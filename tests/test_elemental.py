"""app/elemental.py：元素量推估與單位換算（ADR-0004）。用真的 data/catalog 參考資料。"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.calculator import FakeCalculator
from app.catalog_source import get_catalog_source
from app.elemental import standard_amount
from app.schemas.enums import ElementalBasis, Unit
from app.schemas.label import NutrientConfirmed, VerificationSubmission

REF = get_catalog_source().load_reference()
INGREDIENTS = {i.code: i for i in REF.catalog.ingredients}
AT = datetime(2026, 11, 1, tzinfo=UTC)


def _row(code: str, **fields) -> NutrientConfirmed:
    return NutrientConfirmed(row_id="r01", standard_code=code, scope_status="in_scope", **fields)


def _calc(code: str, **fields):
    return standard_amount(_row(code, **fields), INGREDIENTS[code], REF)


def test_label_stated_uses_stated_amount():
    result = _calc("calcium", nutrient_form_code="calcium_citrate_tetrahydrate", per_serving=238, unit="mg",
                   stated_elemental_amount=50)  # fmt: skip
    assert (result.amount, result.basis, result.standard_unit) == (50, ElementalBasis.LABEL_STATED, Unit.MG)
    assert result.compound_code is None


def test_known_compound_is_estimated_with_ratio():
    result = _calc("calcium", nutrient_form_code="calcium_carbonate", per_serving=500, unit="mg")
    assert result.basis is ElementalBasis.ESTIMATED
    assert result.amount == pytest.approx(200.2)  # 500 × 0.4004
    assert (result.compound_code, result.ratio) == ("calcium_carbonate", 0.4004)


def test_compound_in_grams_is_converted_to_mg():
    result = _calc("magnesium", nutrient_form_code="magnesium_oxide", per_serving=1, unit="g")
    assert result.amount == pytest.approx(603)
    assert result.standard_unit is Unit.MG


def test_unknown_compound_is_not_guessed():
    result = _calc("zinc", nutrient_form_code="zinc_gluconate", per_serving=70, unit="mg")
    assert (result.amount, result.basis, result.standard_unit) == (None, ElementalBasis.UNKNOWN, None)


def test_compound_of_another_nutrient_is_unknown():
    result = _calc("iron", nutrient_form_code="calcium_carbonate", per_serving=500, unit="mg")
    assert result.basis is ElementalBasis.UNKNOWN


def test_no_form_code_uses_label_amount_as_not_applicable():
    result = _calc("vitamin_c", per_serving=500, unit="mg")
    assert (result.amount, result.basis) == (500, ElementalBasis.NOT_APPLICABLE)


def test_vitamin_d_iu_converted_to_ug():
    result = _calc("vitamin_d", per_serving=1000, unit="iu")
    assert (result.amount, result.basis, result.standard_unit) == (25, ElementalBasis.NOT_APPLICABLE, Unit.UG)
    assert result.conversion is not None and result.conversion.factor == 0.025


def test_vitamin_e_iu_and_form_specific_mg():
    iu = _calc("vitamin_e", per_serving=100, unit="iu")
    assert iu.amount == pytest.approx(67) and iu.standard_unit is Unit.MG_ATE
    mg = _calc("vitamin_e", nutrient_form_code="d_alpha_tocopheryl_acetate", per_serving=100, unit="mg")
    assert mg.amount == pytest.approx(91)


def test_vitamin_e_plain_mg_cannot_be_converted():
    assert _calc("vitamin_e", per_serving=100, unit="mg").basis is ElementalBasis.UNKNOWN


def test_g_to_ug_is_exact():
    assert _calc("selenium", per_serving=0.00005, unit="g").amount == 50


def test_niacin_form_converts_via_all_rule():
    result = _calc("niacin", nutrient_form_code="niacinamide", per_serving=15, unit="mg")
    assert (result.amount, result.standard_unit) == (15, Unit.MG_NE)


def test_allowed_ingredient_is_presence_only():
    result = _calc("red_yeast_rice", nutrient_form_code="monacolin_k", per_serving=10, unit="mg")
    assert (result.amount, result.basis, result.standard_unit) == (None, ElementalBasis.NOT_APPLICABLE, None)


def test_out_of_scope_row_is_unknown():
    row = NutrientConfirmed(row_id="r09", scope_status="out_of_scope", per_serving=5, unit="mg")
    assert standard_amount(row, None, REF).basis is ElementalBasis.UNKNOWN


def test_verify_product_daily_amounts_use_standard_amount():
    submission = VerificationSubmission.model_validate({
        "product_name": "鈣片",
        "serving_info": {"serving_size": 2, "dose_unit": "tablet"},
        "user_intake": {"frequency_type": "alternate_days", "times_per_day": 2, "amount_per_time": 2},
        "nutrients": [{
            "row_id": "r01", "standard_code": "calcium", "scope_status": "in_scope",
            "nutrient_form_code": "calcium_carbonate", "per_serving": 500, "unit": "mg",
        }],
    })  # fmt: skip
    [row] = FakeCalculator().verify_product(uuid4(), submission, AT).nutrients
    # 每天 4 粒 ÷ 每份 2 粒 ＝ 2 份；隔天吃平均 1 份
    assert row.elemental_basis is ElementalBasis.ESTIMATED
    assert row.amount_per_serving_standard == pytest.approx(200.2)
    assert row.peak_daily_amount == pytest.approx(400.4)
    assert row.average_daily_amount == pytest.approx(200.2)
    assert (row.compound_code, row.elemental_ratio) == ("calcium_carbonate", 0.4004)


def test_verify_product_unknown_amount_has_no_daily_amount():
    submission = VerificationSubmission.model_validate({
        "product_name": "鋅片",
        "serving_info": {"serving_size": 1, "dose_unit": "tablet"},
        "user_intake": {"frequency_type": "daily", "times_per_day": 1, "amount_per_time": 1},
        "nutrients": [{
            "row_id": "r01", "standard_code": "zinc", "scope_status": "in_scope",
            "nutrient_form_code": "zinc_gluconate", "per_serving": 70, "unit": "mg",
        }],
    })  # fmt: skip
    [row] = FakeCalculator().verify_product(uuid4(), submission, AT).nutrients
    assert (row.elemental_basis, row.peak_daily_amount, row.amount_per_serving_standard) == (
        ElementalBasis.UNKNOWN, None, None,
    )
