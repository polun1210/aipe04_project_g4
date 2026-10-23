import pytest

from app.catalog_source import _EXAMPLE_CATALOG_DIR, CsvCatalogSource
from app.drug_mapping import find_candidates, map_confirmed_drug, map_drug_name
from app.schemas.drug_label import DrugDraftRow

DRUG_ITEMS = CsvCatalogSource(_EXAMPLE_CATALOG_DIR).load().drug_items


def test_tradename_hits_in_scope_with_catalog_fields():
    drug = map_drug_name("立普妥", DRUG_ITEMS)
    assert drug.scope_status == "in_scope"
    assert drug.active_ingredient_code == "atorvastatin"
    assert drug.display_name_zh == "阿托伐他汀"
    assert drug.drug_class_codes == ["statin"]


@pytest.mark.parametrize("name", ["ATORVASTATIN", " atorvastatin ", "Ａtorvastatin", "阿托伐他汀"])
def test_case_width_and_whitespace_differences_still_hit(name):
    assert map_drug_name(name, DRUG_ITEMS).active_ingredient_code == "atorvastatin"


def test_compound_drug_maps_to_one_item_with_multiple_classes():
    drug = map_drug_name("Hyzaar", DRUG_ITEMS)
    assert drug.active_ingredient_code == "losartan_hydrochlorothiazide"
    assert set(drug.drug_class_codes) == {"acei_arb", "thiazide_diuretic"}


def test_gibberish_becomes_unresolved():
    drug = map_drug_name("亂打的藥名", DRUG_ITEMS)
    assert drug.scope_status == "unresolved"
    assert drug.active_ingredient_code is None
    assert drug.raw_name == "亂打的藥名"


def test_partial_match_does_not_hit():
    assert map_drug_name("立普", DRUG_ITEMS).scope_status == "unresolved"


def test_dose_is_carried_over():
    drug = map_drug_name("氧化鎂錠", DRUG_ITEMS, dose_mg=250, times_per_day=2)
    assert (drug.dose_mg, drug.times_per_day) == (250, 2)


# ── find_candidates ─────────────────────────────────────────


def test_candidates_list_each_item_once_even_if_several_names_match():
    codes = [c.active_ingredient_code for c in find_candidates("a", DRUG_ITEMS)]
    assert len(codes) == len(set(codes))


def test_candidates_put_exact_match_first():
    candidates = find_candidates("立普妥", DRUG_ITEMS)
    assert candidates[0].active_ingredient_code == "atorvastatin"
    assert candidates[0].matched_name == "立普妥"


def test_candidates_are_limited_to_ten():
    many = [
        DRUG_ITEMS[0].model_copy(update={"active_ingredient_code": f"drug_{n:02d}", "display_name_zh": f"藥{n:02d}"})
        for n in range(15)
    ]
    assert len(find_candidates("drug_", many)) == 10
    assert len(find_candidates("drug_", many, limit=3)) == 3


def test_candidates_empty_when_nothing_matches_or_blank():
    assert find_candidates("亂打的藥名", DRUG_ITEMS) == []
    assert find_candidates("  ", DRUG_ITEMS) == []


# ── 送出評估時：沒改名沿用草稿對照 ────────────────────────────


def _row(raw_name: str, code: str | None, scope: str) -> DrugDraftRow:
    return DrugDraftRow(
        row_id="d01", raw_name=raw_name, source_image_id="img-01", active_ingredient_code=code, scope_status=scope
    )


def test_unchanged_name_reuses_draft_mapping():
    # 整串原文完全比對對不到，但辨識時用商品名對到了
    row = _row("立普妥膜衣錠 10毫克", "atorvastatin", "in_scope")
    assert map_drug_name(row.raw_name, DRUG_ITEMS).scope_status == "unresolved"
    drug = map_confirmed_drug("立普妥膜衣錠 10毫克", row, DRUG_ITEMS)
    assert (drug.scope_status, drug.active_ingredient_code, drug.drug_class_codes) == (
        "in_scope",
        "atorvastatin",
        ["statin"],
    )


def test_unchanged_name_ignores_width_and_case():
    row = _row("Lipitor 10mg", "atorvastatin", "in_scope")
    assert map_confirmed_drug(" ｌｉｐｉｔｏｒ 10MG ", row, DRUG_ITEMS).active_ingredient_code == "atorvastatin"


def test_renamed_drug_is_remapped():
    row = _row("立普妥膜衣錠 10毫克", "atorvastatin", "in_scope")
    assert map_confirmed_drug("耐適恩", row, DRUG_ITEMS).active_ingredient_code == "esomeprazole"
    assert map_confirmed_drug("完全亂打的藥", row, DRUG_ITEMS).scope_status == "unresolved"


def test_unchanged_out_of_scope_stays_out_of_scope():
    drug = map_confirmed_drug("Zyloric 100mg", _row("Zyloric 100mg", None, "out_of_scope"), DRUG_ITEMS)
    assert drug.scope_status == "out_of_scope" and drug.active_ingredient_code is None


def test_unchanged_unresolved_is_remapped():
    # 草稿無法確認，但現在的目錄認得（例如同義詞表更新過）
    assert map_confirmed_drug("立普妥", _row("立普妥", None, "unresolved"), DRUG_ITEMS).scope_status == "in_scope"


def test_draft_code_missing_from_catalog_falls_back_to_remap():
    drug = map_confirmed_drug("某藥 5mg", _row("某藥 5mg", "not_in_catalog", "in_scope"), DRUG_ITEMS)
    assert drug.scope_status == "unresolved"


def test_no_draft_row_is_remapped_and_keeps_dose():
    drug = map_confirmed_drug("氧化鎂錠", None, DRUG_ITEMS, 250, 2)
    assert (drug.active_ingredient_code, drug.dose_mg, drug.times_per_day) == ("magnesium_oxide", 250, 2)
