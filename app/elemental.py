"""核對時的元素量與單位換算（ADR-0004）。純函式，不碰資料庫、不呼叫模型。

  標示有元素量                      → label_stated
  型態代碼對得到化合物比率表        → estimated（化合物量 × 比率）
  有型態代碼但比率表與換算表都沒有  → unknown（不猜）
  沒有型態代碼（維生素等）          → not_applicable，直接用標示量
  允許成分（紅麴、葡萄糖胺、魚油）  → 只判有沒有，不換算

計算全部用 Fraction，輸出才轉 float，避免 0.1 + 0.2 這類浮點誤差。
"""

from dataclasses import dataclass
from fractions import Fraction

from app.schemas.catalog import CompoundRatio, ConversionFactor, Ingredient
from app.schemas.enums import ALLOWED_INGREDIENTS, ElementalBasis, ScopeStatus, Unit
from app.schemas.label import NutrientConfirmed, UnitConversion
from app.schemas.reference import ReferenceData

# 質量單位之間的換算（以 mg 為基準），不需要查表
_MASS_IN_MG = {Unit.G: Fraction(1000), Unit.MG: Fraction(1), Unit.UG: Fraction(1, 1000)}
_ALL_FORMS = "all"


@dataclass(frozen=True)
class ElementalResult:
    amount: float | None
    basis: ElementalBasis
    standard_unit: Unit | None = None
    conversion: UnitConversion | None = None  # 用到換算表時記錄是哪一列
    compound_code: str | None = None  # estimated 時所用化合物
    ratio: float | None = None  # estimated 時所用比率


_UNKNOWN = ElementalResult(None, ElementalBasis.UNKNOWN)


def _exact(value: float) -> Fraction:
    return Fraction(str(value))


def standard_amount(row: NutrientConfirmed, ingredient: Ingredient | None, ref: ReferenceData) -> ElementalResult:
    """一列成分 → 標準單位下的每份元素量。"""
    if row.scope_status is not ScopeStatus.IN_SCOPE or row.standard_code is None:
        return _UNKNOWN
    if row.standard_code in ALLOWED_INGREDIENTS:
        return ElementalResult(None, ElementalBasis.NOT_APPLICABLE)
    if row.unit is None or ingredient is None or ingredient.standard_unit is None:
        return _UNKNOWN
    target = ingredient.standard_unit

    if row.stated_elemental_amount is not None:
        return _result(_exact(row.stated_elemental_amount), row, target, ref, ElementalBasis.LABEL_STATED)
    if row.per_serving is None:
        return _UNKNOWN
    amount = _exact(row.per_serving)

    if row.nutrient_form_code is None:
        return _result(amount, row, target, ref, ElementalBasis.NOT_APPLICABLE)

    compound = next((c for c in ref.compounds if c.compound_code == row.nutrient_form_code), None)
    if compound is not None:
        if compound.nutrient_code != row.standard_code:
            return _UNKNOWN
        return _result(amount * _exact(compound.ratio), row, target, ref, ElementalBasis.ESTIMATED, compound)
    # 型態不在比率表：只有換算表明確涵蓋這個型態（或 all）時才換算，其餘不猜
    return _result(amount, row, target, ref, ElementalBasis.NOT_APPLICABLE, require_rule=True)


def _result(
    amount: Fraction,
    row: NutrientConfirmed,
    target: Unit,
    ref: ReferenceData,
    basis: ElementalBasis,
    compound: CompoundRatio | None = None,
    *,
    require_rule: bool = False,
) -> ElementalResult:
    converted = _convert(amount, row.unit, target, row.standard_code, row.nutrient_form_code, ref.conversion_factors)
    if converted is None:
        return _UNKNOWN
    value, rule = converted
    if require_rule and rule is None:
        return _UNKNOWN
    conversion = (
        UnitConversion(
            from_unit=rule.from_unit,
            to_unit=rule.to_unit,
            factor=rule.factor,
            applies_to_form=rule.applies_to_form,
            source=rule.source,
        )
        if rule is not None
        else None
    )
    return ElementalResult(
        amount=float(value),
        basis=basis,
        standard_unit=target,
        conversion=conversion,
        compound_code=compound.compound_code if compound else None,
        ratio=compound.ratio if compound else None,
    )


def _convert(
    amount: Fraction,
    from_unit: Unit,
    to_unit: Unit,
    nutrient: str,
    form_code: str | None,
    factors: list[ConversionFactor],
) -> tuple[Fraction, ConversionFactor | None] | None:
    """回傳（換算後數值, 用到的換算表列）；換不了回傳 None。質量單位互換不查表，表列為 None。"""
    if from_unit is to_unit:
        return amount, None
    if from_unit in _MASS_IN_MG and to_unit in _MASS_IN_MG:
        return amount * _MASS_IN_MG[from_unit] / _MASS_IN_MG[to_unit], None
    direct = _find_factor(factors, nutrient, from_unit, to_unit, form_code)
    if direct is not None:
        return amount * _exact(direct.factor), direct
    # 先把質量單位換成 mg 再查表（例如 ug → mg → mg_ne）
    if from_unit in _MASS_IN_MG:
        via = _find_factor(factors, nutrient, Unit.MG, to_unit, form_code)
        if via is not None:
            return amount * _MASS_IN_MG[from_unit] * _exact(via.factor), via
    return None


def _find_factor(
    factors: list[ConversionFactor], nutrient: str, from_unit: Unit, to_unit: Unit, form_code: str | None
) -> ConversionFactor | None:
    """該型態專屬的列優先，其次 applies_to_form = all。"""
    candidates = [f for f in factors if f.nutrient_code == nutrient and f.from_unit is from_unit and f.to_unit is to_unit]
    for form in (form_code, _ALL_FORMS):
        match = next((f for f in candidates if f.applies_to_form == form), None)
        if match is not None:
            return match
    return None
