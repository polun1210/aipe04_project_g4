"""敘述層的輸出檢查：純程式關卡，絕不用 LLM 當裁判。

LLM 寫的白話（以及固定模板）都要通過這裡才能進報告：
  - 數字：文字裡的數字都要在判定層找得到
  - 禁用詞：BANNED_PHRASES
  - 劑量邊界：數字接單位且不在判定層；停用、減量、改吃之類的建議
  - 涵蓋：每條交互作用提醒剛好一則敘述，不能漏、不能多
  - 引用：引用的 chunk_id 必須在這次檢索結果裡，且 interaction 只能引用替自己成分檢索的段落；某條交互作用有檢索到證據，說明就至少引用一段
  - 措辭：一律不准用「立即」「危險」之類的強烈字眼（ADR-0012，系統不分嚴重程度）
"""

import re
from collections.abc import Sequence

from app.narration_template import percent
from app.schemas.assessment import Assessment, InteractionFinding, RelevantNutrient
from app.schemas.enums import IngredientCode, NarrationKind
from app.schemas.narration import BANNED_PHRASES, NarrationEvidence, NarrationItem, NarrationOutput, OutputCheckResult

# 獨立的數字才檢查；B12、D3、Omega-3、COX-2 這類名稱裡的數字不算
_NUMBER = re.compile(r"(?<![A-Za-z0-9.\-－])\d+(?:\.\d+)?")
_DOSE = re.compile(r"(?<![A-Za-z0-9.\-－])(\d+(?:\.\d+)?)\s*(?:mg|毫克|ug|mcg|μg|µg|微克|IU|國際單位|公克|g)(?![A-Za-z])")
_DOSAGE_ADVICE = ("停用", "停藥", "停止服用", "減量", "減少劑量", "降低劑量", "不要再吃", "改吃", "換成")
_STRONG_WORDS = ("立即", "立刻", "馬上", "緊急", "危險", "嚴重")
# 自由問答才會出現、報告敘述不會寫的停用說法；只給對話用，不改報告敘述原有的檢查
_CHAT_EXTRA_ADVICE = (
    "暫停服用", "不要吃", "別吃", "不建議服用", "避免服用", "調整劑量", "增加劑量",
    "停止用藥", "停止服藥", "暫停用藥", "暫停服藥", "不要服藥", "不要用藥", "不要吃藥", "停吃", "不要再服用", "調整用量",
)
# 編號後面不能緊接數字：「1.35 mg」的 1 是小數，不是條列編號
_LIST_MARKER = re.compile(r"(?m)^[ \t]*\d{1,2}[.、)）](?!\d)[ \t]*")
_TOLERANCE = 1e-6


def check_narration(
    output: NarrationOutput, assessment: Assessment, evidence: Sequence[NarrationEvidence] = ()
) -> OutputCheckResult:
    allowed = allowed_numbers(assessment.relevant_nutrients, assessment.interactions)
    texts = [(_label(i), i.text) for i in output.items]
    numbers = [f"{label}：{n}" for label, text in texts for n in _NUMBER.findall(text) if not _is_allowed(n, allowed)]
    banned = [f"{label}：{p}" for label, text in texts for p in BANNED_PHRASES if p in text]
    doses = [f"{label}：{m.group(0)}" for label, text in texts for m in _DOSE.finditer(text)
             if not _is_allowed(m.group(1), allowed)]
    advice = [f"{label}：{w}" for label, text in texts for w in _DOSAGE_ADVICE if w in text]
    coverage = _coverage_violations(output, assessment)
    wording = _wording_violations(output)
    cited = _evidence_violations(output, evidence)
    return OutputCheckResult(
        passed=not (numbers or banned or doses or advice or coverage or wording or cited),
        number_fidelity_violations=numbers,
        banned_phrase_violations=banned,
        dosage_boundary_violations=doses + advice,
        coverage_violations=coverage,
        strong_wording_violations=wording,
        evidence_violations=cited,
    )


def text_violations(text: str, allowed: set[float]) -> list[str]:
    """自由文字（問答）用的同一組規則；不含「每條交互作用都要寫到」「引用」這類報告敘述專屬的檢查。

    已知限制：只看「數字有沒有出現在報告裡」，不看語意，所以「每天吃 35 mg」會因 35 是上限值而通過；中文數字（三百毫克）也抓不到。
    """
    # 條列編號（1. 2、）不是報告數字，否則任何條列回答都會被擋；
    # 數字範圍的連字號換成空白，後半段才會被檢查（「35-1000 mg」的 1000）。名稱裡的 COX-2、Omega-3 前面是字母，不受影響
    body = re.sub(r"(?<=\d)[\-－~～至](?=\d)", " ", _LIST_MARKER.sub("", text))
    return (
        [f"數字：{n}" for n in _NUMBER.findall(body) if not _is_allowed(n, allowed)]
        + [f"劑量：{m.group(0)}" for m in _DOSE.finditer(body) if not _is_allowed(m.group(1), allowed)]
        + [f"建議：{w}" for w in _DOSAGE_ADVICE + _CHAT_EXTRA_ADVICE if w in text]
        + [f"禁用詞：{p}" for p in BANNED_PHRASES if p in text]
        + [f"強烈字眼：{w}" for w in _STRONG_WORDS if w in text]
    )


def allowed_numbers(nutrients: Sequence[RelevantNutrient], interactions: Sequence[InteractionFinding]) -> set[float]:
    values: set[float] = set()
    for n in nutrients:
        values |= {n.peak_intake_from_supplements, n.average_intake_from_supplements, n.recommended_total_intake.value}
        if n.intake_from_drugs is not None:
            values.add(n.intake_from_drugs)
        if n.ul is not None:
            values |= {n.ul.ul_value, percent(n.ul.ratio), round(n.ul.ratio * 100, 1)}
    for f in interactions:
        values |= {t.separation_hours for t in f.triggers if t.separation_hours is not None}
    values.add(len(interactions))
    return values | {round(v, 1) for v in values}


def _is_allowed(number: str, allowed: set[float]) -> bool:
    value = float(number)
    return any(abs(value - a) < _TOLERANCE for a in allowed)


def _label(item: NarrationItem) -> str:
    return item.kind.value if item.ingredient_code is None else f"{item.kind.value}.{item.ingredient_code.value}"


def _coverage_violations(output: NarrationOutput, assessment: Assessment) -> list[str]:
    expected = {f.ingredient_code for f in assessment.interactions}
    written = {i.ingredient_code for i in output.items if i.kind is NarrationKind.INTERACTION}
    nutrients = {n.nutrient_code for n in assessment.relevant_nutrients}
    nutrient_items = {i.ingredient_code for i in output.items if i.kind is NarrationKind.NUTRIENT}
    return (
        [f"interaction.{c.value}：缺少敘述" for c in sorted(expected - written)]
        + [f"interaction.{c.value}：判定層沒有這條提醒" for c in sorted(written - expected)]
        + [f"nutrient.{c.value}：判定層沒有這個營養素" for c in sorted(nutrient_items - nutrients)]
    )


def _wording_violations(output: NarrationOutput) -> list[str]:
    return [f"{_label(item)}：{w}" for item in output.items for w in _STRONG_WORDS if w in item.text]


def _evidence_violations(output: NarrationOutput, evidence: Sequence[NarrationEvidence]) -> list[str]:
    """interaction 說明只能引用替自己這條成分檢索的段落；其他種類的說明可引用整次檢索結果。"""
    retrieved = {e.chunk_id for e in evidence}
    own: dict[IngredientCode, set[str]] = {}
    for e in evidence:
        own.setdefault(e.for_ingredient, set()).add(e.chunk_id)
    violations: list[str] = []
    for item in output.items:
        is_interaction = item.kind is NarrationKind.INTERACTION
        allowed = own.get(item.ingredient_code, set()) if is_interaction else retrieved
        for cid in item.evidence_ids:
            if cid not in retrieved:
                violations.append(f"{_label(item)}：引用了沒檢索到的 {cid}")
            elif cid not in allowed:
                violations.append(f"{_label(item)}：引用了其他成分的證據 {cid}")
        if is_interaction and item.ingredient_code in own and not item.evidence_ids:
            violations.append(f"{_label(item)}：有檢索到證據卻沒有引用")
    return violations
