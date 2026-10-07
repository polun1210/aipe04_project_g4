"""標示辨識模組（E）。對外只有兩個函式：check_quality（交接點 04a）與 extract（交接點 04b）。

目前是假版本（T01）：回傳 docs/schemas/examples/ 的固定內容，讓後端與前端先行串接。
位置框座標系 ＝ 依 EXIF 方向轉正後的圖。
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from app.extraction.engines import Engine, EngineResult, ReplayEngine, TextBlock
from app.extraction.types import ExtractionError, ImageInput
from app.schemas.enums import QualityStatus
from app.schemas.label import ExtractionDraft, SourceImage

__all__ = [
    "Engine",
    "EngineResult",
    "ExtractionError",
    "ImageInput",
    "ReplayEngine",
    "TextBlock",
    "check_quality",
    "extract",
]

_EXAMPLE_DRAFT = (
    Path(__file__).resolve().parents[2] / "docs" / "schemas" / "examples" / "04b_extraction_job_done.json"
)
_STUB_VERSION = "stub-t01"


def check_quality(images: list[ImageInput]) -> list[SourceImage]:
    """POST /api/extractions 時同步呼叫。不呼叫任何付費 API。

    假版本：每張都判為 accepted。
    """
    return [SourceImage(image_id=img.image_id, quality_status=QualityStatus.ACCEPTED) for img in images]


def extract(
    product_id: UUID,
    images: list[ImageInput],
    quality: list[SourceImage],
    engine: Engine | None = None,
) -> ExtractionDraft:
    """非同步工作內呼叫。quality 是上傳時 check_quality 的結果（已回給前端，04a），這裡不再重新檢查，
    所以 04a 與 04b 的品質結果一定一致；只處理 quality_status = accepted 的圖。

    假版本：回傳範例草稿，product_id 與照片編號換成呼叫者給的；三個版本欄位標為 stub，
    避免串接期間的修正紀錄被誤認為真實辨識結果。位置框是範例圖的座標，不對應真實照片。
    指定 engine 時會實際呼叫它，ocr_version 改成該引擎的版本。
    """
    by_id = {img.image_id: img for img in images}
    if [s.image_id for s in quality] != [img.image_id for img in images]:
        raise ExtractionError("品質檢查結果與照片對不上（照片編號或順序不同）")
    accepted = [by_id[s.image_id] for s in quality if s.quality_status is QualityStatus.ACCEPTED]
    if not accepted:
        raise ExtractionError("沒有通過品質檢查的照片")
    sources = quality

    ocr_version = _STUB_VERSION
    if engine is not None:
        results = [_run_engine(engine, img) for img in accepted]
        ocr_version = results[0].engine_version

    draft = json.loads(_EXAMPLE_DRAFT.read_text(encoding="utf-8"))["result"]
    first_id = accepted[0].image_id
    draft["product_id"] = str(product_id)
    draft["source_images"] = [s.model_dump(mode="json") for s in sources]
    draft["serving_info"]["source_image_id"] = first_id
    for row in draft["nutrients"]:
        row["source_image_id"] = first_id
    draft["extraction_meta"] = {
        "ocr_version": ocr_version,
        "rule_layer_version": _STUB_VERSION,
        "synonym_table_version": _STUB_VERSION,
        "extracted_at": datetime.now(timezone.utc).isoformat(),
    }
    return ExtractionDraft.model_validate(draft)


def _run_engine(engine: Engine, image: ImageInput) -> EngineResult:
    """引擎的任何失敗（逾時、網路、格式）都轉成 ExtractionError，後端只需處理這一種。"""
    try:
        return engine.run(image)
    except ExtractionError:
        raise
    except Exception as e:
        raise ExtractionError(f"{image.image_id} 辨識失敗") from e
