import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.schemas.report import Report, ReportSummary
from app.store import TAIPEI_TZ, InMemoryStore, get_store

EXAMPLES = Path(__file__).parent.parent / "docs" / "schemas" / "examples"


def _example(name: str) -> dict:
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


@pytest.fixture
def store() -> InMemoryStore:
    return InMemoryStore()


@pytest.fixture
def client(store) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_store] = lambda: store
    return TestClient(app, raise_server_exceptions=False)


def _assess(client: TestClient) -> str:
    product_id = client.post("/api/products", json=_example("05a_verification_submission.json")).json()["product_id"]
    request = {**_example("03_assessment_request.json"), "product_ids": [product_id]}
    response = client.post("/api/assessments", json=request)
    assert response.status_code == 200
    return response.json()["case_id"]


def _make_report(client: TestClient) -> dict:
    response = client.post(f"/api/assessments/{_assess(client)}/report")
    assert response.status_code == 201
    return response.json()


# ── POST /api/assessments/{case_id}/report ──────────────────


def test_create_report_returns_201_with_valid_report(client):
    case_id = _assess(client)
    response = client.post(f"/api/assessments/{case_id}/report")
    assert response.status_code == 201
    assert Report.model_validate(response.json()).case_id == UUID(case_id)


def test_create_report_twice_returns_same_report_with_200(client):
    case_id = _assess(client)
    first = client.post(f"/api/assessments/{case_id}/report")
    second = client.post(f"/api/assessments/{case_id}/report")
    assert second.status_code == 200
    assert second.json()["report_id"] == first.json()["report_id"]


def test_create_report_for_unknown_case_is_404(client):
    response = client.post(f"/api/assessments/{uuid4()}/report")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_create_report_for_other_users_case_is_404(client, store):
    case_id = _assess(client)
    case, assessment = store.assessments[0]
    store.assessments[0] = (case.model_copy(update={"user_id": uuid4()}), assessment)
    assert client.post(f"/api/assessments/{case_id}/report").status_code == 404


# ── GET /api/reports ────────────────────────────────────────


def test_list_reports_newest_first_with_counts(client, store):
    first = _make_report(client)
    second = _make_report(client)
    older = datetime.now(UTC) - timedelta(minutes=5)
    store._reports[0] = (store._reports[0][0], store._reports[0][1].model_copy(update={"generated_at": older}))

    rows = client.get("/api/reports").json()
    summaries = [ReportSummary.model_validate(r) for r in rows]
    assert [str(s.report_id) for s in summaries] == [second["report_id"], first["report_id"]]
    assert summaries[0].drug_count == len(second["profile"]["drugs"])
    assert summaries[0].product_count == len(second["products"])


def test_list_reports_filters_by_taipei_date(client, store):
    _make_report(client)
    today = datetime.now(TAIPEI_TZ).date()
    assert len(client.get("/api/reports", params={"date_from": str(today), "date_to": str(today)}).json()) == 1
    tomorrow = today + timedelta(days=1)
    assert client.get("/api/reports", params={"date_from": str(tomorrow)}).json() == []
    yesterday = today - timedelta(days=1)
    assert client.get("/api/reports", params={"date_to": str(yesterday)}).json() == []


def test_list_reports_uses_taipei_day_boundary(client, store):
    _make_report(client)
    user_id, report = store._reports[0]
    # UTC 16:30 = 台灣隔天 00:30
    utc_evening = datetime(2026, 10, 15, 16, 30, tzinfo=UTC)
    store._reports[0] = (user_id, report.model_copy(update={"generated_at": utc_evening}))
    assert len(client.get("/api/reports", params={"date_from": "2026-10-16", "date_to": "2026-10-16"}).json()) == 1
    assert client.get("/api/reports", params={"date_to": "2026-10-15"}).json() == []


def test_list_reports_from_after_to_is_422(client):
    response = client.get("/api/reports", params={"date_from": "2026-10-20", "date_to": "2026-10-10"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_list_reports_hides_other_users_reports(client, store):
    _make_report(client)
    store._reports[0] = (uuid4(), store._reports[0][1])
    assert client.get("/api/reports").json() == []


# ── GET /api/reports/{report_id} ────────────────────────────


def test_get_report_returns_stored_report(client):
    report = _make_report(client)
    response = client.get(f"/api/reports/{report['report_id']}")
    assert response.status_code == 200
    assert response.json() == report


def test_get_unknown_report_is_404(client):
    assert client.get(f"/api/reports/{uuid4()}").status_code == 404
