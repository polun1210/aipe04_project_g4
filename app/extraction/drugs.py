"""藥包辨識（交接點 04_drug_draft）：藥包照片 → DrugDraft。

VLM（同保健食品，經 OpenRouter 的 Gemini 3.8 Flash）只讀出「藥包上寫了什麼」：藥名原文、商品名、學名、位置；
再用後端的藥名對照（app/drug_mapping.py）預填有效成分。對照只是預填，送出評估時後端會重新對照。
"""

import hashlib
import json
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from uuid import UUID

from pydantic import Field, ValidationError

from app.drug_mapping import map_drug_name
from app.extraction.engines.base import EngineRecording
from app.extraction.engines.gemini import _to_bbox
from app.extraction.engines.openrouter import OpenRouterEngine
from app.extraction.types import ExtractionError, ImageInput
from app.schemas.catalog import DrugItem
from app.schemas.common import StrictModel
from app.schemas.drug_label import DrugDraft, DrugDraftRow
from app.schemas.enums import QualityStatus, ScopeStatus
from app.schemas.label import ExtractionMeta, SourceImage

MAPPING_VERSION = "drug-map-v1"

PROMPT = """這是一張台灣的藥袋、藥品資訊單或處方箋照片。只根據圖上看得到的文字，列出圖中每一項藥品，依圖上順序。
不要猜測，不要用你知道的藥名去「修正」圖上的拼字；看不清楚或沒寫就填 null（陣列填 []）。不要輸出任何病人資料。
同一項藥品只列一次（不要因為有兩種用法就列兩次）。
- raw_name：藥名欄的主要藥名原文，照抄一行（例如「Glucophage 500mg/Tab <Metformin>」），不含病人資料與說明文字
- brand_name：商品名，只寫名稱本身、不含含量與劑型（例如「立普妥」「Lipitor」「HYZAAR」），沒有就 null
- generic_names：圖上明確寫出的學名／成分英文，照抄拼字、不含含量；複方列多個；沒寫就 []
- box_2d：這項藥名在照片上的位置 [ymin, xmin, ymax, xmax]，以 0–1000 正規化；無法定位就填 null"""


class _DrugItem(StrictModel):
    raw_name: str
    brand_name: str | None
    generic_names: list[str]
    box_2d: list[int] | None = Field(description="[ymin, xmin, ymax, xmax]，0–1000 正規化")


class _DrugReading(StrictModel):
    items: list[_DrugItem]


class DrugOpenRouterEngine(OpenRouterEngine):
    engine_name = "openrouter-drug"
    prompt = PROMPT
    prompt_version = "d1"
    output_model = _DrugReading


# 鹽類字尾：目錄只收有效成分（「LOSARTAN POTASSIUM」→ losartan）。
# 先比原名再比去掉鹽類的名稱，「Calcium carbonate」這類本身就是成分的名稱不會被拆壞
# 只去掉名稱結尾的鹽類字（「Calcium Atorvastatin」開頭的 calcium 不動）
_SALTS = re.compile(
    r"(?:\s+(?:potassium|k|sodium|na|hcl|hydrochloride|besylate|besilate|maleate|"
    r"tartrate|tar|mesylate|succinate|fumarate|calcium|ca)\.?)+$"
)


def _clean(name: str) -> str:
    s = re.sub(r"\(.*?\)|（.*?）", " ", unicodedata.normalize("NFKC", name).lower())
    return re.sub(r"\s+", " ", s).strip(" .")


def _variants(name: str) -> list[str]:
    plain = _clean(name)
    stripped = _SALTS.sub("", plain).strip(" .")
    return [v for v in dict.fromkeys([plain, stripped]) if v]


def map_item(raw_name: str, brand: str | None, generics: list[str], drug_items: list[DrugItem]) -> str | None:
    """依序用商品名、複方合寫、單一學名、原文對照目錄，回傳第一個命中的有效成分代碼。

    圖上寫了多個學名（複方）時，只接受成分數相同的複方品項：不拆開比單一成分，
    商品名或原文對到單方也不算，免得複方被當成其中一個單方。
    """
    by_code = {i.active_ingredient_code: i for i in drug_items}
    variants = [v for v in (_variants(g) for g in generics) if v]
    if len(variants) > 1:
        combo = [" + ".join(v[0] for v in variants), " + ".join(v[-1] for v in variants)]
    else:
        combo = variants[0] if variants else []
    for name in [brand or "", *combo, raw_name]:
        if name.strip():
            mapped = map_drug_name(name, drug_items)
            if mapped.scope_status is not ScopeStatus.IN_SCOPE:
                continue
            parts = len(by_code[mapped.active_ingredient_code].english_name.split("+"))
            if len(variants) <= 1 or parts == len(variants):
                return mapped.active_ingredient_code
    return None


def parse(recording: EngineRecording) -> _DrugReading:
    """錄製紀錄 → 模型讀出的藥品清單。不連網，測試與重新計算都用它。"""
    try:
        text = recording.response["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        raise ExtractionError(f"{recording.image_id} 的 OpenRouter 回應格式錯誤") from e
    try:
        return _DrugReading.model_validate_json(text or "")
    except (ValidationError, json.JSONDecodeError) as e:
        raise ExtractionError(f"{recording.image_id} 的藥包辨識結果不符合格式") from e


def _catalog_version(drug_items: list[DrugItem]) -> str:
    digest = hashlib.sha256(json.dumps([i.model_dump(mode="json") for i in drug_items], ensure_ascii=False).encode())
    return f"drug-items-{digest.hexdigest()[:12]}"


def extract_drugs(
    draft_id: UUID,
    images: list[ImageInput],
    quality: list[SourceImage],
    engine: DrugOpenRouterEngine,
    drug_items: list[DrugItem],
) -> DrugDraft:
    """同步呼叫。只處理 quality_status = accepted 的圖；任何辨識失敗都轉成 ExtractionError。"""
    by_id = {img.image_id: img for img in images}
    if [s.image_id for s in quality] != [img.image_id for img in images]:
        raise ExtractionError("品質檢查結果與照片對不上（照片編號或順序不同）")
    accepted = [by_id[s.image_id] for s in quality if s.quality_status is QualityStatus.ACCEPTED]
    if not accepted:
        raise ExtractionError("沒有通過品質檢查的照片")
    with ThreadPoolExecutor(max_workers=len(accepted)) as pool:
        recordings = list(pool.map(engine.record, accepted))
    return build_draft(draft_id, quality, recordings, drug_items)


def build_draft(
    draft_id: UUID, quality: list[SourceImage], recordings: list[EngineRecording], drug_items: list[DrugItem]
) -> DrugDraft:
    rows: list[DrugDraftRow] = []
    for rec in recordings:
        for item in parse(rec).items:
            code = map_item(item.raw_name, item.brand_name, item.generic_names, drug_items)
            rows.append(
                DrugDraftRow(
                    row_id=f"d{len(rows) + 1:02d}",
                    raw_name=item.raw_name,
                    generic_name_raw=" + ".join(item.generic_names) or None,
                    source_image_id=rec.image_id,
                    bbox=_to_bbox(item.box_2d, rec.image_width, rec.image_height),
                    active_ingredient_code=code,
                    scope_status=ScopeStatus.IN_SCOPE if code else ScopeStatus.UNRESOLVED,
                )
            )
    first = recordings[0]
    model = first.response.get("model") or first.request["model"]
    return DrugDraft(
        draft_id=draft_id,
        source_images=quality,
        rows=rows,
        extraction_meta=ExtractionMeta(
            ocr_version=f"{first.engine}/{model}/{first.request['provider']}/prompt-{first.request['prompt_version']}",
            rule_layer_version=MAPPING_VERSION,
            synonym_table_version=_catalog_version(drug_items),
            extracted_at=datetime.now(timezone.utc),
        ),
    )
