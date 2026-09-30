"""交接點 ⑦：敘述層（後端 ⇄ LLM 組）。

輸入：Assessment ＋ 規則綁定的出處。輸出：每段一則白話說明。
建議行動的文字由模板依 advice_code 產生，不由 LLM 寫。
輸出一律先過 OutputCheckResult 檢查，不合格退回重生成；報告不可串流。
"""

from pydantic import Field, model_validator

from app.schemas.assessment import Assessment
from app.schemas.common import StrictModel
from app.schemas.enums import IngredientCode, NarrationKind
from app.schemas.rules import Citation

BANNED_PHRASES = (
    "安全", "可放心", "無問題", "未發現風險",
    "沒有交互作用", "不會超標", "確診", "你沒有疾病",
)


class NarrationInput(StrictModel):
    assessment: Assessment
    citations: list[Citation]  # 依 triggers 的 citation_ids 查表取回


class NarrationItem(StrictModel):
    kind: NarrationKind
    ingredient_code: IngredientCode | None  # summary 為 null；其餘對應 Assessment 裡的那一筆
    text: str = Field(min_length=1)

    @model_validator(mode="after")
    def _code_matches_kind(self) -> "NarrationItem":
        if (self.kind is NarrationKind.SUMMARY) != (self.ingredient_code is None):
            raise ValueError("只有 summary 的 ingredient_code 為 null")
        return self


class NarrationOutput(StrictModel):
    items: list[NarrationItem]
    model: str
    prompt_version: str

    @model_validator(mode="after")
    def _unique_items(self) -> "NarrationOutput":
        keys = [(i.kind, i.ingredient_code) for i in self.items]
        if len(keys) != len(set(keys)):
            raise ValueError("同一段落只能有一則敘述")
        if sum(i.kind is NarrationKind.SUMMARY for i in self.items) != 1:
            raise ValueError("必須剛好一則 summary")
        return self


class OutputCheckResult(StrictModel):
    """純程式關卡，絕不用 LLM 當裁判。"""

    passed: bool
    number_fidelity_violations: list[str]  # 敘述中有、但 Assessment 沒有的數字
    banned_phrase_violations: list[str]
    dosage_boundary_violations: list[str]  # 數字接 mg／ug／IU 且不在授權集合；停用、減量詞彙
