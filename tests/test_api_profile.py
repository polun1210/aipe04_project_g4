import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.auth import GoogleIdentity, get_google_verifier
from app.main import create_app
from app.store import InMemoryStore, get_store

EXAMPLES = Path(__file__).parent.parent / "docs" / "schemas" / "examples"
PROFILE = {
    "birth_year": 1960,
    "birth_month": 5,
    "sex": "female",
    "conditions": {"selected": ["hypertension"], "none_selected": False},
}


@pytest.fixture
def store() -> InMemoryStore:
    return InMemoryStore()


def _client(store: InMemoryStore) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_store] = lambda: store
    app.dependency_overrides[get_google_verifier] = lambda: lambda c: GoogleIdentity(c, f"{c}@x.com", c)
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def google_env(monkeypatch):
    monkeypatch.setenv("AUTH", "google")
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "id")
    monkeypatch.setenv("SESSION_SECRET", "s")


@pytest.fixture
def new_user(google_env, store) -> TestClient:
    client = _client(store)
    client.post("/api/auth/google", json={"credential": "newbie"})
    return client


def test_測試帳號預設已填健康資料(monkeypatch, store):
    monkeypatch.delenv("AUTH", raising=False)
    client = _client(store)
    assert client.get("/api/me").json()["profile_completed"] is True
    res = client.get("/api/me/profile")
    assert res.status_code == 200
    assert res.json()["birth_year"] == 1954


def test_測試帳號可修改健康資料(monkeypatch, store):
    monkeypatch.delenv("AUTH", raising=False)
    client = _client(store)
    assert client.put("/api/me/profile", json=PROFILE).status_code == 200
    assert client.get("/api/me/profile").json() == PROFILE


def test_新使用者還沒填資料(new_user):
    assert new_user.get("/api/me").json()["profile_completed"] is False
    res = new_user.get("/api/me/profile")
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "not_found"


def test_新使用者儲存後_profile_completed_變_true(new_user):
    assert new_user.put("/api/me/profile", json=PROFILE).json() == PROFILE
    assert new_user.get("/api/me").json()["profile_completed"] is True
    assert new_user.get("/api/me/profile").json() == PROFILE


@pytest.mark.parametrize(
    "patch",
    [
        {"conditions": {"selected": ["hypertension"], "none_selected": True}},
        {"birth_month": 13},
        {"sex": "other"},
    ],
)
def test_儲存健康資料格式錯誤回_422(new_user, patch):
    res = new_user.put("/api/me/profile", json={**PROFILE, **patch})
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "validation_error"


def test_沒登入存取健康資料回_401(google_env, store):
    client = _client(store)
    assert client.get("/api/me/profile").status_code == 401
    assert client.put("/api/me/profile", json=PROFILE).status_code == 401


def test_使用者_A_的資料_B_讀不到(google_env, store):
    a = _client(store)
    a.post("/api/auth/google", json={"credential": "a"})
    a.put("/api/me/profile", json=PROFILE)
    b = _client(store)
    b.post("/api/auth/google", json={"credential": "b"})
    assert b.get("/api/me/profile").status_code == 404


def test_沒填健康資料就評估回_409(new_user):
    res = new_user.post("/api/assessments", json=json.loads((EXAMPLES / "03_assessment_request.json").read_text(encoding="utf-8")))
    assert res.status_code == 409
    assert res.json() == {"error": {"code": "profile_incomplete", "message": "請先填寫出生年月、性別與慢性疾病"}}
