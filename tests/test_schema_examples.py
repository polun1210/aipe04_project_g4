"""範例檔必須永遠通過 Pydantic 驗證：結構改了、範例沒跟著改，這裡就會紅。"""

import json
from pathlib import Path

import pytest
from pydantic import BaseModel, TypeAdapter

from app.schemas import catalog, rules
from app.schemas.api import ErrorResponse, JobResponse
from app.schemas.assessment import Assessment
from app.schemas.case import AssessmentRequest, CaseProfile
from app.schemas.csv_io import load_csv
from app.schemas.label import ExtractionAccepted, ExtractionDraft, LabelCorrection, VerificationSubmission
from app.schemas.narration import BANNED_PHRASES, NarrationOutput
from app.schemas.report import Report

EXAMPLES = Path(__file__).parent.parent / "docs" / "schemas" / "examples"

JSON_EXAMPLES: dict[str, TypeAdapter] = {
    "03_assessment_request.json": TypeAdapter(AssessmentRequest),
    "04a_extraction_accepted.json": TypeAdapter(ExtractionAccepted),
    "04b_extraction_job_done.json": TypeAdapter(JobResponse[ExtractionDraft]),
    "05a_verification_submission.json": TypeAdapter(VerificationSubmission),
    "05b_label_corrections.json": TypeAdapter(list[LabelCorrection]),
    "case_profile.json": TypeAdapter(CaseProfile),
    "06_assessment.json": TypeAdapter(Assessment),
    "07_narration_output.json": TypeAdapter(NarrationOutput),
    "08_report.json": TypeAdapter(Report),
    "api_error.json": TypeAdapter(ErrorResponse),
}

CSV_EXAMPLES: dict[str, type[BaseModel]] = {
    "known_conditions.csv": catalog.KnownCondition,
    "drug_classes.csv": catalog.DrugClass,
    "drug_items.csv": catalog.DrugItem,
    "drug_nutrient_doses.csv": catalog.DrugNutrientDose,
    "ingredients.csv": catalog.Ingredient,
    "out_of_scope_names.csv": catalog.OutOfScopeName,
    "dris_values.csv": catalog.DrisValue,
    "compound_ratios.csv": catalog.CompoundRatio,
    "conversion_factors.csv": catalog.ConversionFactor,
    "rules.csv": rules.Rule,
    "citations.csv": rules.Citation,
}


def test_every_example_file_is_registered():
    on_disk = {p.name for p in EXAMPLES.glob("*.json")} | {
        p.name for p in (EXAMPLES / "catalog").glob("*.csv")
    }
    assert on_disk == set(JSON_EXAMPLES) | set(CSV_EXAMPLES)


@pytest.mark.parametrize("filename", JSON_EXAMPLES)
def test_json_example_validates(filename):
    raw = (EXAMPLES / filename).read_text(encoding="utf-8")
    JSON_EXAMPLES[filename].validate_json(raw)


@pytest.mark.parametrize("filename", CSV_EXAMPLES)
def test_csv_example_validates(filename):
    rows = load_csv(EXAMPLES / "catalog" / filename, CSV_EXAMPLES[filename])
    assert rows


def test_catalog_covers_full_v1_scope():
    ingredients = load_csv(EXAMPLES / "catalog" / "ingredients.csv", catalog.Ingredient)
    classes = load_csv(EXAMPLES / "catalog" / "drug_classes.csv", catalog.DrugClass)
    conditions = load_csv(EXAMPLES / "catalog" / "known_conditions.csv", catalog.KnownCondition)
    assert len({i.code for i in ingredients}) == 16
    assert len({c.drug_class_code for c in classes}) == 16
    assert len({c.condition_code for c in conditions}) == 5


def test_rule_citations_exist():
    rule_rows = load_csv(EXAMPLES / "catalog" / "rules.csv", rules.Rule)
    citation_ids = {c.citation_id for c in load_csv(EXAMPLES / "catalog" / "citations.csv", rules.Citation)}
    for rule in rule_rows:
        assert set(rule.citation_ids) <= citation_ids, rule.rule_id


def test_narration_example_has_no_banned_phrases():
    output = NarrationOutput.model_validate_json(
        (EXAMPLES / "07_narration_output.json").read_text(encoding="utf-8")
    )
    for item in output.items:
        assert not [p for p in BANNED_PHRASES if p in item.text], item.text


def test_report_numbers_match_assessment():
    assessment = json.loads((EXAMPLES / "06_assessment.json").read_text(encoding="utf-8"))
    report = json.loads((EXAMPLES / "08_report.json").read_text(encoding="utf-8"))
    assert [n["peak_intake_from_supplements"] for n in report["nutrients"]] == [
        n["peak_intake_from_supplements"] for n in assessment["relevant_nutrients"]
    ]
    assert [f["severity"] for f in report["interactions"]] == [
        f["severity"] for f in assessment["interactions"]
    ]
