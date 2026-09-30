"""交接點 ④⑤：保健食品標示。

④ ExtractionDraft       OCR 組 → HITL 前端    辨識草稿，只放「標示上寫了什麼」，不做任何換算
⑤ VerificationSubmission HITL 前端 → 後端    使用者核對後送出，不含任何計算欄位
  VerifiedProduct       後端內部             後端重算後的完整產品，凍結進評估個案

計算欄位（元素量、每日攝取量、ul_applicable…）只由後端產生；前端送來的一律不採信。
"""

from datetime import datetime
from uuid import UUID

from pydantic import Field, model_validator

from app.schemas.catalog import Code
from app.schemas.common import BoundingBox, FrozenModel, StrictModel
from app.schemas.enums import (
    ALLOWED_INGREDIENTS,
    CorrectionType,
    DoseUnit,
    ElementalBasis,
    FrequencyType,
    IngredientCode,
    LabelSection,
    QualityStatus,
    RejectReason,
    ScopeStatus,
    Unit,
)

Confidence = float


def _check_scope(scope: ScopeStatus, code: IngredientCode | None, unit: Unit | None) -> None:
    """in_scope ⟺ 有 standard_code；範圍內成分的單位不可是 other。"""
    if (scope is ScopeStatus.IN_SCOPE) != (code is not None):
        raise ValueError("scope_status = in_scope 若且唯若 standard_code 非 null")
    if scope is ScopeStatus.IN_SCOPE and unit is Unit.OTHER:
        raise ValueError("範圍內成分的 unit 不可為 other")


def _check_unique_rows(row_ids: list[str | None]) -> None:
    present = [r for r in row_ids if r is not None]
    if len(present) != len(set(present)):
        raise ValueError("同一產品內 row_id 不可重複")


# ═══ ④ 辨識草稿（OCR 組產出）═══════════════════════════════════


class SourceImage(StrictModel):
    image_id: str
    quality_status: QualityStatus
    reject_reason: RejectReason | None = None  # rejected 時必填；該圖不參與擷取

    @model_validator(mode="after")
    def _reason_iff_rejected(self) -> "SourceImage":
        if (self.quality_status is QualityStatus.REJECTED) != (self.reject_reason is not None):
            raise ValueError("reject_reason 只在 rejected 時填寫，且必填")
        return self


class ExtractionMeta(StrictModel):
    ocr_version: str
    rule_layer_version: str
    synonym_table_version: str  # 名稱標準化的錯誤率要能跨版本比較
    extracted_at: datetime


class ServingInfoDraft(StrictModel):
    """「每一份量 N 粒」。抓不到就填 null，HITL 會擋著要使用者補，不要猜。"""

    serving_size: float | None = Field(default=None, gt=0)  # 每份的劑型單位數
    dose_unit: DoseUnit | None = None
    source_image_id: str | None = None
    bbox: BoundingBox | None = None
    extraction_confidence: Confidence | None = Field(default=None, ge=0, le=1)


class LabelSuggestedIntake(StrictModel):
    """標示上印的建議吃法，用來預填 HITL 的服用方式選單。"""

    raw_text: str  # 「每日1次，每次2粒」
    amount_per_time: float | None = Field(default=None, gt=0)
    times_per_day: float | None = Field(default=None, gt=0)


class NutrientDraft(StrictModel):
    """標示上的一列成分。範圍是全部標示成分（營養標示方框 ＋ 成分欄），不限 13 項。

    魚油：EPA、DHA、魚油總量各一列，standard_code 都是 omega_3，
    nutrient_form_code 分別為 epa／dha／fish_oil。不用巢狀。
    """

    row_id: str  # 同一產品內唯一，例如 r01。HITL 與修正紀錄都靠它定位
    raw_name: str  # 標示原文，例如「檸檬酸鈣(含純鈣50mg)」。之後任何人都不可修改
    label_section: LabelSection
    source_image_id: str
    bbox: BoundingBox | None = None  # 組不出座標就 null，不影響數值
    extraction_confidence: Confidence | None = Field(default=None, ge=0, le=1)
    standard_code: IngredientCode | None = None  # 名稱標準化結果；範圍外與無法確認為 null
    scope_status: ScopeStatus
    nutrient_form_raw: str | None = None  # 型態原文，例如「檸檬酸鈣」
    nutrient_form_code: Code | None = None  # 例如 calcium_citrate、epa
    per_serving: float | None = Field(default=None, ge=0)  # 每份含量，照標示原單位
    unit: Unit | None = None
    # 標示有載明元素量時填，單位同 unit：
    #   「檸檬酸鈣(含純鈣50mg) 238mg」→ per_serving 238, stated 50
    #   「鈣(碳酸鈣) 200mg」         → per_serving 200, stated 200（數字本身就是元素量）
    #   「檸檬酸鈣 2000mg」          → per_serving 2000, stated null（後端依比率推估）
    stated_elemental_amount: float | None = Field(default=None, ge=0)
    percent_dv: float | None = Field(default=None, ge=0)  # 每日參考值%，只顯示，不是劑量
    requires_user_input: bool = False

    @model_validator(mode="after")
    def _consistent(self) -> "NutrientDraft":
        _check_scope(self.scope_status, self.standard_code, self.unit)
        return self


class ExtractionDraft(StrictModel):
    """GET /api/extractions/{job_id} 完成時的 result。"""

    product_id: UUID
    product_name: str | None = None  # 不參與計算；未填時前端顯示「保健食品 N」
    source_images: list[SourceImage] = Field(min_length=1)
    serving_info: ServingInfoDraft
    label_suggested_intake: LabelSuggestedIntake | None = None
    nutrients: list[NutrientDraft]
    extraction_meta: ExtractionMeta

    @model_validator(mode="after")
    def _unique_rows(self) -> "ExtractionDraft":
        _check_unique_rows([n.row_id for n in self.nutrients])
        return self


class ExtractionAccepted(StrictModel):
    """POST /api/extractions（multipart 上傳圖片）的回應。品質檢查同步完成。"""

    job_id: str | None  # 全部圖片都被拒時為 null，前端要求重拍
    product_id: UUID
    source_images: list[SourceImage]


# ═══ ⑤ 核對後送出（HITL 前端產出）════════════════════════════


class ServingInfo(StrictModel):
    """送出時必填：這是所有攝取量計算的分母。"""

    serving_size: float = Field(gt=0)
    dose_unit: DoseUnit


class UserIntake(StrictModel):
    """使用者實際吃法。劑型單位沿用 serving_info.dose_unit。"""

    frequency_type: FrequencyType
    times_per_day: float = Field(gt=0)  # 服用當日的次數
    amount_per_time: float = Field(gt=0)  # 每次幾個劑型單位
    days_per_week: float | None = Field(default=None, gt=0, le=7)  # weekly_n_times 必填
    cycle_on_days: float | None = Field(default=None, gt=0)  # cyclic_on_off 必填
    cycle_off_days: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def _frequency_fields(self) -> "UserIntake":
        weekly = self.frequency_type is FrequencyType.WEEKLY_N_TIMES
        if weekly != (self.days_per_week is not None):
            raise ValueError("days_per_week 只在 weekly_n_times 時填寫，且必填")
        cyclic = self.frequency_type is FrequencyType.CYCLIC_ON_OFF
        has_cycle = self.cycle_on_days is not None and self.cycle_off_days is not None
        if cyclic != has_cycle:
            raise ValueError("cycle_on_days／cycle_off_days 只在 cyclic_on_off 時填寫，且都必填")
        return self


class NutrientConfirmed(StrictModel):
    """核對後的一列。raw_name 不在這裡（不可改，後端從草稿取）。"""

    row_id: str | None  # 草稿原有的列帶原 row_id；使用者新增的列為 null；刪掉的列不送
    standard_code: IngredientCode | None = None  # 只能從封閉選單選，不接受自由輸入
    scope_status: ScopeStatus  # 使用者選「無法確定」→ unresolved；選「不在評估範圍」→ out_of_scope
    nutrient_form_code: Code | None = None
    per_serving: float | None = Field(default=None, ge=0)
    unit: Unit | None = None
    stated_elemental_amount: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _consistent(self) -> "NutrientConfirmed":
        _check_scope(self.scope_status, self.standard_code, self.unit)
        is_target = self.standard_code is not None and self.standard_code not in ALLOWED_INGREDIENTS
        if is_target and (self.per_serving is None or self.unit is None):
            raise ValueError("目標營養素必須有 per_serving 與 unit（允許成分可以沒有劑量）")
        return self


class VerificationSubmission(StrictModel):
    """PUT /api/products/{product_id}/verification"""

    product_name: str | None = None
    serving_info: ServingInfo
    user_intake: UserIntake
    nutrients: list[NutrientConfirmed] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_rows(self) -> "VerificationSubmission":
        _check_unique_rows([n.row_id for n in self.nutrients])
        return self


class LabelCorrection(StrictModel):
    """每次 HITL 修正一筆，後端比對草稿與送出內容產生。辨識準確率的唯一來源。

    field_path 格式：serving_info.serving_size ／ nutrients.<row_id>.<欄位> ／
    nutrients.<row_id>（整列新增或刪除）
    """

    product_id: UUID
    field_path: str
    correction_type: CorrectionType
    model_value: str | None  # 系統原本的輸出
    corrected_value: str | None  # 使用者改成的值
    ocr_version: str
    rule_layer_version: str
    synonym_table_version: str
    corrected_at: datetime


# ═══ 後端內部：重算後的完整產品（凍結進評估個案）════════════════


class UnitConversion(FrozenModel):
    from_unit: Unit
    to_unit: Unit
    factor: float
    applies_to_form: str
    source: str


class ComputedIntake(FrozenModel):
    """UserIntake ＋ 後端計算值。上限比對一律用 peak（ADR-0005）。"""

    frequency_type: FrequencyType
    times_per_day: float
    amount_per_time: float
    days_per_week: float | None = None
    cycle_on_days: float | None = None
    cycle_off_days: float | None = None
    is_quantifiable: bool  # as_needed 為 false
    units_per_day_peak: float | None
    units_per_day_average: float | None
    servings_per_day_peak: float | None  # ÷ serving_size，允許非整數
    servings_per_day_average: float | None


class ComputedNutrient(FrozenModel):
    row_id: str | None
    raw_name: str | None  # 使用者新增的列為 null
    display_name_zh: str | None  # 凍結當下從目錄複製；範圍外與無法確認為 null
    standard_code: IngredientCode | None
    scope_status: ScopeStatus
    label_section: LabelSection | None  # 使用者新增的列為 null
    nutrient_form_code: str | None
    per_serving: float | None
    unit: Unit | None
    amount_per_serving_standard: float | None  # 換算與元素量處理後；所有計算一律用此欄
    standard_unit: Unit | None
    conversion: UnitConversion | None = None
    elemental_basis: ElementalBasis
    compound_code: str | None = None  # estimated 時記錄所用化合物
    elemental_ratio: float | None = None  # estimated 時記錄所用比率
    peak_daily_amount: float | None  # ★上限比對使用★
    average_daily_amount: float | None  # 重複補充與一般呈現使用
    ul_applicable: bool  # 無 UL（鉀、B12）或允許成分為 false


class VerifiedProduct(FrozenModel):
    product_id: UUID
    product_name: str | None
    serving_info: ServingInfo
    user_intake: ComputedIntake
    nutrients: list[ComputedNutrient]
    verified_at: datetime
    extraction_meta: ExtractionMeta
