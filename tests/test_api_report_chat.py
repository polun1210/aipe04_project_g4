import json
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.auth import get_current_user_id
from app.main import create_app
from app.report_chat import PROMPT_VERSION, ReportChat, get_report_chat
from app.extraction.engines.openrouter import Route
from app.store import InMemoryStore, get_store

EXAMPLES = Path(__file__).parent.parent / "docs" / "schemas" / "examples"


def _example(name: str) -> dict:
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


class FakeTransport:
    def __init__(self, reply: str = "魚油超過上限。") -> None:
        self.reply = reply
        self.bodies: list[dict] = []

    def __call__(self, body: dict, timeout: float) -> dict:
        self.bodies.append(body)
        return {"choices": [{"message": {"content": self.reply}}]}


@pytest.fixture
def store() -> InMemoryStore:
    return InMemoryStore()


@pytest.fixture
def transport() -> FakeTransport:
    return FakeTransport()


@pytest.fixture
def client(store, transport) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_store] = lambda: store
    app.dependency_overrides[get_report_chat] = lambda: ReportChat(transport, Route("anthropic/test", "anthropic"))
    return TestClient(app, raise_server_exceptions=False)


def _report_id(client: TestClient) -> str:
    product_id = client.post("/api/products", json=_example("05a_verification_submission.json")).json()["product_id"]
    request = {**_example("03_assessment_request.json"), "product_ids": [product_id]}
    case_id = client.post("/api/assessments", json=request).json()["case_id"]
    return client.post(f"/api/assessments/{case_id}/report").json()["report_id"]


def test_chat_returns_answer_and_sends_report_to_llm(client, transport):
    report_id = _report_id(client)
    response = client.post(f"/api/reports/{report_id}/chat", json={"question": "哪些項目超過上限？"})
    assert response.status_code == 200
    assert response.json() == {"answer": "魚油超過上限。"}
    prompt = transport.bodies[0]["messages"][0]["content"]
    assert report_id in prompt and "哪些項目超過上限？" in prompt
    assert transport.bodies[0]["provider"] == {"only": ["anthropic"], "allow_fallbacks": False}
    assert PROMPT_VERSION.startswith("report-chat-v")


def test_chat_rejects_blank_question(client, transport):
    report_id = _report_id(client)
    assert client.post(f"/api/reports/{report_id}/chat", json={"question": "  "}).status_code == 422
    assert transport.bodies == []


def test_chat_other_users_report_is_404(client, store, transport):
    report_id = _report_id(client)
    client.app.dependency_overrides[get_current_user_id] = lambda: uuid4()
    response = client.post(f"/api/reports/{report_id}/chat", json={"question": "哪些項目超過上限？"})
    assert response.status_code == 404
    assert transport.bodies == []


def test_chat_unknown_report_is_404(client):
    response = client.post(f"/api/reports/{uuid4()}/chat", json={"question": "哪些項目超過上限？"})
    assert response.status_code == 404


def test_chat_requires_login(client):
    def deny():
        from app.errors import ApiError
        from app.schemas.enums import ErrorCode

        raise ApiError(401, ErrorCode.UNAUTHORIZED, "請先登入")

    client.app.dependency_overrides[get_current_user_id] = deny
    response = client.post(f"/api/reports/{uuid4()}/chat", json={"question": "x"})
    assert response.status_code == 401


def test_chat_disabled_when_narrator_is_template(client, store, transport, monkeypatch):
    report_id = _report_id(client)
    monkeypatch.setenv("NARRATOR", "template")
    get_report_chat.cache_clear()
    del client.app.dependency_overrides[get_report_chat]
    response = client.post(f"/api/reports/{report_id}/chat", json={"question": "哪些項目超過上限？"})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "chat_disabled"
    assert transport.bodies == []
    get_report_chat.cache_clear()


def test_chat_llm_failure_is_502_without_detail(client, transport):
    def boom(body, timeout):
        raise OSError("secret detail")

    report_id = _report_id(client)
    client.app.dependency_overrides[get_report_chat] = lambda: ReportChat(boom, Route("m", "anthropic"))
    response = client.post(f"/api/reports/{report_id}/chat", json={"question": "哪些項目超過上限？"})
    assert response.status_code == 502
    assert "secret" not in response.text


class SequenceTransport:
    def __init__(self, *replies: str) -> None:
        self.replies = list(replies)
        self.calls = 0

    def __call__(self, body: dict, timeout: float) -> dict:
        reply = self.replies[min(self.calls, len(self.replies) - 1)]
        self.calls += 1
        return {"choices": [{"message": {"content": reply}}]}


def _chat_with(client, transport) -> None:
    client.app.dependency_overrides[get_report_chat] = lambda: ReportChat(transport, Route("m", "anthropic"))


def _ask(client, report_id: str):
    return client.post(f"/api/reports/{report_id}/chat", json={"question": "哪些項目超過上限？"})


FALLBACK = "這個問題請詢問醫師或藥師。"


def test_chat_answer_quoting_report_numbers_is_not_blocked(client):
    # 鎂的上限 350、維生素 D 的 B12 與 D3 名稱裡的數字都不該被擋
    transport = SequenceTransport("鎂的上限是 350 mg，維生素 D3 與 B12 都在報告裡。")
    _chat_with(client, transport)
    response = _ask(client, _report_id(client))
    assert response.json() == {"answer": "鎂的上限是 350 mg，維生素 D3 與 B12 都在報告裡。"}
    assert transport.calls == 1


def test_chat_retries_once_then_returns_second_answer(client):
    transport = SequenceTransport("你每天吃 9999 mg", "魚油超過上限。")
    _chat_with(client, transport)
    response = _ask(client, _report_id(client))
    assert response.json() == {"answer": "魚油超過上限。"}
    assert transport.calls == 2


def test_chat_returns_fixed_sentence_without_model_text_after_two_failures(client, caplog):
    bad = "請立即停藥，每天吃 9999 mg"
    transport = SequenceTransport(bad)
    _chat_with(client, transport)
    with caplog.at_level("WARNING"):
        response = _ask(client, _report_id(client))
    assert response.status_code == 200
    assert response.json() == {"answer": FALLBACK}
    assert transport.calls == 2
    assert "9999" not in response.text and "停藥" not in response.text
    assert "強烈字眼" in caplog.text  # 原因只進後端日誌


def test_chat_transport_failure_stays_502(client):
    def boom(body, timeout):
        raise TimeoutError("slow")

    _chat_with(client, boom)
    assert _ask(client, _report_id(client)).status_code == 502
