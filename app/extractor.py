"""辨識服務的替換點。

辨識組員的真版本好了之後，只要換掉 get_extractor 回傳的實作，網址與前端都不用改。
StubExtractor 不讀圖：品質檢查與保健食品辨識直接呼叫 app.extraction 現有的假函式，
藥包辨識回 04_drug_draft 範例。所以它的內容不可當作正確結果。
"""

import json
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Protocol
from uuid import UUID

from app import extraction
from app.extraction import ExtractionError, ImageInput
from app.schemas.drug_label import DrugDraft
from app.schemas.enums import QualityStatus
from app.schemas.label import ExtractionDraft, SourceImage

_EXAMPLE_DRUG_DRAFT = Path(__file__).resolve().parents[1] / "docs" / "schemas" / "examples" / "04_drug_draft.json"
_STUB_VERSION = "stub"


class Extractor(Protocol):
    def check_quality(self, images: list[ImageInput]) -> list[SourceImage]: ...

    def extract_supplement(
        self, product_id: UUID, images: list[ImageInput], quality: list[SourceImage]
    ) -> ExtractionDraft: ...

    def extract_drugs(self, draft_id: UUID, images: list[ImageInput], quality: list[SourceImage]) -> DrugDraft: ...


class StubExtractor:
    def check_quality(self, images: list[ImageInput]) -> list[SourceImage]:
        return extraction.check_quality(images)

    def extract_supplement(
        self, product_id: UUID, images: list[ImageInput], quality: list[SourceImage]
    ) -> ExtractionDraft:
        return extraction.extract(product_id, images, quality)

    def extract_drugs(self, draft_id: UUID, images: list[ImageInput], quality: list[SourceImage]) -> DrugDraft:
        first_accepted = next((s.image_id for s in quality if s.quality_status is QualityStatus.ACCEPTED), None)
        if first_accepted is None:
            raise ExtractionError("沒有通過品質檢查的照片")
        draft = json.loads(_EXAMPLE_DRUG_DRAFT.read_text(encoding="utf-8"))
        draft["draft_id"] = str(draft_id)
        draft["source_images"] = [s.model_dump(mode="json") for s in quality]
        for row in draft["rows"]:
            row["source_image_id"] = first_accepted
        draft["extraction_meta"] = {
            "ocr_version": _STUB_VERSION,
            "rule_layer_version": _STUB_VERSION,
            "synonym_table_version": _STUB_VERSION,
            "extracted_at": datetime.now(UTC).isoformat(),
        }
        return DrugDraft.model_validate(draft)


@lru_cache(maxsize=1)
def get_extractor() -> Extractor:
    return StubExtractor()
