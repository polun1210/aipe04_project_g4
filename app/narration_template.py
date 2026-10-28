"""固定模板敘述：不呼叫 LLM 也能產出完整報告，也是 LLM 輸出檢查不合格時的備用。

只把判定層的結論換成句子，不做任何判斷或計算；百分比由 ul.ratio 四捨五入而來。
句子之後換成羿文的模板句子時，只改這個檔，輸出格式（NarrationOutput）不變。
"""

from decimal import ROUND_HALF_UP, Decimal

from app.schemas.assessment import Assessment, InteractionFinding, RelevantNutrient
from app.schemas.enums import SEVERITY_RANK, ElementalBasis, IngredientCode, NarrationKind, Severity, ULPhrasing
from app.schemas.narration import NarrationItem, NarrationOutput

TEMPLATE_MODEL = "template"
TEMPLATE_PROMPT_VERSION = "template-v1"

SEVERITY_LABEL = {Severity.PRIORITY: "優先處理", Severity.ATTENTION: "需留意", Severity.INFO: "提醒"}

_UL_SENTENCE = {
    ULPhrasing.EXCEEDED_SUPPLEMENT_ONLY: "{name}的補充劑攝取已超過上限攝取量。",
    ULPhrasing.PERCENT_SUPPLEMENT_ONLY: "{name}的補充劑攝取已達上限攝取量的{pct}%。",
    ULPhrasing.EXCEEDED_TOTAL_INTAKE: "{name}光是補充劑來源就已超過上限攝取量，這還沒有算進飲食。",
    ULPhrasing.PERCENT_TOTAL_INTAKE: "{name}的補充劑來源已達上限攝取量的{pct}%，這個比例尚未包含飲食。",
}


def percent(ratio: float) -> int:
    # 一般四捨五入（62.5 → 63），與提示詞一致；內建 round() 遇 .5 會取偶數
    return int((Decimal(str(ratio)) * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def template_narration(
    assessment: Assessment, names: dict[IngredientCode, str], condition_names: dict[str, str]
) -> NarrationOutput:
    """names：成分代碼 → 中文名稱；condition_names：用藥類別或有效成分代碼 → 中文名稱。"""
    items = [NarrationItem(kind=NarrationKind.SUMMARY, ingredient_code=None, text=_summary(assessment, names))]
    for n in assessment.relevant_nutrients:
        text = _nutrient_text(n, names[n.nutrient_code])
        if text:
            items.append(NarrationItem(kind=NarrationKind.NUTRIENT, ingredient_code=n.nutrient_code, text=text))
    for f in assessment.interactions:
        text = _interaction_text(f, names[f.ingredient_code], condition_names)
        items.append(NarrationItem(kind=NarrationKind.INTERACTION, ingredient_code=f.ingredient_code, text=text))
    return NarrationOutput(items=items, model=TEMPLATE_MODEL, prompt_version=TEMPLATE_PROMPT_VERSION)


def _nutrient_text(n: RelevantNutrient, name: str) -> str | None:
    if n.ul is None:
        return None
    text = _UL_SENTENCE[n.ul.phrasing].format(name=name, pct=percent(n.ul.ratio))
    if n.basis is ElementalBasis.ESTIMATED:
        text += "其中有含量是依化合物比例推估的。"
    return text


def _interaction_text(f: InteractionFinding, name: str, condition_names: dict[str, str]) -> str:
    reasons = "；".join(
        f"{condition_names.get(t.condition_code, t.condition_code)}：{t.reason_zh}" for t in f.triggers
    )
    if not f.user_has_supplement:
        return f"你沒有補充{name}，這一條是因為你服用的藥物而提醒：{reasons}。"
    return f"{reasons}。"


def _summary(assessment: Assessment, names: dict[IngredientCode, str]) -> str:
    parts = [_interaction_summary(assessment, names)]
    exceeded = [names[n.nutrient_code] for n in assessment.relevant_nutrients if n.ul and n.ul.exceeded]
    if exceeded:
        parts.append(f"{'、'.join(exceeded)}的補充劑攝取已超過上限攝取量，請和醫師或藥師討論。")
    undetermined = dict.fromkeys(names[u.nutrient_code] for u in assessment.disclosures.undetermined_amounts)
    if undetermined:
        parts.append(f"有部分{'、'.join(undetermined)}的含量無法判定，沒有算進上限比對，請詢問藥師。")
    if assessment.disclosures.unresolved_drugs:
        parts.append("有部分藥物無法確認是哪一種，無法判斷是否有交互作用，請詢問藥師。")
    return "".join(parts)


def _interaction_summary(assessment: Assessment, names: dict[IngredientCode, str]) -> str:
    findings = assessment.interactions
    if not findings:
        return "這次的用藥與保健食品沒有命中本系統的任何規則，但這不等於一定適合你，有疑問請詢問醫師或藥師。"
    counts = "、".join(
        f"{SEVERITY_LABEL[s]} {n} 項" for s in Severity if (n := sum(f.severity is s for f in findings))
    )
    top = max(findings, key=lambda f: SEVERITY_RANK[f.severity])
    top_names = "、".join(names[f.ingredient_code] for f in findings if f.severity is top.severity)
    return f"這次共有 {len(findings)} 項提醒（{counts}），最需要先看的是{top_names}。"

