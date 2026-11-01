"""真的計算層 app/assessing.py：個案 → 應該得到的 finding 與數字。

10 個情境對應 docs/w3/narrator-cases/ 的 10 份範例；規則 id 以正式 data/catalog 為準。
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from app.assessing import assess
from app.calculator import RealCalculator
from app.catalog_source import get_catalog_source
from app.schemas.assessment import Assessment
from app.schemas.case import BasicProfileSnapshot, CaseProfile, SelectedDrug
from app.schemas.common import ExclusiveSelection
from app.schemas.enums import ElementalBasis, ULPhrasing
from app.schemas.label import VerificationSubmission

REF = get_catalog_source().load_reference()
AT = datetime(2026, 11, 1, tzinfo=UTC)
DRUG_ITEMS = {d.active_ingredient_code: d for d in REF.catalog.drug_items}
CALC = RealCalculator(REF)


def drug(code: str, **fields) -> SelectedDrug:
    item = DRUG_ITEMS[code]
    return SelectedDrug(
        raw_name=item.display_name_zh, scope_status="in_scope", active_ingredient_code=code,
        display_name_zh=item.display_name_zh, drug_class_codes=item.drug_class_codes, **fields,
    )  # fmt: skip


def row(code: str, per_serving: float | None = None, unit: str | None = "mg", **fields) -> dict:
    return {"row_id": f"r-{code}", "standard_code": code, "scope_status": "in_scope",
            "per_serving": per_serving, "unit": unit if per_serving is not None else None, **fields}  # fmt: skip


def product(*rows: dict, frequency="daily", times=1, amount=1, serving=1, **intake):
    submission = VerificationSubmission.model_validate({
        "product_name": "測試品",
        "serving_info": {"serving_size": serving, "dose_unit": "tablet"},
        "user_intake": {"frequency_type": frequency, "times_per_day": times, "amount_per_time": amount, **intake},
        "nutrients": list(rows),
    })  # fmt: skip
    return CALC.verify_product(uuid4(), submission, AT)


def make_case(products, drugs=(), conditions=("hypertension",), sex="female", age=45) -> CaseProfile:
    return CaseProfile(
        case_id=uuid4(), user_id=uuid4(), created_at=AT, decision_data_version=REF.version,
        basic_profile=BasicProfileSnapshot(age=age, sex=sex, age_band="31-50" if age <= 50 else "51-70"),
        conditions=ExclusiveSelection(selected=list(conditions), none_selected=not conditions),
        drugs=ExclusiveSelection(selected=list(drugs), none_selected=not drugs),
        supplements=list(products),
    )  # fmt: skip


def run(case: CaseProfile) -> Assessment:
    return assess(case, REF)


def codes(a: Assessment) -> list[str]:
    return [f.ingredient_code for f in a.interactions]


def nutrient(a: Assessment, code: str):
    return next(n for n in a.relevant_nutrients if n.nutrient_code == code)


# ─── 10 個情境 ───────────────────────────────────────────────


def test_01_full_example():
    p1 = product(row("calcium", 1500, nutrient_form_code="calcium_carbonate"), row("vitamin_d", 35, "ug"),
                 row("magnesium", 100), row("vitamin_b12", 6, "ug"))  # fmt: skip
    p2 = product({"row_id": "r1", "standard_code": "red_yeast_rice", "scope_status": "in_scope"})
    case = make_case([p1, p2], [drug("atorvastatin"), drug("hydrochlorothiazide"), drug("omeprazole"), drug("losartan")])
    a = run(case)
    # 有補的在前、其次沒補的（PPI 的鐵、thiazide 的鋅與鉀）；各組內依成分目錄順序。
    # ACEI/ARB 的鉀規則需要補鉀才觸發，這裡的鉀是 thiazide 規則帶出來的
    assert codes(a) == ["magnesium", "vitamin_d", "vitamin_b12", "red_yeast_rice", "iron", "zinc", "potassium"]
    assert [t.rule_id for t in a.interactions[0].triggers] == ["ppi-magnesium", "thiazide-magnesium"]
    assert nutrient(a, "calcium").peak_intake_from_supplements == pytest.approx(600.6)
    assert nutrient(a, "calcium").basis is ElementalBasis.ESTIMATED
    assert nutrient(a, "calcium").ul.ratio == pytest.approx(600.6 / 2500)
    assert nutrient(a, "vitamin_d").ul.phrasing is ULPhrasing.PERCENT_TOTAL_INTAKE
    assert nutrient(a, "vitamin_b12").ul is None
    assert nutrient(a, "magnesium").ul.phrasing is ULPhrasing.PERCENT_SUPPLEMENT_ONLY
    assert a.interactions[-1].requires_professional_review is True
    assert a.disclosures.drug_source_not_counted == ["calcium", "magnesium"]


def test_02_red_yeast_with_statin_only():
    case = make_case([product({"row_id": "r1", "standard_code": "red_yeast_rice", "scope_status": "in_scope"})],
                     [drug("atorvastatin")])  # fmt: skip
    a = run(case)
    [f] = a.interactions
    assert (f.ingredient_code, f.user_has_supplement, f.requires_professional_review) == ("red_yeast_rice", True, True)
    assert a.relevant_nutrients == []  # 允許成分不放 relevant_nutrients


def test_03_no_interaction():
    case = make_case([product(row("vitamin_c", 500), row("vitamin_e", 20, "iu"))], [drug("amlodipine")])
    a = run(case)
    assert a.interactions == []
    assert nutrient(a, "vitamin_c").ul.ratio == pytest.approx(0.25)
    assert nutrient(a, "vitamin_e").peak_intake_from_supplements == pytest.approx(13.4)
    assert nutrient(a, "vitamin_e").unit == "mg_ate"


def test_04_exceeded_supplement_only():
    case = make_case([product(row("magnesium", 400), row("zinc", 22))], [drug("omeprazole")])
    a = run(case)
    mg = nutrient(a, "magnesium")
    assert (mg.ul.exceeded, mg.ul.phrasing) == (True, ULPhrasing.EXCEEDED_SUPPLEMENT_ONLY)
    assert mg.ul.ratio == pytest.approx(400 / 350)
    assert nutrient(a, "zinc").ul.exceeded is False
    assert codes(a) == ["magnesium", "iron", "vitamin_b12"]  # PPI：有補鎂在前，鐵、B12 沒補也列


def test_05_exceeded_total_intake():
    case = make_case([product(row("vitamin_d", 125, "ug"), row("iron", 24))], [drug("amlodipine")])
    a = run(case)
    vd = nutrient(a, "vitamin_d")
    assert (vd.ul.exceeded, vd.ul.phrasing) == (True, ULPhrasing.EXCEEDED_TOTAL_INTAKE)
    assert vd.ul.ratio == pytest.approx(2.5)
    assert nutrient(a, "iron").ul.phrasing is ULPhrasing.PERCENT_SUPPLEMENT_ONLY


def test_06_drug_triggered_but_not_supplemented():
    case = make_case([product(row("vitamin_c", 500))], [drug("metformin")])
    a = run(case)
    [f] = a.interactions
    assert (f.ingredient_code, f.user_has_supplement, f.matched_product_ids) == ("vitamin_b12", False, [])
    b12 = nutrient(a, "vitamin_b12")
    assert (b12.is_supplemented, b12.triggered_by_drug, b12.peak_intake_from_supplements) == (False, True, 0)
    assert b12.ul is None and b12.basis is ElementalBasis.NOT_APPLICABLE


def test_07_antacid_dose_is_separate_from_supplements():
    case = make_case([product(row("iron", 18), row("magnesium", 50))],
                     [drug("magnesium_oxide", dose_mg=250, times_per_day=2)])  # fmt: skip
    a = run(case)
    mg = nutrient(a, "magnesium")
    assert mg.intake_from_drugs == pytest.approx(301.6)  # 150.8 × 2
    assert mg.peak_intake_from_supplements == 50  # 藥品來源不加進補充劑
    assert a.disclosures.drug_source_not_counted == ["iron"]  # 鎂有取得劑量，鐵沒有


def test_08_draft_and_retired_rules_are_ignored():
    case = make_case(
        [product({"row_id": "r1", "standard_code": "red_yeast_rice", "scope_status": "in_scope"},
                 {"row_id": "r2", "standard_code": "glucosamine", "scope_status": "in_scope"}, row("calcium", 500, nutrient_form_code="calcium_carbonate"))],  # fmt: skip
        [drug("simvastatin"), drug("glucosamine_sulfate"), drug("omeprazole")],
    )
    # glucosamine-rx-duplicate 是 draft、ppi-calcium 是 retired，都不能用
    found = codes(run(case))
    assert found[0] == "red_yeast_rice" and "calcium" not in found and "glucosamine" not in found


def test_09_many_nutrients_peak_vs_average_and_same_day_assumption():
    p = product(row("calcium", 1000, nutrient_form_code="calcium_carbonate"), row("zinc", 15),
                frequency="weekly_n_times", days_per_week=3, times=2, amount=1, serving=1)  # fmt: skip
    a = run(make_case([p], [drug("hydrochlorothiazide")]))
    ca = nutrient(a, "calcium")
    assert ca.peak_intake_from_supplements == pytest.approx(2 * 400.4)
    assert ca.average_intake_from_supplements == pytest.approx(2 * 400.4 * 3 / 7)
    assert ca.ul.ratio == pytest.approx(2 * 400.4 / 2500)  # 用峰值比對，不用平均
    assert a.disclosures.peak_same_day_assumption is True
    assert codes(a) == ["zinc", "magnesium", "potassium"]  # thiazide 的鋅（有補）、鎂、鉀；鈣沒有規則


def test_10_no_drugs_no_conditions():
    a = run(make_case([product(row("niacin", 50, "mg_ne"), row("vitamin_b6", 25))], drugs=(), conditions=()))
    assert a.interactions == []
    assert nutrient(a, "niacin").ul.exceeded is True
    d = a.disclosures
    assert (d.known_conditions_none, d.drugs_none, d.healthy_population_caveat) == (True, True, False)
    assert d.peak_same_day_assumption is False and d.drug_source_not_counted == []


# ─── 邊界 ───────────────────────────────────────────────────


def test_exactly_one_hundred_percent_is_exceeded():
    a = run(make_case([product(row("magnesium", 350))]))
    ul = nutrient(a, "magnesium").ul
    assert (ul.ratio, ul.exceeded) == (1.0, True)


def test_just_below_one_hundred_percent_is_not_exceeded():
    a = run(make_case([product(row("magnesium", 349.9))]))
    assert nutrient(a, "magnesium").ul.exceeded is False


def test_alternate_days_average_is_half_of_peak():
    a = run(make_case([product(row("vitamin_c", 1000), frequency="alternate_days")]))
    vc = nutrient(a, "vitamin_c")
    assert (vc.peak_intake_from_supplements, vc.average_intake_from_supplements) == (1000, 500)
    assert a.disclosures.peak_same_day_assumption is True


def test_as_needed_is_not_quantified():
    a = run(make_case([product(row("vitamin_c", 1000), frequency="as_needed")]))
    vc = nutrient(a, "vitamin_c")
    assert (vc.is_supplemented, vc.peak_intake_from_supplements, vc.ul) == (True, 0, None)


def test_only_allowed_ingredient_has_no_target_nutrient():
    a = run(make_case([product({"row_id": "r1", "standard_code": "omega_3", "scope_status": "in_scope"})]))
    assert a.relevant_nutrients == [] and a.interactions == []


def test_unknown_amount_is_excluded_from_sum_and_disclosed():
    known = product(row("calcium", 500, nutrient_form_code="calcium_carbonate"))
    unknown = product(row("calcium", 500, nutrient_form_code="seaweed_calcium"))
    a = run(make_case([known, unknown]))
    assert nutrient(a, "calcium").peak_intake_from_supplements == pytest.approx(200.2)
    assert [u.nutrient_code for u in a.disclosures.undetermined_amounts] == ["calcium"]


def test_amounts_are_summed_across_products_and_estimated_wins():
    stated = product(row("magnesium", 100))
    estimated = product(row("magnesium", 200, nutrient_form_code="magnesium_oxide"))
    mg = nutrient(run(make_case([stated, estimated])), "magnesium")
    assert mg.peak_intake_from_supplements == pytest.approx(100 + 200 * 0.603)
    assert mg.basis is ElementalBasis.ESTIMATED


def test_out_of_scope_drug_does_not_trigger_rules():
    omeprazole = drug("omeprazole")
    out = SelectedDrug(raw_name="未知藥", scope_status="out_of_scope")
    unresolved = SelectedDrug(raw_name="看不懂", scope_status="unresolved")
    a = run(make_case([product(row("magnesium", 50))], [out, unresolved]))
    assert a.interactions == []
    assert a.disclosures.out_of_scope_drugs == ["未知藥"] and a.disclosures.unresolved_drugs == ["看不懂"]
    assert codes(run(make_case([product(row("magnesium", 50))], [omeprazole]))) == ["magnesium", "iron", "vitamin_b12"]


def test_multiple_products_matched_in_finding():
    p1, p2 = product(row("magnesium", 50)), product(row("magnesium", 60))
    f = next(f for f in run(make_case([p1, p2], [drug("omeprazole")])).interactions if f.ingredient_code == "magnesium")
    assert f.matched_product_ids == [p1.product_id, p2.product_id]


def test_ordering_supplemented_first_then_catalog_order():
    a = run(make_case([product(row("zinc", 10))], [drug("metformin"), drug("hydrochlorothiazide")]))
    # 鋅（有補）在前；其餘沒補的依成分目錄順序：鎂、鉀、維生素 D 需補充才觸發，所以只剩 B12
    assert codes(a) == ["zinc", "magnesium", "potassium", "vitamin_b12"]
    assert [f.user_has_supplement for f in a.interactions] == [True, False, False, False]


def test_healthy_population_caveat_follows_conditions():
    assert run(make_case([product(row("zinc", 10))], conditions=("t2dm",))).disclosures.healthy_population_caveat


def test_dris_depend_on_sex():
    male = nutrient(run(make_case([product(row("iron", 10))], sex="male")), "iron")
    female = nutrient(run(make_case([product(row("iron", 10))], sex="female")), "iron")
    assert male.recommended_total_intake.value != female.recommended_total_intake.value


def test_different_products_give_different_assessments():
    a = run(make_case([product(row("zinc", 10))]))
    b = run(make_case([product(row("zinc", 40))]))
    assert nutrient(a, "zinc").ul.ratio != nutrient(b, "zinc").ul.ratio


def test_case_and_version_are_carried_over():
    case = make_case([product(row("zinc", 10))])
    a = run(case)
    assert (a.case_id, a.decision_data_version) == (case.case_id, REF.version)
    assert isinstance(a.case_id, UUID)
