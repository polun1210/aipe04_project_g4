"""計算層的介面。

昊昀的真版本好了之後，只要換掉 get_calculator 回傳的實作，網址與前端都不用改。
真版本需要的輸入輸出就是這兩個函式的簽名；FakeCalculator 只做「整條能通」所需的最少事情：
  - verify_product：只做份數乘法，不做單位換算與元素量推估（缺元素量的列標為 unknown）
  - assess：不管輸入，一律回傳 06_assessment 範例（case_id 與版本戳換成這次的）
所以 FakeCalculator 的數字不可當作正確結果。
"""

from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Protocol
from uuid import UUID

from app.schemas.assessment import Assessment
from app.schemas.case import CaseProfile
from app.schemas.enums import TARGET_NUTRIENTS, ElementalBasis, FrequencyType, ScopeStatus
from app.schemas.label import (
    ComputedIntake,
    ComputedNutrient,
    ExtractionMeta,
    NutrientConfirmed,
    VerificationSubmission,
    VerifiedProduct,
)

_EXAMPLE_ASSESSMENT = Path(__file__).resolve().parents[1] / "docs" / "schemas" / "examples" / "06_assessment.json"
_NO_UL_NUTRIENTS = {"potassium", "vitamin_b12"}
_MANUAL_VERSION = "manual"


class Calculator(Protocol):
    def verify_product(self, product_id: UUID, submission: VerificationSubmission, verified_at: datetime) -> VerifiedProduct:
        """核對後送出的產品 → 後端重算後的完整產品（前端送來的計算欄位一律不採信）。"""
        ...

    def assess(self, case: CaseProfile) -> Assessment:
        """凍結的評估個案 → 評估結果。"""
        ...


def _average_day_factor(intake) -> float | None:
    """平均每天有吃的比例；as_needed 不可量化。"""
    match intake.frequency_type:
        case FrequencyType.DAILY:
            return 1.0
        case FrequencyType.ALTERNATE_DAYS:
            return 0.5
        case FrequencyType.WEEKLY_N_TIMES:
            return intake.days_per_week / 7
        case FrequencyType.CYCLIC_ON_OFF:
            return intake.cycle_on_days / (intake.cycle_on_days + intake.cycle_off_days)
        case _:
            return None


def _computed_intake(submission: VerificationSubmission) -> ComputedIntake:
    intake = submission.user_intake
    factor = _average_day_factor(intake)
    quantifiable = factor is not None
    units_peak = intake.times_per_day * intake.amount_per_time if quantifiable else None
    units_average = units_peak * factor if quantifiable else None
    serving_size = submission.serving_info.serving_size
    return ComputedIntake(
        **intake.model_dump(),
        is_quantifiable=quantifiable,
        units_per_day_peak=units_peak,
        units_per_day_average=units_average,
        servings_per_day_peak=units_peak / serving_size if quantifiable else None,
        servings_per_day_average=units_average / serving_size if quantifiable else None,
    )


def _computed_nutrient(row: NutrientConfirmed, servings_peak: float | None, servings_average: float | None) -> ComputedNutrient:
    amount, basis = None, ElementalBasis.UNKNOWN
    if row.scope_status is ScopeStatus.IN_SCOPE and row.per_serving is not None:
        if row.stated_elemental_amount is not None:
            amount, basis = row.stated_elemental_amount, ElementalBasis.LABEL_STATED
        elif row.nutrient_form_code is None:
            amount, basis = row.per_serving, ElementalBasis.NOT_APPLICABLE
    quantifiable = amount is not None and servings_peak is not None
    return ComputedNutrient(
        row_id=row.row_id,
        raw_name=None,
        display_name_zh=None,
        standard_code=row.standard_code,
        scope_status=row.scope_status,
        label_section=None,
        nutrient_form_code=row.nutrient_form_code,
        per_serving=row.per_serving,
        unit=row.unit,
        amount_per_serving_standard=amount,
        standard_unit=row.unit if amount is not None else None,
        elemental_basis=basis,
        peak_daily_amount=amount * servings_peak if quantifiable else None,
        average_daily_amount=amount * servings_average if quantifiable else None,
        ul_applicable=row.standard_code in TARGET_NUTRIENTS and row.standard_code not in _NO_UL_NUTRIENTS,
    )


class FakeCalculator:
    def verify_product(self, product_id: UUID, submission: VerificationSubmission, verified_at: datetime) -> VerifiedProduct:
        intake = _computed_intake(submission)
        return VerifiedProduct(
            product_id=product_id,
            product_name=submission.product_name,
            serving_info=submission.serving_info,
            user_intake=intake,
            nutrients=[
                _computed_nutrient(row, intake.servings_per_day_peak, intake.servings_per_day_average)
                for row in submission.nutrients
            ],
            verified_at=verified_at,
            extraction_meta=ExtractionMeta(
                ocr_version=_MANUAL_VERSION,
                rule_layer_version=_MANUAL_VERSION,
                synonym_table_version=_MANUAL_VERSION,
                extracted_at=verified_at,
            ),
        )

    def assess(self, case: CaseProfile) -> Assessment:
        example = Assessment.model_validate_json(_EXAMPLE_ASSESSMENT.read_text(encoding="utf-8"))
        return example.model_copy(
            update={"case_id": case.case_id, "decision_data_version": case.decision_data_version}
        )


@lru_cache(maxsize=1)
def get_calculator() -> Calculator:
    return FakeCalculator()
