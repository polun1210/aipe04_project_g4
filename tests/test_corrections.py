import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import TypeAdapter

from app.corrections import UnknownRowError, label_corrections
from app.main import create_app
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
