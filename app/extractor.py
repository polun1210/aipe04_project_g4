"""辨識服務的替換點。

用環境變數 EXTRACTOR 明確切換，不因為「沒設金鑰」就自動改用假版本：
假草稿看起來跟真的一樣，部署時忘了設定也不會有人發現。
- stub（沒設時的預設，開發與 CI 用）：StubExtractor 不讀圖，品質檢查與保健食品辨識直接呼叫
  app.extraction 現有的假函式，藥包辨識回 04_drug_draft 範例，內容不可當作正確結果
- openrouter：保健食品與藥包照片都真的送 OpenRouter 辨識；金鑰或型號沒設好時第一次呼叫就報錯
"""

import json
import logging
import os
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Protocol
from uuid import UUID

from app import extraction
from app.extraction import ExtractionError, ImageInput
from app.catalog_source import get_catalog_source
from app.extraction.drugs import DrugOpenRouterEngine, extract_drugs
from app.extraction.engines.openrouter import OpenRouterEngine
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


class OpenRouterExtractor(StubExtractor):
    """保健食品與藥包走真辨識。品質檢查仍是假版本（每張都通過）。"""

    def __init__(self, engine: OpenRouterEngine, drug_engine: DrugOpenRouterEngine) -> None:
        self.engine = engine
        self.drug_engine = drug_engine

    def extract_supplement(
        self, product_id: UUID, images: list[ImageInput], quality: list[SourceImage]
    ) -> ExtractionDraft:
        return extraction.extract(product_id, images, quality, engine=self.engine)

    def extract_drugs(self, draft_id: UUID, images: list[ImageInput], quality: list[SourceImage]) -> DrugDraft:
        drug_items = get_catalog_source().load().drug_items
        return extract_drugs(draft_id, images, quality, self.drug_engine, drug_items)


@lru_cache(maxsize=1)
def get_extractor() -> Extractor:
    mode = os.environ.get("EXTRACTOR", "stub")
    if mode == "stub":
        logging.getLogger(__name__).warning("EXTRACTOR=stub：辨識回傳假資料，正式環境要設成 openrouter")
        return StubExtractor()
    if mode == "openrouter":
        return OpenRouterExtractor(OpenRouterEngine.from_env(), DrugOpenRouterEngine.from_env())
    raise ValueError(f"EXTRACTOR 只能是 stub 或 openrouter，收到 {mode!r}")
