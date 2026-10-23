"""敘述層的輸出檢查：純程式關卡，絕不用 LLM 當裁判。

LLM 寫的白話（以及固定模板）都要通過這裡才能進報告：
  - 數字：文字裡的數字都要在判定層找得到
  - 禁用詞：BANNED_PHRASES
  - 劑量邊界：數字接單位且不在判定層；停用、減量、改吃之類的建議
  - 涵蓋：每條交互作用提醒剛好一則敘述，不能漏、不能多
  - 措辭：不是「優先處理」等級卻用了「立即」「危險」之類的強烈字眼
"""

import re
from collections import Counter

from app.narration_template import percent
from app.schemas.assessment import Assessment
from app.schemas.enums import NarrationKind, Severity
from app.schemas.narration import BANNED_PHRASES, NarrationItem, NarrationOutput, OutputCheckResult

# 獨立的數字才檢查；B12、D3、Omega-3、COX-2 這類名稱裡的數字不算
_NUMBER = re.compile(r"(?<![A-Za-z0-9.\-－])\d+(?:\.\d+)?")
_DOSE = re.compile(r"(?<![A-Za-z0-9.\-－])(\d+(?:\.\d+)?)\s*(?:mg|毫克|ug|mcg|μg|µg|微克|IU|國際單位|公克|g)(?![A-Za-z])")
_DOSAGE_ADVICE = ("停用", "停藥", "停止服用", "減量", "減少劑量", "降低劑量", "不要再吃", "改吃", "換成")
_STRONG_WORDS = ("立即", "立刻", "馬上", "緊急", "危險", "嚴重")
_TOLERANCE = 1e-6


def check_narration(output: NarrationOutput, assessment: Assessment) -> OutputCheckResult:
    allowed = _allowed_numbers(assessment)
    texts = [(_label(i), i.text) for i in output.items]
    numbers = [f"{label}：{n}" for label, text in texts for n in _NUMBER.findall(text) if not _is_allowed(n, allowed)]
    banned = [f"{label}：{p}" for label, text in texts for p in BANNED_PHRASES if p in text]
    doses = [f"{label}：{m.group(0)}" for label, text in texts for m in _DOSE.finditer(text)
             if not _is_allowed(m.group(1), allowed)]
    advice = [f"{label}：{w}" for label, text in texts for w in _DOSAGE_ADVICE if w in text]
    coverage = _coverage_violations(output, assessment)
    wording = _wording_violations(output, assessment)
    return OutputCheckResult(
        passed=not (numbers or banned or doses or advice or coverage or wording),
        number_fidelity_violations=numbers,
        banned_phrase_violations=banned,
        dosage_boundary_violations=doses + advice,
        coverage_violations=coverage,
        severity_wording_violations=wording,
    )


def _allowed_numbers(assessment: Assessment) -> set[float]:
    values: set[float] = set()
    for n in assessment.relevant_nutrients:
        values |= {n.peak_intake_from_supplements, n.average_intake_from_supplements, n.recommended_total_intake.value}
        if n.intake_from_drugs is not None:
            values.add(n.intake_from_drugs)
        if n.ul is not None:
            values |= {n.ul.ul_value, percent(n.ul.ratio), round(n.ul.ratio * 100, 1)}
    for f in assessment.interactions:
        values |= {t.separation_hours for t in f.triggers if t.separation_hours is not None}
    counts = Counter(f.severity for f in assessment.interactions)
    values |= {len(assessment.interactions), *counts.values()}
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


def _wording_violations(output: NarrationOutput, assessment: Assessment) -> list[str]:
    severity = {f.ingredient_code: f.severity for f in assessment.interactions}
    has_priority = Severity.PRIORITY in severity.values()
    violations = []
    for item in output.items:
        if item.kind is NarrationKind.SUMMARY:
            strong_allowed = has_priority
        elif item.kind is NarrationKind.INTERACTION:
            strong_allowed = severity.get(item.ingredient_code) is Severity.PRIORITY
        else:
            strong_allowed = False
        if not strong_allowed:
            violations += [f"{_label(item)}：{w}" for w in _STRONG_WORDS if w in item.text]
    return violations
