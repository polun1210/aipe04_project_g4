"""交接點 ⑧：Report（後端 → 報告頁 Jinja2 模板與 PDF）。

= Assessment ＋ 顯示名稱 ＋ 展開的出處 ＋ 通過檢查的 LLM 敘述。
報告頁只負責排版，不做任何判斷或計算。存 reports.report JSONB，凍結後不隨規則表變動。
"""

from datetime import datetime
from uuid import UUID

from app.schemas.assessment import (
    Disclosures,
    DuplicateFinding,
    InteractionFinding,
    RelevantNutrient,
    Trigger,
)
from app.schemas.common import FrozenModel
from app.schemas.enums import AgeBand, ConditionCode, DrugClassCode, Sex
from app.schemas.rules import Citation


class ReportCondition(FrozenModel):
    condition_code: ConditionCode
    display_name_zh: str


class ReportDrug(FrozenModel):
    active_ingredient_code: str
    display_name_zh: str
    drug_class_codes: list[DrugClassCode]


class ReportProfile(FrozenModel):
    age: int
    sex: Sex
    age_band: AgeBand
    known_conditions: list[ReportCondition]
    known_conditions_none: bool
    drugs: list[ReportDrug]
    drugs_none: bool


class ReportProduct(FrozenModel):
    product_id: UUID
    display_name: str  # product_name，未填時為「保健食品 N」


class ReportDuplicate(DuplicateFinding):
    display_name_zh: str
    narration: str | None


class ReportNutrient(RelevantNutrient):
    display_name_zh: str
    narration: str | None


class ReportTrigger(Trigger):
    condition_display_name_zh: str  # 用藥類別或有效成分的中文名
    citations: list[Citation]  # 展開後的完整出處（凍結，規則日後改動不影響舊報告）


class ReportInteraction(InteractionFinding):
    display_name_zh: str
    triggers: list[ReportTrigger]
    narration: str | None


class Report(FrozenModel):
    report_id: UUID
    case_id: UUID
    generated_at: datetime
    decision_data_version: str
    narration_model: str
    prompt_version: str

    profile: ReportProfile
    products: list[ReportProduct]
    summary: str
    # 版面順序固定：重複補充 → 營養素與上限 → 交互作用 → 涵蓋範圍聲明
    duplicates: list[ReportDuplicate]
    nutrients: list[ReportNutrient]
    interactions: list[ReportInteraction]
    disclosures: Disclosures
