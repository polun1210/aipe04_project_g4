"""藥包辨識 → DrugDraft。處方籤 26 張（公開範例）用錄製的 Gemini 3.8 Flash 結果重播，不連網。"""

import json
from pathlib import Path
from uuid import UUID

import pytest

from app.catalog_source import get_catalog_source
from app.extraction import ExtractionError, ImageInput
from app.extraction.drugs import DrugOpenRouterEngine, build_draft, extract_drugs, map_item
from app.extraction.engines.base import EngineRecording
from app.extraction.engines.openrouter import Route
from app.schemas.enums import QualityStatus, ScopeStatus
from app.schemas.label import SourceImage

RECORDED = Path(__file__).parents[1] / "fixtures" / "engine_responses" / "openrouter-drug"
DRAFT_ID = UUID("d1000000-0000-4000-8000-000000000009")
ITEMS = get_catalog_source().load().drug_items
# 26 張裡含目錄內藥品的 7 張；其他藥都不在目錄裡，應該是無法判定
IN_CATALOG = {
    "rx01": "atorvastatin", "rx02": "atorvastatin", "rx03": "atorvastatin", "rx04": "atorvastatin",
    "rx22": "atorvastatin", "rx05": "losartan_hydrochlorothiazide", "rx06": "losartan",
}  # fmt: skip


def _draft(image_id: str):
    rec = EngineRecording.model_validate_json((RECORDED / f"{image_id}.json").read_text(encoding="utf-8"))
    return build_draft(DRAFT_ID, [SourceImage(image_id=image_id, quality_status=QualityStatus.ACCEPTED)], [rec], ITEMS)


def test_處方籤26張都產出合法草稿且只有目錄內的藥對到成分():
    ids = sorted(p.stem for p in RECORDED.glob("rx*.json"))
    assert len(ids) == 26
    for image_id in ids:
        draft = _draft(image_id)
        assert draft.rows, image_id
        codes = {r.active_ingredient_code for r in draft.rows if r.scope_status is ScopeStatus.IN_SCOPE}
        assert codes == ({IN_CATALOG[image_id]} if image_id in IN_CATALOG else set()), image_id
        assert draft.extraction_meta.ocr_version.startswith("openrouter-drug/")


def test_位置框換算成原圖像素():
    row = _draft("rx22").rows[0]
    assert row.bbox is not None and row.bbox.width > 0


@pytest.mark.parametrize(
    ("brand", "generics", "expected"),
    [
        (None, ["LOSARTAN POTASSIUM"], "losartan"),  # 鹽類字尾去掉
        (None, ["Magnesium oxide"], "magnesium_oxide"),  # 本身就是成分的名稱不能被拆壞
        ("可悅您", [], "losartan"),  # 台灣商品名
        (None, ["Losartan", "Hydrochlorothiazide"], "losartan_hydrochlorothiazide"),  # 複方對到複方
    ],
)
def test_藥名對照(brand, generics, expected):
    assert map_item("原文", brand, generics, ITEMS) == expected


@pytest.mark.parametrize(
    "generics",
    [
        ["Losartan", "Amlodipine"],  # 複方不能被當成其中一個單方
        ["Losartanol"],  # 名稱只是包含目錄藥名，不算
        ["Atorvastatin Calcium Extra"],  # 去掉鹽類後仍不是完全相同的名稱
    ],
)
def test_不該對到目錄的名稱(generics):
    assert map_item("原文", None, generics, ITEMS) is None


def test_學名是複方時商品名或原文對到單方也不算():
    assert map_item("Losartan", "可悅您", ["Losartan", "Amlodipine"], ITEMS) is None


def test_名稱開頭的鹽類字不去掉():
    assert map_item("原文", None, ["Calcium Atorvastatin"], ITEMS) is None


def test_沒有通過品質檢查時回錯誤():
    engine = DrugOpenRouterEngine(lambda body, timeout: {}, Route("google/gemini-3.8-flash", "google-ai-studio"))
    with pytest.raises(ExtractionError, match="品質檢查"):
        extract_drugs(
            DRAFT_ID,
            [ImageInput(image_id="a", content=b"x")],
            [SourceImage(image_id="a", quality_status=QualityStatus.REJECTED, reject_reason="blur")],
            engine,
            ITEMS,
        )


def test_模型回傳不符格式時回錯誤而不是空草稿(make_jpeg):
    reply = {"model": "m", "choices": [{"message": {"content": json.dumps({"rows": []})}}]}
    engine = DrugOpenRouterEngine(lambda body, timeout: reply, Route("google/gemini-3.8-flash", "google-ai-studio"))
    with pytest.raises(ExtractionError, match="不符合格式"):
        extract_drugs(
            DRAFT_ID,
            [ImageInput(image_id="a", content=make_jpeg(100, 100))],
            [SourceImage(image_id="a", quality_status=QualityStatus.ACCEPTED)],
            engine,
            ITEMS,
        )
