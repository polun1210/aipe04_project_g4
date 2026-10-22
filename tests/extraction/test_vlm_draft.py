"""VLM 結果 → 辨識草稿（E 工單 #22）。只透過 extract() 測外部行為。

比較集用錄製的 OpenRouter（Gemini 3.8 Flash）結果重播，不花錢；比較集沒有的寫法，用手寫的 EngineResult 重播。
"""

import json
from pathlib import Path
from uuid import UUID

import pytest

from app.extraction import EngineResult, ImageInput, ReplayEngine, extract
from app.extraction.engines.base import LabelReading, ReadingRow, ServingReading
from app.extraction.engines.openrouter import OpenRouterEngine, Route
from app.schemas.enums import DoseUnit, LabelSection, QualityStatus, ScopeStatus, Unit
from app.schemas.label import ExtractionDraft, SourceImage

RECORDED = Path(__file__).resolve().parents[1] / "fixtures" / "engine_responses" / "openrouter"
PRODUCT = UUID("c4000000-0000-4000-8000-000000000001")
COMPARISON_SET = sorted(p.stem for p in RECORDED.glob("p*-img01.json"))


def _replay(image_id: str, folder: Path = RECORDED) -> ExtractionDraft:
    return extract(
        PRODUCT,
        [ImageInput(image_id=image_id, content=b"replay")],
        [SourceImage(image_id=image_id, quality_status=QualityStatus.ACCEPTED)],
        engine=ReplayEngine(folder),
    )


def _crafted(tmp_path, rows: list[ReadingRow], serving: ServingReading | None = None, intake: str | None = None):
    result = EngineResult(
        image_id="t01-img01",
        engine_version="openrouter/test/test/prompt-g1",
        blocks=[],
        reading=LabelReading(serving=serving, rows=rows, suggested_intake_raw=intake),
    )
    (tmp_path / "t01-img01.json").write_text(result.model_dump_json(), encoding="utf-8")
    return _replay("t01-img01", tmp_path)


def _row(name, amount=None, unit=None, section=LabelSection.NUTRITION_TABLE, dv=None) -> ReadingRow:
    return ReadingRow(raw_text=name, raw_name=name, amount=amount, unit_raw=unit, percent_dv=dv, label_section=section)


def _by_name(draft: ExtractionDraft, name: str):
    return next(n for n in draft.nutrients if n.raw_name == name)


# ─── 比較集（錄製的 Gemini 3.8 Flash 結果）──────────────────────


def test_比較集有10張錄製結果():
    assert len(COMPARISON_SET) == 10


@pytest.mark.parametrize("image_id", COMPARISON_SET)
def test_比較集每張都產出合法草稿並記錄三個版本(image_id):
    draft = _replay(image_id)
    ExtractionDraft.model_validate(draft.model_dump())
    meta = draft.extraction_meta
    assert meta.ocr_version == "openrouter/google/gemini-3.8-flash/google-ai-studio/prompt-g1"
    assert meta.rule_layer_version == "vlm-r1" and meta.synonym_table_version.startswith("syn-")


def test_每日參考值百分比不會填進每份含量():
    b12 = _by_name(_replay("p01-img01"), "維生素B12")
    assert (b12.per_serving, b12.unit, b12.percent_dv) == (9, Unit.UG, 375)


def test_單位原文帶括號的國際單位時仍對映到主單位():
    vitamin_e = _by_name(_replay("p01-img01"), "維生素E")
    assert (vitamin_e.standard_code, vitamin_e.unit) == ("vitamin_e", Unit.MG_ATE)


def test_每一份量只寫重量時留空():
    serving = _replay("p07-img01").serving_info
    assert (serving.serving_size, serving.dose_unit) == (None, None)


def test_錠對映成錠劑而粒無法判定劑型時留空():
    assert _replay("p01-img01").serving_info.dose_unit is DoseUnit.TABLET
    p10 = _replay("p10-img01").serving_info
    assert (p10.serving_size, p10.dose_unit) == (1, None)


def test_魚油的EPA與DHA以型態代碼區分():
    forms = {n.nutrient_form_code for n in _replay("p02-img01").nutrients if n.standard_code == "omega_3"}
    assert {"epa", "dha", "n3_total"} <= forms


def test_成分欄裡目標營養素的化合物算範圍外():
    citrate = next(
        n for n in _replay("p01-img01").nutrients if n.raw_name == "檸檬酸鈣" and n.label_section is LabelSection.INGREDIENT_LIST
    )
    assert (citrate.scope_status, citrate.standard_code) == (ScopeStatus.OUT_OF_SCOPE, None)


def test_標示的建議吃法有寫次數才填():
    intake = _replay("p08-img01").label_suggested_intake
    assert intake is not None
    assert (intake.times_per_day, intake.amount_per_time) == (1, 2)


def test_標示寫含量範圍時取第一個數字並要使用者確認():
    """p08 標示寫「Monacolin K 含量為 11±2.0 毫克」：轉接器取 11 並標記，草稿上要使用者確認。"""
    monacolin = _by_name(_replay("p08-img01"), "HMG-COA還原酵素抑制劑 Monacolin K")
    assert (monacolin.standard_code, monacolin.nutrient_form_code) == ("red_yeast_rice", "monacolin_k")
    assert (monacolin.per_serving, monacolin.unit, monacolin.requires_user_input) == (11, Unit.MG, True)


def test_目錄有的寫法才認得_沒有的照完全比對原則不認(tmp_path):
    """名稱標準化只做完全比對：「紅麴粉末」在目錄同義詞裡就認得，目錄沒有的寫法不在規則層猜。"""
    red = _by_name(_replay("p08-img01"), "紅麴粉末")
    assert (red.scope_status, red.standard_code) == (ScopeStatus.IN_SCOPE, "red_yeast_rice")
    other = _crafted(tmp_path, [_row("紅麴萃取粉", section=LabelSection.INGREDIENT_LIST)]).nutrients[0]
    assert (other.scope_status, other.standard_code) == (ScopeStatus.OUT_OF_SCOPE, None)


# ─── 比較集沒有的寫法 ────────────────────────────────────────


def test_允許成分可以從成分欄擷取(tmp_path):
    red = _crafted(tmp_path, [_row("紅麴", section=LabelSection.INGREDIENT_LIST)]).nutrients[0]
    assert (red.scope_status, red.standard_code, red.label_section) == (
        ScopeStatus.IN_SCOPE,
        "red_yeast_rice",
        LabelSection.INGREDIENT_LIST,
    )


def test_元素量的三種寫法(tmp_path):
    draft = _crafted(
        tmp_path,
        [
            _row("檸檬酸鈣(含純鈣50mg)", 238, "毫克"),
            _row("鈣(碳酸鈣)", 200, "毫克"),
            _row("檸檬酸鈣", 2000, "毫克"),
        ],
    )
    got = [(n.standard_code, n.nutrient_form_code, n.per_serving, n.stated_elemental_amount) for n in draft.nutrients]
    assert got == [
        ("calcium", "calcium_citrate", 238, 50),
        ("calcium", "calcium_carbonate", 200, 200),
        ("calcium", "calcium_citrate", 2000, None),
    ]


def test_國際單位保留原單位不換算(tmp_path):
    vitamin_d = _crafted(tmp_path, [_row("維生素D", 400, "IU")]).nutrients[0]
    assert (vitamin_d.per_serving, vitamin_d.unit) == (400, Unit.IU)


def test_營養標示裡不認得的名稱標為無法確認並要使用者確認(tmp_path):
    row = _crafted(tmp_path, [_row("神秘萃取物", 50, "毫克")]).nutrients[0]
    assert (row.scope_status, row.requires_user_input) == (ScopeStatus.UNRESOLVED, True)


def test_範圍內成分的單位認不得時留空並要使用者確認(tmp_path):
    row = _crafted(tmp_path, [_row("鈣", 300, "CFU")]).nutrients[0]
    assert (row.scope_status, row.unit, row.requires_user_input) == (ScopeStatus.IN_SCOPE, None, True)


def test_公司資訊與註腳不會變成成分列(tmp_path):
    draft = _crafted(tmp_path, [_row("鈣", 300, "毫克"), _row("消費者服務專線：0800-000-000"), _row("*參考值未訂定")])
    assert [n.raw_name for n in draft.nutrients] == ["鈣"]


def test_營養標示已有該營養素時其他區塊的含量列算範圍外(tmp_path):
    draft = _crafted(
        tmp_path,
        [_row("鈣", 425, "毫克"), _row("天然海藻鈣(含32%鈣)", 1330, "毫克", section=LabelSection.PER_UNIT_NOTE)],
    )
    assert _by_name(draft, "天然海藻鈣(含32%鈣)").scope_status is ScopeStatus.OUT_OF_SCOPE


def test_型態不明的菸鹼素照樣是範圍內且單位對映成菸鹼素當量(tmp_path):
    niacin = _crafted(tmp_path, [_row("菸鹼素", 25.5, "毫克NE")]).nutrients[0]
    assert (niacin.standard_code, niacin.unit, niacin.nutrient_form_code) == ("niacin", Unit.MG_NE, None)


def test_同一營養素在營養標示與每粒說明都出現時只算營養標示那一列(tmp_path):
    draft = _crafted(tmp_path, [_row("鈣", 600, "毫克"), _row("鈣", 200, "毫克", section=LabelSection.PER_UNIT_NOTE)])
    assert [n.scope_status for n in draft.nutrients] == [ScopeStatus.IN_SCOPE, ScopeStatus.OUT_OF_SCOPE]


def test_成分欄裡目標營養素的原料仍是範圍外(tmp_path):
    """範圍判定表：成分欄的檸檬酸鈣、氯化鉀、硬脂酸鎂 → 範圍外，營養素由營養標示表那列代表。"""
    section = LabelSection.INGREDIENT_LIST
    draft = _crafted(tmp_path, [_row("鈣", 300, "毫克"), *(_row(n, section=section) for n in ["檸檬酸鈣", "氯化鉀", "硬脂酸鎂"])])
    assert [n.scope_status for n in draft.nutrients] == [ScopeStatus.IN_SCOPE] + [ScopeStatus.OUT_OF_SCOPE] * 3
    assert all(n.standard_code is None for n in draft.nutrients[1:])


# ─── 型態代碼（supplement-label-output.md「型態代碼」）────────────


def _forms(draft: ExtractionDraft) -> list[tuple]:
    return [(n.raw_name, n.scope_status, n.standard_code, n.nutrient_form_code) for n in draft.nutrients]


def test_標示寫omega3脂肪酸總量時型態為n3_total而魚油總量為fish_oil(tmp_path):
    names = ["魚油", "魚油(含EPA 18%、DHA 12%)", "Omega-3脂肪酸總量", "ω-3 脂肪酸", "n-3多元不飽和脂肪酸", "EPA", "DHA"]
    draft = _crafted(tmp_path, [_row(n, 100, "毫克") for n in names])
    assert [(n.standard_code, n.nutrient_form_code) for n in draft.nutrients] == [
        ("omega_3", "fish_oil"),
        ("omega_3", "fish_oil"),  # 括號裡的 EPA、DHA 只是說明，這一列是魚油總量
        ("omega_3", "n3_total"),
        ("omega_3", "n3_total"),
        ("omega_3", "n3_total"),
        ("omega_3", "epa"),
        ("omega_3", "dha"),
    ]
    assert all(n.scope_status is ScopeStatus.IN_SCOPE for n in draft.nutrients)


def test_紅麴的MonacolinK含量列型態為monacolin_k而只寫紅麴不填型態(tmp_path):
    draft = _crafted(
        tmp_path,
        [
            _row("紅麴", section=LabelSection.INGREDIENT_LIST),
            _row("Monacolin K", 2.4, "毫克", section=LabelSection.PER_UNIT_NOTE),
            _row("莫納可林K", 2.4, "mg", section=LabelSection.PER_UNIT_NOTE),
        ],
    )
    assert _forms(draft) == [
        ("紅麴", ScopeStatus.IN_SCOPE, "red_yeast_rice", None),
        ("Monacolin K", ScopeStatus.IN_SCOPE, "red_yeast_rice", "monacolin_k"),
        ("莫納可林K", ScopeStatus.IN_SCOPE, "red_yeast_rice", "monacolin_k"),
    ]


def test_葡萄糖胺寫明鹽酸鹽才填glucosamine_hcl(tmp_path):
    section = LabelSection.INGREDIENT_LIST
    names = ["葡萄糖胺鹽酸鹽", "鹽酸葡萄糖胺", "Glucosamine HCl", "葡萄糖胺(鹽酸鹽)", "葡萄糖胺", "葡萄糖胺硫酸鹽"]
    draft = _crafted(tmp_path, [_row(n, section=section) for n in names])
    assert _forms(draft) == [
        ("葡萄糖胺鹽酸鹽", ScopeStatus.IN_SCOPE, "glucosamine", "glucosamine_hcl"),
        ("鹽酸葡萄糖胺", ScopeStatus.IN_SCOPE, "glucosamine", "glucosamine_hcl"),
        ("Glucosamine HCl", ScopeStatus.IN_SCOPE, "glucosamine", "glucosamine_hcl"),
        ("葡萄糖胺(鹽酸鹽)", ScopeStatus.IN_SCOPE, "glucosamine", "glucosamine_hcl"),
        ("葡萄糖胺", ScopeStatus.IN_SCOPE, "glucosamine", None),
        ("葡萄糖胺硫酸鹽", ScopeStatus.IN_SCOPE, "glucosamine", None),  # spec 只有鹽酸鹽的型態代碼
    ]


def test_允許成分括號寫化合物時不當成元素量(tmp_path):
    row = _crafted(tmp_path, [_row("葡萄糖胺(葡萄糖胺鹽酸鹽)", 1500, "毫克", section=LabelSection.PER_UNIT_NOTE)]).nutrients[0]
    assert (row.standard_code, row.nutrient_form_code, row.stated_elemental_amount) == ("glucosamine", "glucosamine_hcl", None)


# ─── 轉接器的數值容錯（needs_review）─────────────────────────────


def test_轉接器容錯過的列要使用者確認而其他列不受影響(tmp_path):
    rows = [_row("鈣", 200, "毫克"), _row("鎂", 11, "毫克").model_copy(update={"needs_review": True})]
    draft = _crafted(tmp_path, rows)
    assert _by_name(draft, "鈣").requires_user_input is False
    magnesium = _by_name(draft, "鎂")
    assert (magnesium.per_serving, magnesium.requires_user_input) == (11, True)


def test_範圍外的列容錯過也標成要使用者確認(tmp_path):
    row = _crafted(tmp_path, [_row("熱量", 5, "大卡").model_copy(update={"needs_review": True})]).nutrients[0]
    assert (row.scope_status, row.requires_user_input) == (ScopeStatus.OUT_OF_SCOPE, True)


def test_每一份量容錯過時留空讓使用者填(tmp_path):
    serving = ServingReading(raw_text="每一份量 2±1 錠", serving_size=2, dose_unit_raw="錠", needs_review=True)
    info = _crafted(tmp_path, [_row("鈣", 200, "毫克")], serving=serving).serving_info
    assert (info.serving_size, info.dose_unit, info.source_image_id) == (None, None, "t01-img01")


def test_每一份量沒有容錯時照常填入(tmp_path):
    serving = ServingReading(raw_text="每一份量 2 錠", serving_size=2, dose_unit_raw="錠")
    info = _crafted(tmp_path, [_row("鈣", 200, "毫克")], serving=serving).serving_info
    assert (info.serving_size, info.dose_unit) == (2, DoseUnit.TABLET)


def _multi(tmp_path, servings: list[ServingReading | None]) -> ExtractionDraft:
    ids = [f"a-img{i + 1:02d}" for i in range(len(servings))]
    for image_id, serving in zip(ids, servings):
        result = EngineResult(
            image_id=image_id,
            engine_version="openrouter/test/test/prompt-g1",
            blocks=[],
            reading=LabelReading(serving=serving, rows=[_row("鈣", 200, "毫克")]),
        )
        (tmp_path / f"{image_id}.json").write_text(result.model_dump_json(), encoding="utf-8")
    return extract(
        PRODUCT,
        [ImageInput(image_id=i, content=b"replay") for i in ids],
        [SourceImage(image_id=i, quality_status=QualityStatus.ACCEPTED) for i in ids],
        engine=ReplayEngine(tmp_path),
    )


def test_多張照片時優先採用沒有容錯的每一份量(tmp_path):
    shaky = ServingReading(raw_text="2±1 錠", serving_size=2, dose_unit_raw="錠", needs_review=True)
    clear = ServingReading(raw_text="每一份量 3 錠", serving_size=3, dose_unit_raw="錠")
    draft = _multi(tmp_path, [shaky, clear])
    assert (draft.serving_info.serving_size, draft.serving_info.source_image_id) == (3, "a-img02")


def test_每一份量都容錯過時保留讀到的那張照片讓使用者定位(tmp_path):
    shaky = ServingReading(raw_text="2±1 錠", serving_size=2, dose_unit_raw="錠", needs_review=True)
    draft = _multi(tmp_path, [None, shaky])
    assert (draft.serving_info.serving_size, draft.serving_info.source_image_id) == (None, "a-img02")


def test_名稱中間的片段不算命中(tmp_path):
    row = _crafted(tmp_path, [_row("高效 鈣 配方", 200, "毫克")]).nutrients[0]
    assert (row.standard_code, row.scope_status) == (None, ScopeStatus.UNRESOLVED)


# ─── 轉接器 → extract() 一路接起來（假的連線，不需要金鑰）────────────


def _openrouter_draft(label: dict, make_jpeg) -> ExtractionDraft:
    content = json.dumps(label, ensure_ascii=False)
    reply = {"model": "google/gemini-3.8-flash", "choices": [{"message": {"content": content}, "finish_reason": "stop"}]}
    engine = OpenRouterEngine(lambda body, timeout: reply, Route("google/gemini-3.8-flash", "google-ai-studio"))
    image = ImageInput(image_id="img-01", content=make_jpeg(100, 200))
    return extract(PRODUCT, [image], [SourceImage(image_id="img-01", quality_status=QualityStatus.ACCEPTED)], engine=engine)


LABEL = {
    "serving": {"raw_text": "每一份量 2 錠", "serving_size": 2, "dose_unit": "錠", "box_2d": [100, 50, 140, 400]},
    "rows": [
        {"raw_text": "鈣 200毫克", "raw_name": "鈣", "amount": 200, "unit": "毫克", "percent_dv": None,
         "label_section": "nutrition_table", "box_2d": [200, 50, 240, 600]},
        {"raw_text": "鎂 11±2.0毫克", "raw_name": "鎂", "amount": "11±2.0", "unit": "毫克", "percent_dv": None,
         "label_section": "nutrition_table", "box_2d": [250, 50, 290, 600]},
    ],
    "suggested_intake": None,
    "headings": ["營養標示"],
}  # fmt: skip


def test_OpenRouter回傳的數值是文字時草稿上要使用者確認(make_jpeg):
    draft = _openrouter_draft(LABEL, make_jpeg)
    by_name = {n.raw_name: n for n in draft.nutrients}
    assert by_name["鈣"].requires_user_input is False
    assert (by_name["鎂"].per_serving, by_name["鎂"].requires_user_input) == (11, True)


def test_OpenRouter回傳的每一份量是文字時草稿留空但保留位置框(make_jpeg):
    label = {**LABEL, "serving": {**LABEL["serving"], "serving_size": "2~3"}}
    serving = _openrouter_draft(label, make_jpeg).serving_info
    assert (serving.serving_size, serving.dose_unit) == (None, None)
    assert serving.bbox is not None


# ─── 審查補充：整字比對、括號裡的單位、評估基準 ───────────────────────


@pytest.mark.parametrize("name", ["Liver repair complex", "Hepatica", "Adhatoda 萃取物"])
def test_英文字裡剛好有_epa_dha_不算魚油(tmp_path, name):
    row = _crafted(tmp_path, [_row(name, 100, "毫克")]).nutrients[0]
    assert (row.standard_code, row.nutrient_form_code) == (None, None)


def test_獨立的_EPA_仍算魚油(tmp_path):
    row = _crafted(tmp_path, [_row("EPA", 180, "毫克")]).nutrients[0]
    assert (row.standard_code, row.nutrient_form_code) == ("omega_3", "epa")


@pytest.mark.parametrize(("unit", "expected"), [("毫克(α-TE)", Unit.MG_ATE), ("mg(NE)", Unit.MG_NE), ("微克(800IU)", Unit.UG)])
def test_單位括號裡的_aTE_NE_要保留(tmp_path, unit, expected):
    row = _crafted(tmp_path, [_row("維生素E", 10, unit)]).nutrients[0]
    assert row.unit is expected


def test_比較集範圍內成分全部讀對():
    """評估基準守在 CI：標準答案（只有文字，不含照片）放在 tests/fixtures/gold_w1。"""
    from scripts.eval_drafts import evaluate

    t = evaluate()
    assert t["in_full"] == t["gold_in"] == 42 and t["missing"] == 0 and t["extra"] == 0
