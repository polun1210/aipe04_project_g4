"""STORE=pg 下走完整個 API：重啟伺服器資料還在、使用者之間互相看不到。"""

import json
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.auth import get_current_user_id
from app.db import pool as pool_module
from app.main import create_app
from app.store import TEST_USER_ID, close_store, get_store

EXAMPLES = Path(__file__).parents[2] / "docs" / "schemas" / "examples"


def _example(name: str) -> dict:
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


@pytest.fixture
def pg_env(test_database_url, monkeypatch):
    monkeypatch.setenv("STORE", "pg")
    monkeypatch.setenv("AUTH", "test")
    monkeypatch.setenv("DATABASE_URL", test_database_url)
    get_store.cache_clear()
    pool_module.close_pool()
    yield
    close_store()
    get_store.cache_clear()


def _create_report(client: TestClient) -> str:
    product_id = client.post("/api/products", json=_example("05a_verification_submission.json")).json()["product_id"]
    request = {**_example("03_assessment_request.json"), "product_ids": [product_id]}
    case_id = client.post("/api/assessments", json=request).json()["case_id"]
    response = client.post(f"/api/assessments/{case_id}/report")
    assert response.status_code == 201, response.text
    return response.json()["report_id"]


def test_重啟伺服器後報告歷史還在(pg_env):
    with TestClient(create_app()) as first_run:  # 進入 with 才會跑 lifespan：開連線池、確認測試帳號
        report_id = _create_report(first_run)

    # 模擬重啟：關掉連線池、清掉快取，整個應用程式重建
    close_store()
    get_store.cache_clear()
    with TestClient(create_app()) as second_run:
        listed = [r["report_id"] for r in second_run.get("/api/reports").json()]
        assert report_id in listed
        assert second_run.get(f"/api/reports/{report_id}").status_code == 200


def test_另一個使用者不能拿別人的產品去評估也看不到別人的報告(pg_env):
    with TestClient(create_app()) as client:
        product_id = client.post("/api/products", json=_example("05a_verification_submission.json")).json()["product_id"]
        report_id = _create_report(client)

        other = get_store().find_or_create_google_user(f"sub-{uuid4()}", None, "乙")
        assert other != TEST_USER_ID
        client.app.dependency_overrides[get_current_user_id] = lambda: other
        get_store().save_profile(other, get_store().get_profile(TEST_USER_ID))

        request = {**_example("03_assessment_request.json"), "product_ids": [product_id]}
        response = client.post("/api/assessments", json=request)
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "product_not_found"
        assert client.get("/api/reports").json() == []
        assert client.get(f"/api/reports/{report_id}").status_code == 404


def test_STORE的值不認得時直接報錯(monkeypatch):
    from app.store import store_mode

    monkeypatch.setenv("STORE", "redis")
    with pytest.raises(RuntimeError, match="memory 或 pg"):
        store_mode()


def test_資料庫沒有這版參考資料時啟動就報錯並提示匯入(pg_env, monkeypatch):
    class OldCatalog:
        def load_reference(self):
            return type("Ref", (), {"version": "9999.0.0"})()

    monkeypatch.setattr("app.store.get_catalog_source", lambda: OldCatalog())
    with pytest.raises(RuntimeError, match="import_catalog"):
        with TestClient(create_app()):
            pass
