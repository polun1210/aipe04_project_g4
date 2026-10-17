import pytest

from app.catalog_source import _EXAMPLE_CATALOG_DIR, CsvCatalogSource
from app.drug_mapping import map_drug_name

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
