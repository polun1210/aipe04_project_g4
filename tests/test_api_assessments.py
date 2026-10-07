import json
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.calculator import FakeCalculator, get_calculator
from app.main import create_app
from app.schemas.assessment import Assessment
from app.schemas.case import CaseProfile
from app.schemas.label import VerificationSubmission, VerifiedProduct
from app.store import TEST_USER_ID, InMemoryStore, get_store

EXAMPLES = Path(__file__).parent.parent / "docs" / "schemas" / "examples"


def _example(name: str) -> dict:
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


class SpyCalculator:
    """記錄收到的評估個案，回傳固定結果，用來確認網址確實透過介面呼叫計算層。"""

    def __init__(self, delegate) -> None:
        self._delegate = delegate
        self.cases: list[CaseProfile] = []

    def verify_product(self, product_id, submission, verified_at) -> VerifiedProduct:
        return self._delegate.verify_product(product_id, submission, verified_at)

    def assess(self, case: CaseProfile) -> Assessment:
        self.cases.append(case)
        return self._delegate.assess(case)


@pytest.fixture
def store() -> InMemoryStore:
    return InMemoryStore()


@pytest.fixture
def client(store) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_store] = lambda: store
    return TestClient(app, raise_server_exceptions=False)


def _create_product(client: TestClient) -> str:
    response = client.post("/api/products", json=_example("05a_verification_submission.json"))
    assert response.status_code == 201
    return response.json()["product_id"]


def _assessment_request(product_ids: list[str]) -> dict:
    return {**_example("03_assessment_request.json"), "product_ids": product_ids}


# ── POST /api/products ──────────────────────────────────────


def test_create_product_returns_new_product_id(client):
    product_id = _create_product(client)
    assert UUID(product_id).version == 4


def test_create_product_stores_recomputed_product(client, store):
    product_id = UUID(_create_product(client))
    [stored] = store.get_products([product_id])
    submission = VerificationSubmission.model_validate(_example("05a_verification_submission.json"))
    assert stored.product_name == submission.product_name
    assert len(stored.nutrients) == len(submission.nutrients)
    assert stored.user_intake.servings_per_day_peak == 1


def test_create_product_rejects_missing_required_field(client):
    body = _example("05a_verification_submission.json")
    del body["serving_info"]
    response = client.post("/api/products", json=body)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_create_product_rejects_client_supplied_computed_fields(client):
    body = _example("05a_verification_submission.json")
    body["user_intake"]["units_per_day_peak"] = 999
    response = client.post("/api/products", json=body)
    assert response.status_code == 422


# ── POST /api/assessments ───────────────────────────────────


def test_assessment_returns_valid_assessment_for_the_created_case(client):
    product_id = _create_product(client)
    response = client.post("/api/assessments", json=_assessment_request([product_id]))
    assert response.status_code == 200
    assessment = Assessment.model_validate(response.json())
    assert assessment.relevant_nutrients


def test_assessment_is_saved_with_test_user(client, store):
    product_id = _create_product(client)
    body = client.post("/api/assessments", json=_assessment_request([product_id])).json()
    [(case, assessment)] = store.assessments
    assert case.user_id == TEST_USER_ID
    assert str(case.case_id) == body["case_id"] == str(assessment.case_id)


def test_assessment_freezes_profile_and_drugs_into_case(client):
    app = create_app()
    store = InMemoryStore()
    spy = SpyCalculator(FakeCalculator())
    app.dependency_overrides[get_store] = lambda: store
    app.dependency_overrides[get_calculator] = lambda: spy
    test_client = TestClient(app, raise_server_exceptions=False)
    product_id = _create_product(test_client)

    test_client.post("/api/assessments", json=_assessment_request([product_id]))

    [case] = spy.cases
    assert case.basic_profile.age == 72
    assert case.basic_profile.age_band == "71+"
    ppi = next(d for d in case.drugs.selected if d.active_ingredient_code == "esomeprazole")
    assert ppi.drug_class_codes == ["ppi"]
    assert ppi.display_name_zh
    assert [str(p.product_id) for p in case.supplements] == [product_id]


def test_assessment_unknown_product_returns_product_not_verified(client):
    response = client.post("/api/assessments", json=_assessment_request([str(uuid4())]))
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "product_not_verified"


def test_assessment_unknown_drug_returns_validation_error(client):
    product_id = _create_product(client)
    body = _assessment_request([product_id])
    body["drugs"]["selected"][0]["active_ingredient_code"] = "not_a_real_drug"
    response = client.post("/api/assessments", json=body)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert "not_a_real_drug" in response.json()["error"]["details"][0]


def test_assessment_rejects_empty_product_ids(client):
    response = client.post("/api/assessments", json=_assessment_request([]))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_assessment_calculator_failure_returns_internal_error_without_leaking(client):
    app = create_app()
    store = InMemoryStore()

    class BrokenCalculator:
        def verify_product(self, product_id, submission, verified_at):
            raise RuntimeError("secret formula table path C:/x")

        def assess(self, case):
            raise RuntimeError("secret formula table path C:/x")

    app.dependency_overrides[get_store] = lambda: store
    app.dependency_overrides[get_calculator] = BrokenCalculator
    response = TestClient(app, raise_server_exceptions=False).post(
        "/api/products", json=_example("05a_verification_submission.json")
    )
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert "secret" not in response.text
