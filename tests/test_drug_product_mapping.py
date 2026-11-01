"""TFDA 品名表接上藥名對照與候選搜尋（用 data/catalog 的真實快照）。"""

import pytest

from app.catalog_source import get_catalog_source
from app.drug_mapping import drug_product_index_of, find_candidates, map_confirmed_drug, map_drug_name
from app.schemas.drug_label import DrugDraftRow

SOURCE = get_catalog_source()
DRUG_ITEMS = SOURCE.load().drug_items
PRODUCTS = drug_product_index_of(SOURCE)


def _first_product(code: str) -> str:
    return next(p.name for p in SOURCE.load_drug_products() if p.active_ingredient_codes == [code])


def test_tfda_metformin_product_name_maps_in_scope():
    drug = map_drug_name(_first_product("metformin"), DRUG_ITEMS, products=PRODUCTS)
    assert drug.scope_status == "in_scope"
    assert drug.active_ingredient_code == "metformin"
    assert drug.drug_class_codes == ["biguanide"]


def test_product_name_ignores_width_case_and_spaces():
    name = "Candanxo F.C. Tablets 50/12.5 mg"
    drug = map_drug_name(f"  {name.upper()} ", DRUG_ITEMS, products=PRODUCTS)
    assert drug.scope_status == "in_scope"


def test_compound_product_uses_catalog_compound_item_and_union_of_classes():
    drug = map_drug_name("Candanxo F.C. Tablets 50/12.5 mg", DRUG_ITEMS, products=PRODUCTS)
    assert drug.active_ingredient_code == "losartan_hydrochlorothiazide"
    assert set(drug.drug_class_codes) == {"thiazide_diuretic", "acei_arb"}


def test_compound_without_catalog_item_prefers_ingredient_with_rule():
    caduet = next(p.name for p in SOURCE.load_drug_products() if p.name.lower().startswith("caduet"))
    drug = map_drug_name(caduet, DRUG_ITEMS, products=PRODUCTS)
    assert drug.active_ingredient_code == "atorvastatin"  # 不是 amlodipine：atorvastatin 有成分觸發規則


def test_compound_without_catalog_item_or_rule_takes_first():
    from app.drug_mapping import _representative

    items = [i for i in DRUG_ITEMS if i.active_ingredient_code in ("glucosamine_sulfate", "magnesium_oxide")]
    assert _representative(items, DRUG_ITEMS, frozenset()) is items[0]


def test_ranitidine_product_is_never_in_scope():
    ranitidine = next(
        p for p in SOURCE.load_drug_products() if any("ranitidine" in o.lower() for o in p.out_of_scope_ingredients)
    )
    drug = map_drug_name(ranitidine.name, DRUG_ITEMS, products=PRODUCTS)
    assert drug.scope_status == "out_of_scope"
    assert drug.active_ingredient_code is None


def test_name_in_neither_table_stays_unresolved():
    assert map_drug_name("完全亂打的藥", DRUG_ITEMS, products=PRODUCTS).scope_status == "unresolved"


def test_drug_item_hit_wins_over_product_table():
    drug = map_drug_name("立普妥", DRUG_ITEMS, products=PRODUCTS)
    assert drug.active_ingredient_code == "atorvastatin"


def test_without_product_index_behaviour_is_unchanged():
    assert map_drug_name(_first_product("metformin"), DRUG_ITEMS).scope_status == "unresolved"


def test_confirmed_drug_with_edited_name_uses_product_table():
    row = DrugDraftRow(
        row_id="r1", raw_name="亂打", source_image_id="img-01", active_ingredient_code=None, scope_status="unresolved"
    )
    name = _first_product("metformin")
    drug = map_confirmed_drug(name, row, DRUG_ITEMS, products=PRODUCTS)
    assert drug.active_ingredient_code == "metformin"


# ── find_candidates ─────────────────────────────────────────


def test_candidates_include_tfda_product_names():
    name = _first_product("metformin")
    [hit] = [c for c in find_candidates(name, DRUG_ITEMS, products=PRODUCTS)]
    assert hit.active_ingredient_code == "metformin"
    assert hit.matched_name == name


def test_class_filter_applies_before_the_limit():
    all_hits = find_candidates("a", DRUG_ITEMS, limit=200, products=PRODUCTS)
    target = all_hits[-1].drug_class_codes[0]
    expected = [c for c in all_hits if target in c.drug_class_codes]
    filtered = find_candidates("a", DRUG_ITEMS, limit=10, drug_class_code=target, products=PRODUCTS)
    assert filtered and all(target in c.drug_class_codes for c in filtered)
    assert [c.active_ingredient_code for c in filtered] == [c.active_ingredient_code for c in expected][:10]


def test_class_filter_keeps_compound_item_in_each_of_its_classes():
    for cls in ("acei_arb", "thiazide_diuretic"):
        codes = [
            c.active_ingredient_code
            for c in find_candidates("hyzaar", DRUG_ITEMS, drug_class_code=cls, products=PRODUCTS)
        ]
        assert "losartan_hydrochlorothiazide" in codes


def test_class_filter_with_no_member_returns_empty():
    assert find_candidates("立普妥", DRUG_ITEMS, drug_class_code="ppi", products=PRODUCTS) == []


@pytest.mark.parametrize("cls", ["ppi", "statin"])
def test_short_query_with_class_only_returns_that_class(cls):
    result = find_candidates("耐", DRUG_ITEMS, drug_class_code=cls, products=PRODUCTS)
    assert all(cls in c.drug_class_codes for c in result)
