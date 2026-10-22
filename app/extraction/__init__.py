"""標示辨識模組（E）。對外只有兩個函式：check_quality（上傳時的品質檢查）與 extract（交接點 04_supplement_draft）。

VLM 引擎（直接讀出結構，例如 OpenRouter 的 Gemini 3.8 Flash）經規則層（rules.py）整理成真實的辨識草稿；
沒指定引擎時，仍回傳 docs/schemas/examples/ 的固定內容（T01 假版本）；引擎只有文字區塊（OCR）時回錯誤。
品質檢查是真實版本（解析度、光線、模糊、反光，見 quality.py）。
位置框座標系 ＝ 依 EXIF 方向轉正後的圖。
"""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from app.extraction import quality, rules
from app.extraction.engines import Engine, EngineResult, ReplayEngine, TextBlock
from app.extraction.types import ExtractionError, ImageInput
from app.schemas.enums import QualityStatus
from app.schemas.label import ExtractionDraft, ExtractionMeta, SourceImage

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
    Path(__file__).resolve().parents[2] / "docs" / "schemas" / "examples" / "04_supplement_draft.json"
)
_STUB_VERSION = "stub-t01"


def check_quality(images: list[ImageInput]) -> list[SourceImage]:
    """上傳照片時同步呼叫。不呼叫任何付費 API；門檻與校準依據見 quality.py。"""
    results = []
    for img in images:
        reason = quality.assess(img.content)
        status = QualityStatus.REJECTED if reason else QualityStatus.ACCEPTED
        results.append(
            SourceImage(image_id=img.image_id, quality_status=status, reject_reason=reason, image_kind=img.image_kind)
        )
    return results


def extract(
    product_id: UUID,
    images: list[ImageInput],
    quality: list[SourceImage],
    engine: Engine | None = None,
) -> ExtractionDraft:
    """同步呼叫。quality 是上傳時 check_quality 的結果，這裡不再重新檢查，
    所以草稿裡的品質結果與 check_quality 一定一致；只處理 quality_status = accepted 的圖。

    指定 VLM 引擎時：實際呼叫它，經規則層產出真實草稿，三個版本欄位記錄引擎、規則層與同義詞表的版本。
    引擎只回傳文字區塊（OCR，沒有規則層）時：回 ExtractionError，不回假草稿。
    沒指定引擎時：回傳範例草稿，product_id 與照片編號換成呼叫者給的；
    三個版本欄位都標為 stub，避免串接期間的修正紀錄被誤認為真實辨識結果。
    位置框是範例圖的座標，不對應真實照片。
    """
    by_id = {img.image_id: img for img in images}
    if [s.image_id for s in quality] != [img.image_id for img in images]:
        raise ExtractionError("品質檢查結果與照片對不上（照片編號或順序不同）")
    accepted = [by_id[s.image_id] for s in quality if s.quality_status is QualityStatus.ACCEPTED]
    if not accepted:
        raise ExtractionError("沒有通過品質檢查的照片")
    sources = quality

    if engine is not None:
        # 多張照片同時送出，等待時間取最慢的一張，不是加總
        with ThreadPoolExecutor(max_workers=len(accepted)) as pool:
            results = list(pool.map(lambda img: _run_engine(engine, img), accepted))
        if any(r.reading is None for r in results):
            # 只有文字區塊（OCR）、沒有結構化結果：不回範例草稿，免得假成分配上真的引擎版本
            raise ExtractionError("辨識引擎沒有回傳結構化結果")
        return _vlm_draft(product_id, sources, results)

    draft = json.loads(_EXAMPLE_DRAFT.read_text(encoding="utf-8"))
    first_id = accepted[0].image_id
    draft["product_id"] = str(product_id)
    draft["source_images"] = [s.model_dump(mode="json") for s in sources]
    draft["serving_info"]["source_image_id"] = first_id
    for row in draft["nutrients"]:
        row["source_image_id"] = first_id
    draft["extraction_meta"] = {
        "ocr_version": _STUB_VERSION,
        "rule_layer_version": _STUB_VERSION,
        "synonym_table_version": _STUB_VERSION,
        "extracted_at": datetime.now(timezone.utc).isoformat(),
    }
    return ExtractionDraft.model_validate(draft)


def _vlm_draft(product_id: UUID, sources: list[SourceImage], results: list[EngineResult]) -> ExtractionDraft:
    names = rules.load_names()
    readings = [(r.image_id, r.reading) for r in results if r.reading is not None]
    # 多張圖時，每一份量取第一張有讀到、而且數字可信（沒做過數值容錯）的
    serving = next(
        (
            rules.serving_info(rd.serving, image_id)
            for image_id, rd in readings
            if rd.serving and rd.serving.serving_size and not rd.serving.needs_review
        ),
        # 都不可信時取第一個有讀到每一份量的（數字會留空），保留它的照片與位置框讓使用者定位
        next(
            (rules.serving_info(rd.serving, image_id) for image_id, rd in readings if rd.serving),
            rules.serving_info(None, readings[0][0]),
        ),
    )
    # 多張圖讀到的每一份量不同：分不出哪張對，留空讓使用者在核對頁填（supplement-label-output.md 第五節）
    read = [rules.serving_info(rd.serving, image_id) for image_id, rd in readings if rd.serving]
    sizes = {s.serving_size for s in read if s.serving_size}
    units = {s.dose_unit for s in read if s.serving_size and s.dose_unit}  # 沒讀到劑型是未知，不算矛盾
    if len(sizes) > 1 or len(units) > 1:
        serving = serving.model_copy(update=dict(serving_size=None, dose_unit=None))
    intake = next((rules.suggested_intake(rd.suggested_intake_raw) for _, rd in readings if rd.suggested_intake_raw), None)
    return ExtractionDraft(
        product_id=product_id,
        source_images=sources,
        serving_info=serving,
        label_suggested_intake=intake,
        nutrients=rules.build_rows(readings, names),
        extraction_meta=ExtractionMeta(
            ocr_version=results[0].engine_version,
            rule_layer_version=rules.RULE_LAYER_VERSION,
            synonym_table_version=names.version,
            extracted_at=datetime.now(timezone.utc),
        ),
    )


def _run_engine(engine: Engine, image: ImageInput) -> EngineResult:
    """引擎的任何失敗（逾時、網路、格式）都轉成 ExtractionError，後端只需處理這一種。"""
    try:
        return engine.run(image)
    except ExtractionError:
        raise
    except Exception as e:
        raise ExtractionError(f"{image.image_id} 辨識失敗") from e
