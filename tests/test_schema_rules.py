"""模型內建的約束：每一條都是規格裡寫死的規則，破了就該報錯。"""

import pytest
from pydantic import ValidationError

from app.schemas.api import JobResponse
from app.schemas.assessment import InteractionFinding
from app.schemas.case import AssessmentRequest, BasicProfile, BasicProfileSnapshot
from app.schemas.common import ExclusiveSelection
from app.schemas.enums import ConditionCode
from app.schemas.label import NutrientConfirmed, NutrientDraft, UserIntake, VerificationSubmission
from app.schemas.rules import Rule

VALID_RULE = {
    "rule_id": "R-0001", "condition_type": "drug_class", "condition_code": "ppi",
    "ingredient_code": "vitamin_b12", "interaction_type": "drug_affects_nutrient",
    "requires_supplement_intake": False, "severity": "attention",
    "requires_professional_review": False, "advice_code": "inform_provider",
    "reason_zh": "長期使用此類胃藥可能降低維生素B12的吸收", "citation_ids": ["c1"],
    "evidence_tier": "tbd", "status": "draft", "curated_by": "A",
}

TRIGGER = {
    "rule_id": "R-1", "condition_type": "drug_class", "condition_code": "ppi",
    "interaction_type": "drug_affects_nutrient", "advice_code": "inform_provider",
    "reason_zh": "說明", "citation_ids": ["c1"],
}


# ─── 強制作答 ───


def test_none_selected_excludes_other_choices():
    with pytest.raises(ValidationError):
        ExclusiveSelection[ConditionCode](selected=["hypertension"], none_selected=True)


def test_unanswered_selection_is_rejected():
    with pytest.raises(ValidationError):
        ExclusiveSelection[ConditionCode](selected=[], none_selected=False)


def test_under_19_is_rejected():
    with pytest.raises(ValidationError):
        BasicProfile(age=18, sex="male")


def test_age_band_must_match_age():
    with pytest.raises(ValidationError):
        BasicProfileSnapshot(age=72, sex="male", age_band="51-70")


def test_assessment_needs_at_least_one_product():
    with pytest.raises(ValidationError):
        AssessmentRequest(
            basic_profile={"age": 72, "sex": "male"},
            conditions={"none_selected": True},
            drugs={"none_selected": True},
            product_ids=[],
        )


# ─── 標示 ───


def test_in_scope_requires_standard_code():
    with pytest.raises(ValidationError):
        NutrientDraft(row_id="r1", raw_name="鐵", label_section="nutrition_table",
                      source_image_id="i1", scope_status="in_scope", standard_code=None)


def test_out_of_scope_must_not_carry_code():
    with pytest.raises(ValidationError):
        NutrientDraft(row_id="r1", raw_name="鐵", label_section="nutrition_table",
                      source_image_id="i1", scope_status="out_of_scope", standard_code="iron")


def test_target_nutrient_needs_amount_but_allowed_ingredient_does_not():
    with pytest.raises(ValidationError):
        NutrientConfirmed(row_id="r1", standard_code="iron", scope_status="in_scope")
    NutrientConfirmed(row_id="r1", standard_code="red_yeast_rice", scope_status="in_scope")


def test_duplicate_row_ids_rejected():
    row = {"row_id": "r1", "standard_code": "iron", "scope_status": "in_scope",
           "per_serving": 10, "unit": "mg"}
    with pytest.raises(ValidationError):
        VerificationSubmission(
            serving_info={"serving_size": 1, "dose_unit": "tablet"},
            user_intake={"frequency_type": "daily", "times_per_day": 1, "amount_per_time": 1},
            nutrients=[row, row],
        )


def test_weekly_frequency_requires_days_per_week():
    with pytest.raises(ValidationError):
        UserIntake(frequency_type="weekly_n_times", times_per_day=1, amount_per_time=1)


# ─── 規則表 ───


def test_valid_rule_passes():
    Rule(**VALID_RULE)


def test_drug_affects_nutrient_never_requires_supplement():
    with pytest.raises(ValidationError):
        Rule(**{**VALID_RULE, "requires_supplement_intake": True})


def test_reason_rejects_dose_numbers_but_allows_nutrient_names():
    with pytest.raises(ValidationError):
        Rule(**{**VALID_RULE, "reason_zh": "間隔 2 小時服用"})
    Rule(**{**VALID_RULE, "reason_zh": "影響維生素B12與Omega-3"})


def test_separation_hours_only_with_separate_timing():
    with pytest.raises(ValidationError):
        Rule(**{**VALID_RULE, "separation_hours": 2})


def test_reviewer_must_differ_from_curator():
    with pytest.raises(ValidationError):
        Rule(**{**VALID_RULE, "status": "reviewed", "reviewed_by": "A", "reviewed_at": "2026-10-01"})


# ─── 評估與 API ───


def test_aggregated_severity_must_be_the_highest():
    with pytest.raises(ValidationError):
        InteractionFinding(
            ingredient_code="magnesium", severity="info", requires_professional_review=False,
            user_has_supplement=False, matched_product_ids=[],
            triggers=[{**TRIGGER, "severity": "attention"}, {**TRIGGER, "severity": "info"}],
        )


def test_done_job_must_carry_result():
    with pytest.raises(ValidationError):
        JobResponse[dict](job_id="j1", status="done")


def test_unknown_field_is_rejected():
    with pytest.raises(ValidationError):
        BasicProfile(age=72, sex="male", height_cm=170)
