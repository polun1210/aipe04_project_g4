import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import TypeAdapter

from app.corrections import UnknownRowError, drug_corrections, label_corrections
from app.main import create_app
from app.schemas.case import AssessmentRequest
from app.schemas.drug_label import DrugCorrection, DrugDraft
from app.schemas.enums import CorrectionType
from app.schemas.label import ExtractionDraft, LabelCorrection, VerificationSubmission
from app.store import TEST_USER_ID, InMemoryStore, get_store

EXAMPLES = Path(__file__).parent.parent / "docs" / "schemas" / "examples"
AT = datetime(2026, 10, 23, 9, 0, tzinfo=UTC)


def _example(name: str):
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


@pytest.fixture
def draft() -> ExtractionDraft:
    return ExtractionDraft.model_validate(_example("04_supplement_draft.json"))


@pytest.fixture
def submission() -> VerificationSubmission:
    return VerificationSubmission.model_validate(_example("05a_verification_submission.json"))


def _paths(corrections: list[LabelCorrection]) -> dict[str, LabelCorrection]:
    return {c.field_path: c for c in corrections}


# ── 比對 ─────────────────────────────────────────────────────


def test_example_draft_and_submission_give_example_corrections(draft, submission):
    product_id = UUID("a1000000-0000-4000-8000-000000000001")
    expected = TypeAdapter(list[LabelCorrection]).validate_python(_example("05b_label_corrections.json"))
    actual = label_corrections(draft, submission, product_id, AT)
    strip = {"corrected_at"}
    assert [c.model_dump(exclude=strip) for c in actual] == [c.model_dump(exclude=strip) for c in expected]


def test_unchanged_submission_has_no_corrections(draft, submission):
    rows = submission.nutrients
    fixed = [r.model_copy(update={"per_serving": 2.4}) if r.row_id == "r04" else r for r in rows]
    assert label_corrections(draft, submission.model_copy(update={"nutrients": fixed}), uuid4(), AT) == []


def test_serving_size_change_is_recorded(draft, submission):
    changed = submission.model_copy(update={"serving_info": submission.serving_info.model_copy(update={"serving_size": 2})})
    c = _paths(label_corrections(draft, changed, uuid4(), AT))["serving_info.serving_size"]
    assert (c.correction_type, c.model_value, c.corrected_value) == (CorrectionType.MODIFIED, "1.0", "2.0")


def test_added_and_removed_rows_are_recorded(draft, submission):
    new_row = submission.nutrients[0].model_copy(update={"row_id": None})
    rows = [r for r in submission.nutrients if r.row_id != "r08"] + [new_row]
    corrections = _paths(label_corrections(draft, submission.model_copy(update={"nutrients": rows}), uuid4(), AT))

    added = corrections["nutrients.new1"]
    assert added.correction_type is CorrectionType.ADDED and added.model_value is None
    assert json.loads(added.corrected_value)["standard_code"] == "vitamin_d"

    removed = corrections["nutrients.r08"]
    assert removed.correction_type is CorrectionType.REMOVED and removed.corrected_value is None
    assert json.loads(removed.model_value)["scope_status"] == "unresolved"


def test_corrections_carry_draft_versions(draft, submission):
    [c] = label_corrections(draft, submission, uuid4(), AT)
    meta = draft.extraction_meta
    assert (c.ocr_version, c.rule_layer_version, c.synonym_table_version) == (
        meta.ocr_version,
        meta.rule_layer_version,
        meta.synonym_table_version,
    )


def test_row_not_in_draft_is_error(draft, submission):
    rows = [*submission.nutrients, submission.nutrients[0].model_copy(update={"row_id": "r99"})]
    with pytest.raises(UnknownRowError) as e:
        label_corrections(draft, submission.model_copy(update={"nutrients": rows}), uuid4(), AT)
    assert e.value.row_ids == ["r99"]


# ── POST /api/products ──────────────────────────────────────


@pytest.fixture
def store(draft) -> InMemoryStore:
    s = InMemoryStore()
    s.save_supplement_draft(TEST_USER_ID, draft)
    return s


@pytest.fixture
def client(store) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_store] = lambda: store
    return TestClient(app, raise_server_exceptions=False)


def _body(draft_product_id: str | None = None, **changes) -> dict:
    body = {**_example("05a_verification_submission.json"), **changes}
    if draft_product_id is not None:
        body["draft_product_id"] = draft_product_id
    return body


def test_submission_with_draft_saves_corrections(client, store, draft):
    response = client.post("/api/products", json=_body(str(draft.product_id)))
    assert response.status_code == 201
    [(user_id, correction)] = store.label_corrections
    assert user_id == TEST_USER_ID
    assert correction.product_id == UUID(response.json()["product_id"])
    assert correction.field_path == "nutrients.r04.per_serving"


def test_submission_without_draft_saves_no_corrections(client, store):
    assert client.post("/api/products", json=_body()).status_code == 201
    assert store.label_corrections == []


def test_missing_draft_does_not_block_submission(client, store):
    assert client.post("/api/products", json=_body(str(uuid4()))).status_code == 201
    assert store.label_corrections == []


def test_row_not_in_draft_is_422(client, store, draft):
    body = _body(str(draft.product_id))
    body["nutrients"] = [*body["nutrients"], {**body["nutrients"][0], "row_id": "r99"}]
    response = client.post("/api/products", json=body)
    assert response.status_code == 422
    assert response.json()["error"]["details"] == ["nutrients：row_id r99 不在辨識草稿裡"]
    assert store.label_corrections == []


def test_posting_raw_draft_is_rejected(client):
    response = client.post("/api/products", json=_example("04_supplement_draft.json"))
    assert response.status_code == 422


# ── 藥名修正紀錄（05c）─────────────────────────────────────────

CASE_ID = UUID("c0000000-0000-4000-8000-000000000001")


@pytest.fixture
def drug_draft() -> DrugDraft:
    return DrugDraft.model_validate(_example("04_drug_draft.json"))


@pytest.fixture
def drug_request() -> AssessmentRequest:
    return AssessmentRequest.model_validate(_example("03_assessment_request.json"))


def test_example_drug_draft_and_request_give_example_corrections(drug_draft, drug_request):
    expected = TypeAdapter(list[DrugCorrection]).validate_python(_example("05c_drug_corrections.json"))
    actual = drug_corrections({drug_draft.draft_id: drug_draft}, drug_request.drugs.selected, CASE_ID, AT)
    strip = {"corrected_at"}
    assert [c.model_dump(exclude=strip) for c in actual] == [c.model_dump(exclude=strip) for c in expected]


def test_width_and_case_changes_are_not_corrections(drug_draft, drug_request):
    drugs = [d.model_copy(update={"name": "  ＺＹＬＯＲＩＣ 100MG "}) if d.row_id == "d04" else d for d in drug_request.drugs.selected]
    paths = _paths(drug_corrections({drug_draft.draft_id: drug_draft}, drugs, CASE_ID, AT))
    assert "rows.d04.name" not in paths


def test_removed_drug_is_recorded(drug_draft, drug_request):
    drugs = [d for d in drug_request.drugs.selected if d.row_id != "d03"]
    c = _paths(drug_corrections({drug_draft.draft_id: drug_draft}, drugs, CASE_ID, AT))["rows.d03"]
    assert (c.correction_type, c.model_value, c.corrected_value) == (CorrectionType.REMOVED, "耐適恩", None)
    assert c.draft_id == drug_draft.draft_id


def test_missing_draft_produces_only_added_rows(drug_request):
    corrections = drug_corrections({}, drug_request.drugs.selected, CASE_ID, AT)
    assert [c.field_path for c in corrections] == ["rows.new1"]


def test_drug_row_not_in_draft_is_error(drug_draft, drug_request):
    drugs = [*drug_request.drugs.selected, drug_request.drugs.selected[0].model_copy(update={"row_id": "d99"})]
    with pytest.raises(UnknownRowError) as e:
        drug_corrections({drug_draft.draft_id: drug_draft}, drugs, CASE_ID, AT)
    assert e.value.row_ids == ["d99"]


def test_added_correction_must_not_have_draft_versions():
    with pytest.raises(ValueError):
        DrugCorrection(
            case_id=CASE_ID, draft_id=None, field_path="rows.new1", correction_type=CorrectionType.ADDED,
            model_value=None, corrected_value="x", ocr_version="v", rule_layer_version=None,
            synonym_table_version=None, corrected_at=AT,
        )  # fmt: skip


# ── POST /api/assessments 存藥名修正紀錄 ─────────────────────


def _assess_with_drug_draft(client, store, drug_draft, owner=TEST_USER_ID, **drug_changes):
    store.save_drug_draft(owner, drug_draft)
    product_id = client.post("/api/products", json=_body()).json()["product_id"]
    body = {**_example("03_assessment_request.json"), "product_ids": [product_id]}
    body["drugs"]["selected"] = [{**d, **drug_changes.get(d["row_id"] or "", {})} for d in body["drugs"]["selected"]]
    return client.post("/api/assessments", json=body)


def test_assessment_saves_drug_corrections(client, store, drug_draft):
    response = _assess_with_drug_draft(client, store, drug_draft)
    assert response.status_code == 200
    saved = [c for _, c in store.drug_corrections]
    assert [c.field_path for c in saved] == ["rows.d05.name", "rows.new1"]
    assert all(c.case_id == UUID(response.json()["case_id"]) for c in saved)
    assert {u for u, _ in store.drug_corrections} == {TEST_USER_ID}


def test_assessment_drug_row_not_in_draft_is_422_and_saves_nothing(client, store, drug_draft):
    response = _assess_with_drug_draft(client, store, drug_draft, d05={"row_id": "d99"})
    assert response.status_code == 422
    assert response.json()["error"]["details"] == ["drugs：row_id d99 不在藥包草稿裡"]
    assert store.drug_corrections == [] and store.assessments == []


def test_assessment_ignores_other_users_drug_draft_for_corrections(client, store, drug_draft):
    assert _assess_with_drug_draft(client, store, drug_draft, owner=uuid4()).status_code == 200
    assert [c.field_path for _, c in store.drug_corrections] == ["rows.new1"]
