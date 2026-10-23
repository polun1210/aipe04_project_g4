"""W4 驗收「無法判定的都有標示」：每一種揭露都要從計算結果原樣進到報告。"""

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.calculator import FakeCalculator, undetermined_amounts
from app.catalog_source import get_catalog_source
from app.main import create_app
from app.reporting import NarratedReporter
from app.schemas.assessment import Assessment, UndeterminedAmount
from app.schemas.case import CaseProfile
from app.schemas.label import VerificationSubmission
from app.store import InMemoryStore, get_store

EXAMPLES = Path(__file__).parent.parent / "docs" / "schemas" / "examples"
AT = datetime(2026, 10, 23, 9, 0, tzinfo=UTC)


def _example(name: str):
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


def _submission_with_rows(rows: list[dict]) -> VerificationSubmission:
    return VerificationSubmission.model_validate({**_example("05a_verification_submission.json"), "nutrients": rows})


SEAWEED_CALCIUM = {  # 知道是鈣，但標示沒寫元素量、型態也不在換算表 → 含量無法判定
    "row_id": "r01", "standard_code": "calcium", "scope_status": "in_scope",
    "nutrient_form_code": "seaweed_calcium", "per_serving": 500, "unit": "mg",
}  # fmt: skip
RED_YEAST = {"row_id": "r02", "standard_code": "red_yeast_rice", "scope_status": "in_scope"}
UNRESOLVED = {"row_id": "r03", "standard_code": None, "scope_status": "unresolved"}


@pytest.fixture
def case() -> CaseProfile:
    base = CaseProfile.model_validate(_example("case_profile.json"))
    product = FakeCalculator().verify_product(
        uuid4(), _submission_with_rows([SEAWEED_CALCIUM, RED_YEAST, UNRESOLVED]), AT
    )
    return base.model_copy(update={"supplements": [product]})


def test_only_target_nutrients_with_unknown_amount_are_undetermined(case):
    [product] = case.supplements
    assert undetermined_amounts(case) == [
        UndeterminedAmount(product_id=product.product_id, row_id="r01", raw_name=None, nutrient_code="calcium")
    ]


def test_fake_calculator_fills_undetermined_from_case(case):
    assessment = FakeCalculator().assess(case)
    assert [u.nutrient_code for u in assessment.disclosures.undetermined_amounts] == ["calcium"]


def test_every_disclosure_reaches_report_unchanged(case):
    assessment = FakeCalculator().assess(case)
    disclosures = assessment.disclosures.model_copy(
        update={"unresolved_drugs": ["看不清楚的藥"], "unresolved_ingredients": ["海藻鈣粉"]}
    )
    assessment = assessment.model_copy(update={"disclosures": disclosures})
    report = NarratedReporter(get_catalog_source(), narrator=None).build(case, assessment, AT)
    assert report.disclosures == disclosures
    for field in ("out_of_scope_ingredients", "unresolved_ingredients", "out_of_scope_drugs", "unresolved_drugs",
                  "drug_source_not_counted", "undetermined_amounts"):  # fmt: skip
        assert getattr(report.disclosures, field), f"{field} 應該有內容，測試才有意義"


def test_summary_mentions_undetermined_amount_and_unresolved_drug(case):
    assessment = FakeCalculator().assess(case)
    disclosures = assessment.disclosures.model_copy(update={"unresolved_drugs": ["看不清楚的藥"]})
    assessment = assessment.model_copy(update={"disclosures": disclosures})
    summary = NarratedReporter(get_catalog_source(), narrator=None).build(case, assessment, AT).summary
    assert "鈣的含量無法判定，沒有算進上限比對" in summary
    assert "無法判斷是否有交互作用" in summary


def test_summary_without_undetermined_has_no_such_sentence():
    case = CaseProfile.model_validate(_example("case_profile.json"))
    assessment = Assessment.model_validate(_example("06_assessment.json"))
    summary = NarratedReporter(get_catalog_source(), narrator=None).build(case, assessment, AT).summary
    assert "含量無法判定" not in summary


def test_api_report_lists_undetermined_amount():
    app = create_app()
    store = InMemoryStore()
    app.dependency_overrides[get_store] = lambda: store
    client = TestClient(app, raise_server_exceptions=False)
    body = {**_example("05a_verification_submission.json"), "nutrients": [SEAWEED_CALCIUM]}
    product_id = client.post("/api/products", json=body).json()["product_id"]
    request = {**_example("03_assessment_request.json"), "product_ids": [product_id]}
    case_id = client.post("/api/assessments", json=request).json()["case_id"]

    report = client.post(f"/api/assessments/{case_id}/report").json()

    [item] = report["disclosures"]["undetermined_amounts"]
    assert (item["product_id"], item["nutrient_code"]) == (product_id, "calcium")
    assert "含量無法判定" in report["summary"]
