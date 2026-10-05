"""辨識模組假版本（T01）：只從兩個對外函式測外部行為。"""

from uuid import UUID

import pytest

from app.extraction import EngineResult, ExtractionError, ImageInput, ReplayEngine, check_quality, extract
from app.schemas.enums import QualityStatus
from app.schemas.label import ExtractionDraft, SourceImage

PRODUCT_ID = UUID("b2000000-0000-4000-8000-000000000002")
IMAGES = [ImageInput(image_id="p01-img01", content=b"fake"), ImageInput(image_id="p01-img02", content=b"fake")]


def test_check_quality_returns_one_result_per_image():
    results = check_quality(IMAGES)
    assert [r.image_id for r in results] == ["p01-img01", "p01-img02"]
    assert all(isinstance(r, SourceImage) for r in results)


def test_stub_accepts_every_image():
    assert all(r.quality_status is QualityStatus.ACCEPTED for r in check_quality(IMAGES))


def test_extract_returns_valid_draft_for_given_product():
    draft = extract(PRODUCT_ID, IMAGES)
    ExtractionDraft.model_validate(draft.model_dump())
    assert draft.product_id == PRODUCT_ID


def test_extract_references_only_given_images():
    draft = extract(PRODUCT_ID, IMAGES)
    given = {img.image_id for img in IMAGES}
    assert {s.image_id for s in draft.source_images} == given
    assert {n.source_image_id for n in draft.nutrients} <= given


def test_extract_without_images_raises_extraction_error():
    with pytest.raises(ExtractionError):
        extract(PRODUCT_ID, [])


def test_extract_with_replay_engine_records_engine_version(tmp_path):
    for img in IMAGES:
        recorded = EngineResult(image_id=img.image_id, engine_version="replay-test-1", blocks=[])
        (tmp_path / f"{img.image_id}.json").write_text(recorded.model_dump_json(), encoding="utf-8")
    draft = extract(PRODUCT_ID, IMAGES, engine=ReplayEngine(tmp_path))
    assert draft.extraction_meta.ocr_version == "replay-test-1"


def test_missing_recording_raises_extraction_error(tmp_path):
    with pytest.raises(ExtractionError):
        extract(PRODUCT_ID, IMAGES, engine=ReplayEngine(tmp_path))


def test_stub_marks_all_versions_as_stub():
    meta = extract(PRODUCT_ID, IMAGES).extraction_meta
    assert (meta.ocr_version, meta.rule_layer_version, meta.synonym_table_version) == ("stub-t01",) * 3


def test_any_engine_failure_becomes_extraction_error():
    class TimingOutEngine:
        def run(self, image):
            raise TimeoutError("engine timed out")

    with pytest.raises(ExtractionError):
        extract(PRODUCT_ID, IMAGES, engine=TimingOutEngine())
