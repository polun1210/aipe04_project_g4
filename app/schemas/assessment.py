"""交接點 ⑥：Assessment（後端計算層＋規則引擎 → 敘述層）。

等級與結論在這裡就完全確定。LLM 只能把它說成人話，不得改等級、不得改數字。
這一層只放代碼；顯示名稱在 Report 才展開。
"""

from uuid import UUID

from pydantic import Field, model_validator

from app.schemas.common import FrozenModel
from app.schemas.enums import (
    SEVERITY_RANK,
    TARGET_NUTRIENTS,
    AdviceCode,
    ConditionCode,
    ConditionType,
    DrugClassCode,
    ElementalBasis,
    IngredientCode,
    InteractionType,
    ReferenceType,
    Severity,
    ULPhrasing,
    ULScope,
    Unit,
)


class RecommendedIntake(FrozenModel):
    """建議總攝取量（含飲食）。與補充劑來源攝取量口徑不同，不可相減成「缺口」。"""

    reference_type: ReferenceType
    value: float


class ULComparison(FrozenModel):
    """上限比對，一律用單日峰值（ADR-0005）。藥品來源不計入比例（臨床紅線一）。"""

    ul_value: float
    ratio: float  # peak_intake_from_supplements ÷ ul_value
    exceeded: bool
    scope: ULScope
    phrasing: ULPhrasing  # 由 scope × exceeded 決定；任何情況都不產生「未超過」「安全」


class RelevantNutrient(FrozenModel):
    """相關營養素：使用者有補的，或被「藥物影響營養素」規則觸發的（沒補也列）。

    三個數值並列，不判定高低。
    """

    nutrient_code: IngredientCode
    is_supplemented: bool
    triggered_by_drug: bool
    peak_intake_from_supplements: float = Field(ge=0)  # 沒補為 0
    average_intake_from_supplements: float = Field(ge=0)
    intake_from_drugs: float | None = None  # 只有制酸劑類會有，分開呈現
    unit: Unit
    basis: ElementalBasis  # 任一來源為 estimated 即為 estimated → 報告寫「推估」
    recommended_total_intake: RecommendedIntake
    ul: ULComparison | None  # null ＝ 無 UL（鉀、B12），不做數值比對

    @model_validator(mode="after")
    def _is_relevant(self) -> "RelevantNutrient":
        if self.nutrient_code not in TARGET_NUTRIENTS:
            raise ValueError("相關營養素只能是 13 項目標營養素")
        if not (self.is_supplemented or self.triggered_by_drug):
            raise ValueError("沒補、也沒被用藥觸發的營養素不列入")
        return self


class Trigger(FrozenModel):
    rule_id: str
    condition_type: ConditionType
    condition_code: str
    interaction_type: InteractionType
    severity: Severity
    advice_code: AdviceCode
    separation_hours: float | None = None  # findings 裡唯一允許的數字
    reason_zh: str
    citation_ids: list[str] = Field(min_length=1)


class InteractionFinding(FrozenModel):
    """每個成分一筆，已聚合：取最高等級，永不降級（ADR-0009）。不含任何攝取量數字。"""

    ingredient_code: IngredientCode
    severity: Severity
    requires_professional_review: bool
    user_has_supplement: bool
    matched_product_ids: list[UUID]
    triggers: list[Trigger] = Field(min_length=1)

    @model_validator(mode="after")
    def _max_severity(self) -> "InteractionFinding":
        highest = max(self.triggers, key=lambda t: SEVERITY_RANK[t.severity]).severity
        if self.severity is not highest:
            raise ValueError("severity 必須是所有 triggers 中的最高等級")
        if self.user_has_supplement != bool(self.matched_product_ids):
            raise ValueError("user_has_supplement 與 matched_product_ids 不一致")
        return self


class UndeterminedAmount(FrozenModel):
    """範圍內成分，但含量無法判定（elemental_basis = unknown），沒有算進加總與上限比對。

    例如只寫「海藻鈣 500mg」：知道是鈣，但不知道元素鈣有多少。報告要寫出來，不能默默略過。
    範圍外、無法確認的成分另有 out_of_scope_ingredients／unresolved_ingredients，不放這裡；
    紅麴這類允許成分只判有沒有、本來就沒有含量，也不放這裡。
    """

    product_id: UUID
    row_id: str | None  # 使用者新增的列為 null
    raw_name: str | None  # 標示原文；使用者新增的列為 null
    nutrient_code: IngredientCode


class Disclosures(FrozenModel):
    """報告固定揭露的範圍資訊。文案在模板，這裡只放資料。"""

    covered_known_conditions: list[ConditionCode]
    covered_drug_classes: list[DrugClassCode]
    covered_nutrients: list[IngredientCode]
    known_conditions_none: bool  # 「你未勾選本系統涵蓋的 5 種慢性病」，不可寫「你沒有疾病」
    drugs_none: bool  # 略過藥包辨識 → 報告寫「你沒有提供用藥資料」，不可寫「你沒有用藥」
    healthy_population_caveat: bool  # 勾了任一慢性病 → DRIs 為健康族群參考值
    peak_same_day_assumption: bool  # 有非每日服用的產品時，峰值假設同日服用
    out_of_scope_ingredients: list[str]  # raw_name，中性語氣
    unresolved_ingredients: list[str]  # raw_name，警示語氣＋建議諮詢藥師
    out_of_scope_drugs: list[str]  # raw_name；中性語氣「不在本系統評估範圍」
    unresolved_drugs: list[str]  # raw_name；寫明「無法判斷是否有交互作用」
    drug_source_not_counted: list[IngredientCode]
    undetermined_amounts: list[UndeterminedAmount]  # 含量無法判定、沒算進上限比對的成分列


class Assessment(FrozenModel):
    """存 assessments.assessment JSONB。報告版面順序：營養素與上限 → 交互作用 → 揭露。"""

    case_id: UUID
    decision_data_version: str
    relevant_nutrients: list[RelevantNutrient]
    interactions: list[InteractionFinding]
    disclosures: Disclosures

    @model_validator(mode="after")
    def _one_finding_per_ingredient(self) -> "Assessment":
        codes = [f.ingredient_code for f in self.interactions]
        if len(codes) != len(set(codes)):
            raise ValueError("interactions 每個成分只能一筆（已聚合）")
        return self
