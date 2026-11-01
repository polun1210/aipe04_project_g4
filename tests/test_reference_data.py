"""data/catalog/ 參考資料的完整性檢查（做法照 nutrition-agent 的 reference/checks.py）。

資料壞掉時這裡會紅：引文不是原文的逐字片段、代碼對不上、DRIs 缺格、化合物比率算錯。
"""

import re
import unicodedata
from collections import Counter
from functools import cache
from pathlib import Path

import pytest

from app.catalog_source import CATALOG_DIR, CsvCatalogSource
from app.schemas.enums import (
    ALLOWED_INGREDIENTS,
    TARGET_NUTRIENTS,
    AgeBand,
    DrugClassCode,
    IngredientCode,
    RuleStatus,
    Sex,
)
from app.schemas.reference import ReferenceData

SOURCES_DIR = CATALOG_DIR.parent / "sources"
RATIO_TOLERANCE = 0.0001
ATOMIC_WEIGHT = {"H": 1.008, "C": 12.011, "N": 14.007, "O": 15.999, "Mg": 24.305, "P": 30.974, "S": 32.06,
                 "Ca": 40.078, "Fe": 55.845}  # fmt: skip
ELEMENT_OF = {"calcium": "Ca", "magnesium": "Mg", "iron": "Fe"}
G4_COMPOUND_ITEMS = {"losartan_hydrochlorothiazide"}  # g4 範例自加；藥名表以兩個單方成分表示複方
NEW_DRAFT_RULE_IDS = {"glucosamine-rx-duplicate"}


@pytest.fixture(scope="module")
def ref() -> ReferenceData:
    return CsvCatalogSource().load_reference()


@cache
def _normalized_text(path: Path) -> str:
    """NFKC 並去掉所有空白，跟 nutrition-agent 的引文核對方式一樣。"""
    return "".join(unicodedata.normalize("NFKC", path.read_text(encoding="utf-8")).split())


def _normalize(text: str) -> str:
    return "".join(unicodedata.normalize("NFKC", text).split())


# ─── 出處 ───────────────────────────────────────────────────


def test_每段引文都逐字出現在_data_sources_的原文檔(ref):
    for cit in ref.citations:
        assert cit.document_path, f"{cit.citation_id} 沒有 document_path"
        path = SOURCES_DIR / cit.document_path
        assert path.is_file(), f"{cit.citation_id} 找不到原文檔 {cit.document_path}"
        assert _normalize(cit.quote) in _normalized_text(path), f"{cit.citation_id} 不在 {cit.document_path}"


def test_引文只用_NIH_ODS_專業版與_NCCIH(ref):
    for cit in ref.citations:
        assert cit.document_path
        assert "consumer" not in cit.document_path.casefold(), cit.citation_id
        if cit.source.value == "nih_ods":
            assert cit.document_path.endswith("-HealthProfessional.md"), cit.citation_id


def test_每條規則的引文編號都查得到且沒有重複的編號(ref):
    cited = {c.citation_id for c in ref.citations}
    assert len(cited) == len(ref.citations)
    assert len({r.rule_id for r in ref.rules}) == len(ref.rules)
    for rule in ref.rules:
        assert set(rule.citation_ids) <= cited, rule.rule_id
    assert cited == {cid for r in ref.rules for cid in r.citation_ids}, "有引文沒有任何規則使用"


def test_內容相同的引文共用同一個編號(ref):
    keys = Counter((c.document_path, _normalize(c.quote)) for c in ref.citations)
    assert max(keys.values()) == 1


def test_審定規則的建表者與覆核者不同且新增的只剩一條草稿(ref):
    by_status = Counter(r.status for r in ref.rules)
    assert by_status[RuleStatus.REVIEWED] >= 1
    drafts = {r.rule_id for r in ref.rules if r.status is RuleStatus.DRAFT}
    assert drafts == NEW_DRAFT_RULE_IDS
    for rule in ref.rules:
        if rule.status is RuleStatus.REVIEWED:
            assert rule.reviewed_by and rule.reviewed_by != rule.curated_by, rule.rule_id


# ─── 代碼對得到 ─────────────────────────────────────────────


def test_規則的條件與成分代碼都在目錄裡(ref):
    classes = {c.drug_class_code.value for c in ref.catalog.drug_classes}
    items = {i.active_ingredient_code for i in ref.catalog.drug_items}
    ingredients = {i.code for i in ref.catalog.ingredients}
    for rule in ref.rules:
        pool = classes if rule.condition_type.value == "drug_class" else items
        assert rule.condition_code in pool, rule.rule_id
        assert rule.ingredient_code in ingredients, rule.rule_id


def test_藥名表的有效成分代碼都在藥物目錄裡(ref):
    items = {i.active_ingredient_code for i in ref.catalog.drug_items}
    products = CsvCatalogSource().load_drug_products()
    assert len(products) > 30000
    assert len({(p.name, p.lang) for p in products}) == len(products)
    assert all(set(p.active_ingredient_codes) <= items for p in products)
    # 每個有效成分都至少有一個品名（g4 自加的複方項目除外），且 Ranitidine（已下架）不得對到範圍內
    used = {c for p in products for c in p.active_ingredient_codes}
    assert items - used <= G4_COMPOUND_ITEMS, items - used - G4_COMPOUND_ITEMS
    assert not any("ranitidine" in c for p in products for c in p.active_ingredient_codes)


def test_中英文品名都對得到有效成分(ref):
    products = CsvCatalogSource().load_drug_products()
    by_name = {(p.name, p.lang): p for p in products}
    assert by_name[('"U-Liang" Eutomin Tablets 1000mg', "en")].active_ingredient_codes == ["metformin"]
    assert by_name[('"井田"美康寧錠500毫克（二甲二脈）', "zh")].active_ingredient_codes == ["metformin"]


# ─── 範圍齊全 ───────────────────────────────────────────────


def test_十六類用藥與十六個成分齊全(ref):
    assert {c.drug_class_code for c in ref.catalog.drug_classes} == set(DrugClassCode)
    assert {i.code for i in ref.catalog.ingredients} == set(IngredientCode)
    assert len(TARGET_NUTRIENTS) == 13 and len(ALLOWED_INGREDIENTS) == 3
    for item in ref.catalog.drug_items:
        assert item.drug_class_codes, item.active_ingredient_code
    for cls in ref.catalog.drug_classes:
        assert any(cls.drug_class_code in i.drug_class_codes for i in ref.catalog.drug_items), cls.drug_class_code


def test_每個目標營養素乘兩性別乘四年齡層都有_DRIs(ref):
    have = {(d.nutrient_code, d.sex, d.age_band) for d in ref.dris_values}
    want = {(n, s, a) for n in TARGET_NUTRIENTS for s in Sex for a in AgeBand}
    assert have == want
    assert len(ref.dris_values) == len(want)


def test_鉀與維生素B12沒有上限其餘都有(ref):
    no_ul = {d.nutrient_code for d in ref.dris_values if d.ul_value is None}
    assert no_ul == {IngredientCode.POTASSIUM, IngredientCode.VITAMIN_B12}
    scoped = {i.code for i in ref.catalog.ingredients if i.ul_scope is not None}
    assert scoped == TARGET_NUTRIENTS - no_ul


def test_制酸劑劑量選項指向有需要劑量的藥(ref):
    items = {i.active_ingredient_code: i for i in ref.catalog.drug_items}
    for dose in ref.catalog.drug_nutrient_doses:
        assert items[dose.active_ingredient_code].requires_dose


# ─── 化合物比率 ─────────────────────────────────────────────


def _molar_mass(formula: str) -> tuple[float, dict[str, float]]:
    """化學式（含括號與 ·nH2O 結晶水）→ (分子量, 各元素質量)。"""
    total: dict[str, float] = {}
    for part in formula.split("·"):
        coef = re.match(r"\d+", part)
        multiplier = int(coef.group()) if coef else 1
        for element, mass in _parse(part[coef.end() if coef else 0 :]).items():
            total[element] = total.get(element, 0.0) + mass * multiplier
    return sum(total.values()), total


def _parse(text: str) -> dict[str, float]:
    stack: list[dict[str, float]] = [{}]
    i = 0
    while i < len(text):
        if text[i] == "(":
            stack.append({})
            i += 1
        elif text[i] == ")":
            i += 1
            n = re.match(r"\d+", text[i:])
            count = int(n.group()) if n else 1
            i += len(n.group()) if n else 0
            inner = stack.pop()
            for el, mass in inner.items():
                stack[-1][el] = stack[-1].get(el, 0.0) + mass * count
        else:
            m = re.match(r"([A-Z][a-z]?)(\d*)", text[i:])
            assert m, f"化學式讀不懂：{text}"
            el, num = m.group(1), int(m.group(2) or 1)
            stack[-1][el] = stack[-1].get(el, 0.0) + ATOMIC_WEIGHT[el] * num
            i += len(m.group())
    return stack[0]


def test_化合物比率依化學式重算與資料一致(ref):
    assert ref.compounds
    for c in ref.compounds:
        assert c.formula, c.compound_code
        molar, by_element = _molar_mass(c.formula)
        expected = by_element[ELEMENT_OF[c.nutrient_code.value]] / molar
        assert abs(expected - c.ratio) <= RATIO_TOLERANCE, f"{c.compound_code}：算出 {expected:.4f}、資料 {c.ratio}"


def test_制酸劑元素量與氧化鎂比率一致(ref):
    ratio = next(c.ratio for c in ref.compounds if c.compound_code == "magnesium_oxide")
    for dose in ref.catalog.drug_nutrient_doses:
        if dose.active_ingredient_code == "magnesium_oxide":
            assert abs(dose.dose_option_mg * ratio - dose.elemental_mg_per_unit) <= 0.1


# ─── 版本 ───────────────────────────────────────────────────


def test_版本檔與讀回的版本一致(ref):
    assert ref.version == (CATALOG_DIR / "VERSION").read_text(encoding="utf-8").strip()
    assert re.fullmatch(r"\d{4}\.\d+\.\d+", ref.version)


def test_同一個藥與營養素的劑量只能有一列(ref):
    # 計算層會把每一列都按劑量比例加進去，兩列就變兩倍（app/assessing.py _drug_intakes）
    row = ref.catalog.drug_nutrient_doses[0]
    doubled = row.model_copy(update={"dose_option_mg": row.dose_option_mg * 2})
    data = ref.catalog.model_dump() | {"drug_nutrient_doses": [row.model_dump(), doubled.model_dump()]}
    with pytest.raises(ValueError, match="不只一列"):
        type(ref.catalog).model_validate(data)
