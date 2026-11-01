import pytest
from fastapi.testclient import TestClient

from app.auth import GoogleIdentity, get_google_verifier
from app.errors import ApiError
from app.main import create_app
from app.schemas.enums import ErrorCode
from app.store import TEST_USER_ID, InMemoryStore, get_store


@pytest.fixture
def store() -> InMemoryStore:
    return InMemoryStore()


def _client(store, verifier=None) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_store] = lambda: store
    if verifier:
        app.dependency_overrides[get_google_verifier] = lambda: verifier
    return TestClient(app, raise_server_exceptions=False)


def _fake_verify(credential: str) -> GoogleIdentity:
    if credential == "bad":
        raise ApiError(401, ErrorCode.UNAUTHORIZED, "Google 登入失敗，請再試一次")
    return GoogleIdentity(sub=credential, email=f"{credential}@example.com", name=f"名字{credential}")


@pytest.fixture
def google_client(monkeypatch, store) -> TestClient:
    monkeypatch.setenv("AUTH", "google")
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("SESSION_SECRET", "test-secret")
    return _client(store, _fake_verify)


def test_沒設_AUTH_時_me_回測試帳號(monkeypatch, store):
    monkeypatch.delenv("AUTH", raising=False)
    res = _client(store).get("/api/me")
    assert res.status_code == 200
    assert res.json() == {"user_id": str(TEST_USER_ID), "email": None, "name": "測試帳號", "profile_completed": True}


def test_沒設_AUTH_時_google_登入回_404(monkeypatch, store):
    monkeypatch.delenv("AUTH", raising=False)
    res = _client(store).post("/api/auth/google", json={"credential": "x"})
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "not_found"


def test_google_登入成功後可查到自己(google_client):
    login = google_client.post("/api/auth/google", json={"credential": "abc"})
    assert login.status_code == 200
    me = google_client.get("/api/me")
    assert me.status_code == 200
    assert me.json() == login.json()
    assert me.json()["email"] == "abc@example.com"


def test_同一個_sub_登入兩次是同一個使用者(google_client):
    first = google_client.post("/api/auth/google", json={"credential": "abc"}).json()["user_id"]
    second = google_client.post("/api/auth/google", json={"credential": "abc"}).json()["user_id"]
    assert first == second


def test_不同_sub_是不同使用者(google_client):
    a = google_client.post("/api/auth/google", json={"credential": "a"}).json()["user_id"]
    b = google_client.post("/api/auth/google", json={"credential": "b"}).json()["user_id"]
    assert a != b


def test_憑證無效時回_401_錯誤格式(google_client):
    res = google_client.post("/api/auth/google", json={"credential": "bad"})
    assert res.status_code == 401
    assert res.json() == {"error": {"code": "unauthorized", "message": "Google 登入失敗，請再試一次"}}


def test_登出後_me_回_401(google_client):
    google_client.post("/api/auth/google", json={"credential": "abc"})
    assert google_client.post("/api/logout").status_code == 204
    assert google_client.get("/api/me").status_code == 401


def test_沒登入也能登出(google_client):
    assert google_client.post("/api/logout").status_code == 204


def test_沒登入打_reports_回_401(google_client):
    res = google_client.get("/api/reports")
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "unauthorized"


def test_google_模式沒設_client_id_時啟動報錯(monkeypatch):
    monkeypatch.setenv("AUTH", "google")
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.setenv("SESSION_SECRET", "s")
    with pytest.raises(RuntimeError, match="GOOGLE_CLIENT_ID"):
        create_app()


def test_google_模式沒設_session_secret_時啟動報錯(monkeypatch):
    monkeypatch.setenv("AUTH", "google")
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "id")
    monkeypatch.delenv("SESSION_SECRET", raising=False)
    with pytest.raises(RuntimeError, match="SESSION_SECRET"):
        create_app()


def test_AUTH_打錯時報錯(monkeypatch):
    monkeypatch.setenv("AUTH", "googel")
    with pytest.raises(ValueError, match="AUTH"):
        create_app()
