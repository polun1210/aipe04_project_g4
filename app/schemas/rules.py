"""交接點 ②：規則表與出處（建表組 → 後端規則引擎）。

rules.csv、citations.csv 各一列 ＝ 一個模型實例。
嚴重度判定條件、evidence_tier 的值由建表規範決定（待定稿），欄位先放著。
"""

import re
from datetime import date

from pydantic import Field, HttpUrl, model_validator

from app.schemas.catalog import Code
from app.schemas.common import PipeList, StrictModel
from app.schemas.enums import (
    AdviceCode,
    CandidateDirection,
    CitationSource,
    ConditionType,
    DrugClassCode,
    IngredientCode,
    InteractionType,
    Jurisdiction,
    RuleStatus,
    Severity,
)

# 獨立的數字（劑量、時數）才算違規；B12、D3、n-3、COX-2 這類名稱裡的數字不算
_DIGIT = re.compile(r"(?<![A-Za-z0-9\-])\d")


class Rule(StrictModel):
    """rules.csv：一條規則 ＝ 一個用藥類別或有效成分 → 一個成分 → 一個方向。"""

    rule_id: str  # 例如 R-0012，報告、出處、測試都以此回溯
    condition_type: ConditionType
    condition_code: Code  # drug_class 時為 DrugClassCode；drug_ingredient 時為有效成分代碼
    ingredient_code: IngredientCode
    ingredient_form_codes: PipeList[str] = Field(default_factory=list)  # 空 ＝ 所有型態適用
    interaction_type: InteractionType
    requires_supplement_intake: bool
    severity: Severity
    requires_professional_review: bool  # 報告是否建議使用者諮詢醫師、藥師
    advice_code: AdviceCode
    separation_hours: float | None = Field(default=None, gt=0)
    reason_zh: str  # 經覆核的固定說明，不得含數字
    citation_ids: PipeList[str] = Field(min_length=1)
    evidence_tier: str  # 值由建表規範定義（待定稿）
    status: RuleStatus
    curated_by: str
    reviewed_by: str | None = None  # status = reviewed 時必填，且不可與 curated_by 相同
    reviewed_at: date | None = None
    curation_note: str | None = None

    @model_validator(mode="after")
    def _invariants(self) -> "Rule":
        """rule-table.md §九 的自動檢查（出處類的檢查需要 citations 表，在測試裡做）。"""
        if self.condition_type is ConditionType.DRUG_CLASS and self.condition_code not in {
            c.value for c in DrugClassCode
        }:
            raise ValueError(f"{self.condition_code} 不是 16 個用藥類別之一")
        affects = self.interaction_type is InteractionType.DRUG_AFFECTS_NUTRIENT
        if affects == self.requires_supplement_intake:
            raise ValueError("drug_affects_nutrient ⟺ requires_supplement_intake = false")
        timing = self.advice_code is AdviceCode.SEPARATE_TIMING
        if timing != (self.separation_hours is not None):
            raise ValueError("separation_hours 非空 ⟺ advice_code = separate_timing")
        if _DIGIT.search(self.reason_zh):
            raise ValueError("reason_zh 不可含數字（間隔時數由模板插入）")
        if self.status is RuleStatus.REVIEWED:
            if not self.reviewed_by or self.reviewed_at is None:
                raise ValueError("reviewed 規則必須有 reviewed_by 與 reviewed_at")
            if self.reviewed_by == self.curated_by:
                raise ValueError("建表者與覆核者須為不同人")
        return self


class Citation(StrictModel):
    """citations.csv"""

    citation_id: str
    source: CitationSource
    source_record_id: str | None = None  # set_id、PMID、DRIs 行號等
    url: HttpUrl | None = None
    section: str | None = None
    quote: str = Field(min_length=1)  # 能支持規則的最短原文段落
    population: str  # 例如「長期服用 Metformin 者」；與 DRIs 族群不同時必須標明
    jurisdiction: Jurisdiction
    retrieved_at: date
    source_version: str | None = None


class RuleCandidate(StrictModel):
    """建表 pipeline 的 LLM 抽取輸出（離線，不進 app 執行期）。嚴重度與建議行動由人決定。"""

    candidate_id: str
    nutrient_code: IngredientCode
    drug_class_code: DrugClassCode
    active_ingredient_code: Code | None = None  # 出處限定單一成分時才填
    interaction_type: InteractionType
    direction: CandidateDirection
    requires_supplement_intake: bool
    mechanism_zh: str
    evidence_quote: str = Field(min_length=1)  # ★必須是來源原文的逐字片段★
    source_id: str
    source_url: HttpUrl
    jurisdiction: Jurisdiction
    retrieved_at: date
    severity: None = None  # LLM 不得填寫
    advice_code: None = None  # LLM 不得填寫
