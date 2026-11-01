"""計算層的介面與實作。

  - verify_product：核對時換算份數、單位與元素量（app/elemental.py）
  - assess：凍結的個案 ＋ 參考資料 → 評估結果（app/assessing.py）
兩者都是純計算，不碰資料庫、不呼叫模型；參考資料由 CatalogSource 提供。
"""

from datetime import datetime
from functools import lru_cache
from typing import Protocol
from uuid import UUID

from app.assessing import assess
from app.catalog_source import get_catalog_source
from app.elemental import standard_amount
from app.schemas.assessment import Assessment
from app.schemas.catalog import Ingredient
from app.schemas.case import CaseProfile
from app.schemas.enums import TARGET_NUTRIENTS, FrequencyType
from app.schemas.reference import ReferenceData
from app.schemas.label import (
    ExtractionDraft,
    ComputedIntake,
    ComputedNutrient,
    ExtractionMeta,
    NutrientConfirmed,
    VerificationSubmission,
    VerifiedProduct,
)

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


def _computed_nutrient(
    row: NutrientConfirmed,
    servings_peak: float | None,
    servings_average: float | None,
    ingredients: dict[str, Ingredient],
    ref: ReferenceData,
) -> ComputedNutrient:
    ingredient = ingredients.get(row.standard_code) if row.standard_code else None
    result = standard_amount(row, ingredient, ref)
    amount = result.amount
    return ComputedNutrient(
        row_id=row.row_id,
        raw_name=None,
        display_name_zh=ingredient.display_name_zh if ingredient else None,  # 範圍內才有；其餘為 null
        standard_code=row.standard_code,
        scope_status=row.scope_status,
        label_section=None,
        nutrient_form_code=row.nutrient_form_code,
        per_serving=row.per_serving,
        unit=row.unit,
        amount_per_serving_standard=amount,
        standard_unit=result.standard_unit,
        conversion=result.conversion,
        elemental_basis=result.basis,
        compound_code=result.compound_code,
        elemental_ratio=result.ratio,
        peak_daily_amount=amount * servings_peak if amount is not None and servings_peak is not None else None,
        average_daily_amount=amount * servings_average if amount is not None and servings_average is not None else None,
        ul_applicable=row.standard_code in TARGET_NUTRIENTS and row.standard_code not in _NO_UL_NUTRIENTS,
    )


class RealCalculator:
    def __init__(self, reference: ReferenceData | None = None) -> None:
        self._reference = reference

    @property
    def reference(self) -> ReferenceData:
        if self._reference is None:
            self._reference = get_catalog_source().load_reference()
        return self._reference

    def verify_product(self, product_id: UUID, submission: VerificationSubmission, verified_at: datetime) -> VerifiedProduct:
        intake = _computed_intake(submission)
        ref = self.reference
        ingredients = {i.code: i for i in ref.catalog.ingredients}
        return VerifiedProduct(
            product_id=product_id,
            product_name=submission.product_name,
            serving_info=submission.serving_info,
            user_intake=intake,
            nutrients=[
                _computed_nutrient(row, intake.servings_per_day_peak, intake.servings_per_day_average, ingredients, ref)
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
        return assess(case, self.reference)


def with_label_names(product: VerifiedProduct, draft: ExtractionDraft | None) -> VerifiedProduct:
    """依 row_id 把辨識草稿的標示原文與區塊帶進來（raw_name 不可改，後端從草稿取）。

    使用者新增的列（row_id 為 null 或草稿裡沒有）維持 null。
    """
    if draft is None:
        return product
    rows = {r.row_id: r for r in draft.nutrients}
    nutrients = [
        n.model_copy(update={"raw_name": rows[n.row_id].raw_name, "label_section": rows[n.row_id].label_section})
        if n.row_id in rows
        else n
        for n in product.nutrients
    ]
    return product.model_copy(update={"nutrients": nutrients})


@lru_cache(maxsize=1)
def get_calculator() -> Calculator:
    return RealCalculator()
