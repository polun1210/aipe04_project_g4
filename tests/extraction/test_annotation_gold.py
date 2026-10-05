"""標準答案轉換：從對外入口 adjudicate、suggest、build_gold 測。"""

from pathlib import Path

import pytest

from app.schemas.enums import DoseUnit, LabelSection, ScopeStatus, Unit
from scripts.annotate.gold import GoldError, _synonyms, adjudicate, build_gold, draft_name_map, suggest
from scripts.annotate.schema import AnnotatedRow, AnnotatedServing, Annotation

CATALOG = Path(__file__).parents[2] / "docs" / "schemas" / "examples" / "catalog" / "ingredients.csv"
NT, PU, IL = LabelSection.NUTRITION_TABLE, LabelSection.PER_UNIT_NOTE, LabelSection.INGREDIENT_LIST


def row(name, amount=None, unit=None, section=NT, pdv=None) -> AnnotatedRow:
    return AnnotatedRow(
        raw_name=name, per_serving=amount, unit=unit, percent_dv=pdv, stated_elemental_amount=None, label_section=section
    )


def ann(*rows, serving=(1, DoseUnit.TABLET)) -> Annotation:
    return Annotation(serving=AnnotatedServing(serving_size=serving[0], dose_unit=serving[1]), rows=list(rows))


A = ann(row("維生素D", 10, Unit.UG), row("鈣", 200, Unit.MG), row("紅麴粉", section=IL), row("每一份量", section=IL))
B = ann(row("維生素D", 12, Unit.UG), row("鈣", 200, Unit.MG), row("紅麴粉", section=IL))
DIS = [
    {"image_id": "p01-img01", "row": "維生素D", "field": "per_serving", "adjudicated": "10"},
    {"image_id": "p01-img01", "row": "每一份量", "field": "row", "adjudicated": "刪除"},
]


def test_裁決套用不一致的結果並刪除多抓的列():
    gold = adjudicate({"p01-img01": A}, {"p01-img01": B}, DIS, [], [])["p01-img01"]
    assert [r.raw_name for r in gold.rows] == ["維生素D", "鈣", "紅麴粉"]
    assert gold.rows[0].per_serving == 10


def test_還有不一致沒裁決時報錯():
    undecided = [{**DIS[0], "adjudicated": ""}, DIS[1]]
    with pytest.raises(GoldError, match="沒有裁決"):
        adjudicate({"p01-img01": A}, {"p01-img01": B}, undecided, [], [])


def test_抽查判錯卻沒有更正值時報錯_有更正就套用():
    spot = [{"image_id": "p01-img01", "row": "每一份量", "field": "dose_unit", "verdict": "錯"}]
    with pytest.raises(GoldError, match="corrections"):
        adjudicate({"p01-img01": A}, {"p01-img01": B}, DIS, spot, [])
    fix = [{"image_id": "p01-img01", "row": "每一份量", "field": "dose_unit", "value": "null"}]
    gold = adjudicate({"p01-img01": A}, {"p01-img01": B}, DIS, spot, fix)["p01-img01"]
    assert gold.serving.dose_unit is None


@pytest.fixture(scope="module")
def synonyms():
    return _synonyms(CATALOG)


def test_營養標示表的營養素建議範圍內(synonyms):
    s = suggest("維生素B12 Vitamin B12", NT, synonyms, set())
    assert (s.scope, s.code) == (ScopeStatus.IN_SCOPE, "vitamin_b12")


def test_成分欄的營養素化合物建議範圍外(synonyms):
    s = suggest("鹽酸吡哆辛(維生素B6)", IL, synonyms, set())
    assert s.scope is ScopeStatus.OUT_OF_SCOPE and s.code is None


def test_允許成分在成分欄也是範圍內(synonyms):
    s = suggest("葡萄糖胺鹽酸鹽", IL, synonyms, set())
    assert (s.scope, s.code, s.form) == (ScopeStatus.IN_SCOPE, "glucosamine", "glucosamine_hcl")


def test_營養標示表已有的營養素其化合物含量列待確認且建議範圍外(synonyms):
    s = suggest("天然海藻鈣(含32%鈣)", PU, synonyms, {"calcium"})
    assert (s.group, s.scope) == ("check", ScopeStatus.OUT_OF_SCOPE)


def test_產生的標準答案通過辨識草稿結構驗證():
    gold = adjudicate({"p01-img01": A}, {"p01-img01": B}, DIS, [], [])
    name_map = draft_name_map(gold, CATALOG)
    sources = [{"image_id": "p01-img01", "product_id": "p01", "product_name": "測試錠"}]
    draft = build_gold(gold, name_map, sources)["p01"]
    assert [(n.raw_name, n.standard_code) for n in draft.nutrients] == [
        ("維生素D", "vitamin_d"), ("鈣", "calcium"), ("紅麴粉", "red_yeast_rice"),
    ]  # fmt: skip
    assert draft.serving_info.serving_size == 1


def test_名稱對照表缺列時報錯():
    gold = adjudicate({"p01-img01": A}, {"p01-img01": B}, DIS, [], [])
    with pytest.raises(GoldError, match="名稱對照表"):
        build_gold(gold, [], [{"image_id": "p01-img01", "product_id": "p01", "product_name": ""}])
