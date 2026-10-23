import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.catalog_source import get_catalog_source
from app.extraction.engines.openrouter import Route
from app.narration_check import check_narration
from app.narration_template import TEMPLATE_MODEL, template_narration
from app.narrator import NarratorError, OpenRouterNarrator
from app.reporting import MAX_RETRIES, NarratedReporter, condition_names, narrate
from app.schemas.assessment import Assessment
from app.schemas.case import CaseProfile
from app.schemas.enums import IngredientCode, NarrationKind, Severity
from app.schemas.narration import BANNED_PHRASES, NarrationInput, NarrationOutput

EXAMPLES = Path(__file__).parent.parent / "docs" / "schemas" / "examples"
GENERATED_AT = datetime(2026, 10, 23, 9, 0, tzinfo=UTC)


@pytest.fixture
def case() -> CaseProfile:
    return CaseProfile.model_validate_json((EXAMPLES / "case_profile.json").read_text(encoding="utf-8"))


@pytest.fixture
def assessment() -> Assessment:
    return Assessment.model_validate_json((EXAMPLES / "06_assessment.json").read_text(encoding="utf-8"))


@pytest.fixture
def names() -> dict[IngredientCode, str]:
    return {i.code: i.display_name_zh for i in get_catalog_source().load().ingredients}


@pytest.fixture
def conditions() -> dict[str, str]:
    return condition_names(get_catalog_source().load())


def _llm_output(assessment: Assessment, **overrides: str) -> NarrationOutput:
    """一份會通過檢查的 LLM 輸出；overrides 以 "summary" 或成分代碼替換文字。"""
    items = [{"kind": "summary", "ingredient_code": None, "text": overrides.get("summary", "請先看紅麴這一條。")}]
    items += [
        {"kind": "interaction", "ingredient_code": f.ingredient_code, "text": overrides.get(f.ingredient_code, "請留意。")}
        for f in assessment.interactions
    ]
    return NarrationOutput.model_validate({"items": items, "model": "fake-llm", "prompt_version": "test"})


class FakeNarrator:
    def __init__(self, outputs: list[NarrationOutput | Exception]) -> None:
        self._outputs = outputs
        self.calls = 0

    def narrate(self, request: NarrationInput, names: dict[IngredientCode, str]) -> NarrationOutput:
        result = self._outputs[min(self.calls, len(self._outputs) - 1)]
        self.calls += 1
        if isinstance(result, Exception):
            raise result
        return result


# ── 固定模板報告 ─────────────────────────────────────────────


def test_template_report_is_complete_without_llm(case, assessment):
    report = NarratedReporter(get_catalog_source(), narrator=None).build(case, assessment, GENERATED_AT)
    assert report.narration_model == TEMPLATE_MODEL
    assert report.case_id == case.case_id
    assert report.summary
    assert all(i.narration for i in report.interactions)
    assert [d.raw_name for d in report.profile.drugs] == [d.raw_name for d in case.drugs.selected]
    assert [p.product_id for p in report.products] == [p.product_id for p in case.supplements]


def test_template_report_expands_names_and_citations(case, assessment):
    report = NarratedReporter(get_catalog_source(), narrator=None).build(case, assessment, GENERATED_AT)
    red_yeast = next(i for i in report.interactions if i.ingredient_code is IngredientCode.RED_YEAST_RICE)
    assert red_yeast.display_name_zh == "紅麴"
    [trigger] = red_yeast.triggers
    assert trigger.condition_display_name_zh == "Statin 類降血脂藥"
    assert [c.citation_id for c in trigger.citations] == trigger.citation_ids


def test_template_report_has_no_banned_phrases(case, assessment):
    report = NarratedReporter(get_catalog_source(), narrator=None).build(case, assessment, GENERATED_AT)
    text = report.model_dump_json()
    assert not [p for p in (*BANNED_PHRASES, "未發現") if p in text]


def test_template_report_is_deterministic(case, assessment):
    reporter = NarratedReporter(get_catalog_source(), narrator=None)
    first = reporter.build(case, assessment, GENERATED_AT).model_dump(exclude={"report_id"})
    second = reporter.build(case, assessment, GENERATED_AT).model_dump(exclude={"report_id"})
    assert first == second


def test_template_summary_names_top_priority_and_counts(assessment, names, conditions):
    summary = template_narration(assessment, names, conditions).items[0].text
    assert "紅麴" in summary
    assert f"這次共有 {len(assessment.interactions)} 項提醒" in summary


def test_template_without_findings_still_has_caveat(assessment, names, conditions):
    empty = assessment.model_copy(update={"interactions": []})
    summary = template_narration(empty, names, conditions).items[0].text
    assert "不等於一定適合你" in summary


def test_template_marks_drug_only_finding(assessment, names, conditions):
    texts = {i.ingredient_code: i.text for i in template_narration(assessment, names, conditions).items}
    assert texts[IngredientCode.POTASSIUM].startswith("你沒有補充鉀")


def test_template_names_drug_class_for_each_rule(assessment, names, conditions):
    texts = {i.ingredient_code: i.text for i in template_narration(assessment, names, conditions).items}
    assert "Thiazide 類利尿劑：" in texts[IngredientCode.CALCIUM]
    assert "質子幫浦抑制劑（PPI）：" in texts[IngredientCode.CALCIUM]


def test_template_passes_output_check(assessment, names, conditions):
    result = check_narration(template_narration(assessment, names, conditions), assessment)
    assert result.passed, result


def test_unknown_citation_is_an_error(case, assessment):
    finding = assessment.interactions[0]
    trigger = finding.triggers[0].model_copy(update={"citation_ids": ["cit-9999"]})
    broken = assessment.model_copy(
        update={"interactions": [finding.model_copy(update={"triggers": [trigger]}), *assessment.interactions[1:]]}
    )
    with pytest.raises(ValueError, match="cit-9999"):
        NarratedReporter(get_catalog_source(), narrator=None).build(case, broken, GENERATED_AT)


# ── 輸出檢查 ─────────────────────────────────────────────────


def test_check_passes_valid_llm_output(assessment):
    assert check_narration(_llm_output(assessment), assessment).passed


def test_check_flags_number_not_in_assessment(assessment):
    result = check_narration(_llm_output(assessment, summary="鈣已達上限的 99%。"), assessment)
    assert not result.passed
    assert result.number_fidelity_violations == ["summary：99"]


def test_check_allows_numbers_from_assessment_and_names(assessment):
    vitamin_d = next(n for n in assessment.relevant_nutrients if n.nutrient_code is IngredientCode.VITAMIN_D)
    pct = round(vitamin_d.ul.ratio * 100)
    text = f"維生素D3已達上限的{pct}%，B12、Omega-3 與 COX-2 只是名稱。"
    assert check_narration(_llm_output(assessment, summary=text), assessment).passed


def test_check_flags_banned_phrase(assessment):
    result = check_narration(_llm_output(assessment, summary="這樣吃很安全。"), assessment)
    assert result.banned_phrase_violations == ["summary：安全"]


def test_check_flags_dose_and_stop_advice(assessment):
    result = check_narration(_llm_output(assessment, red_yeast_rice="建議停用紅麴，或改成 600 mg。"), assessment)
    assert "interaction.red_yeast_rice：600 mg" in result.dosage_boundary_violations
    assert "interaction.red_yeast_rice：停用" in result.dosage_boundary_violations


def test_check_flags_missing_and_extra_interactions(assessment):
    output = _llm_output(assessment)
    items = [i for i in output.items if i.ingredient_code is not IngredientCode.POTASSIUM]
    items.append(items[-1].model_copy(update={"ingredient_code": IngredientCode.ZINC}))
    result = check_narration(output.model_copy(update={"items": items}), assessment)
    assert result.coverage_violations == ["interaction.potassium：缺少敘述", "interaction.zinc：判定層沒有這條提醒"]


def test_check_flags_strong_words_below_priority(assessment):
    info = next(f for f in assessment.interactions if f.severity is Severity.INFO)
    result = check_narration(_llm_output(assessment, **{info.ingredient_code: "請立即就醫。"}), assessment)
    assert result.severity_wording_violations == [f"interaction.{info.ingredient_code}：立即"]


def test_check_allows_strong_words_for_priority(assessment):
    assert check_narration(_llm_output(assessment, red_yeast_rice="請立即和醫師討論。"), assessment).passed


# ── LLM 重試與備援 ───────────────────────────────────────────


def test_narrate_without_llm_uses_template(assessment, names, conditions):
    assert narrate(None, assessment, names, conditions, []).model == TEMPLATE_MODEL


def test_narrate_retries_until_check_passes(assessment, names, conditions):
    bad = _llm_output(assessment, summary="很安全。")
    narrator = FakeNarrator([bad, bad, _llm_output(assessment)])
    output = narrate(narrator, assessment, names, conditions, [])
    assert output.model == "fake-llm"
    assert narrator.calls == 3


def test_narrate_falls_back_to_template_after_retries(assessment, names, conditions):
    narrator = FakeNarrator([_llm_output(assessment, summary="很安全。")])
    assert narrate(narrator, assessment, names, conditions, []).model == TEMPLATE_MODEL
    assert narrator.calls == MAX_RETRIES + 1


def test_narrate_falls_back_when_llm_errors(assessment, names, conditions):
    narrator = FakeNarrator([NarratorError("逾時")])
    assert narrate(narrator, assessment, names, conditions, []).model == TEMPLATE_MODEL
    assert narrator.calls == MAX_RETRIES + 1


def test_report_records_llm_model_and_prompt_version(case, assessment):
    reporter = NarratedReporter(get_catalog_source(), FakeNarrator([_llm_output(assessment)]))
    report = reporter.build(case, assessment, GENERATED_AT)
    assert (report.narration_model, report.prompt_version) == ("fake-llm", "test")
    assert report.summary == "請先看紅麴這一條。"


# ── OpenRouter 轉接 ──────────────────────────────────────────


def _transport(content: str):
    sent = []

    def send(body, timeout):
        sent.append(body)
        return {"choices": [{"message": {"content": content}}]}

    return send, sent


def test_openrouter_narrator_parses_response(assessment, names):
    expected = _llm_output(assessment)
    send, sent = _transport(json.dumps({"items": [i.model_dump(mode="json") for i in expected.items]}))
    narrator = OpenRouterNarrator(send, Route("vendor/model-1", "vendor"))
    output = narrator.narrate(NarrationInput(assessment=assessment, citations=[]), names)
    assert output.model == "vendor/model-1"
    assert [i.kind for i in output.items][0] is NarrationKind.SUMMARY
    assert sent[0]["provider"] == {"only": ["vendor"], "allow_fallbacks": False}


def test_openrouter_narrator_bad_json_is_narrator_error(assessment, names):
    send, _ = _transport("不是 JSON")
    narrator = OpenRouterNarrator(send, Route("vendor/model-1", "vendor"))
    with pytest.raises(NarratorError):
        narrator.narrate(NarrationInput(assessment=assessment, citations=[]), names)


def test_openrouter_narrator_network_error_is_narrator_error(assessment, names):
    def send(body, timeout):
        raise TimeoutError("超過等待時間上限")

    narrator = OpenRouterNarrator(send, Route("vendor/model-1", "vendor"))
    with pytest.raises(NarratorError):
        narrator.narrate(NarrationInput(assessment=assessment, citations=[]), names)
