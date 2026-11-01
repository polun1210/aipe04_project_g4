"""真的計算層：凍結的 CaseProfile ＋ ReferenceData → Assessment。

純函式，不碰資料庫、不呼叫模型。判定規則見 docs/schemas/rule-table.md 第七、八節，
以及 ADR-0002、0004、0005、0007、0012。數值加總與比對用 Fraction，輸出才轉 float。

  1. 加總   同一營養素跨產品加總（只算 in_scope 且含量可判定的列），峰值與平均分開加
  2. 上限   依性別、年齡組查 DRIs；比例 ＝ 補充劑峰值 ÷ UL，恰好 100% 算超過
  3. 藥物   需要劑量的制酸劑另外算 intake_from_drugs，不加進補充劑的加總
  4. 規則   只用 reviewed；同一成分的多條規則合成一筆 InteractionFinding
  5. 揭露   照 rule-table.md「報告固定揭露的內容」逐項產生
"""

from dataclasses import dataclass, field
from fractions import Fraction
from uuid import UUID

from app.schemas.assessment import (
    Assessment,
    Disclosures,
    InteractionFinding,
    RecommendedIntake,
    RelevantNutrient,
    Trigger,
    ULComparison,
    UndeterminedAmount,
)
from app.schemas.case import CaseProfile, SelectedDrug
from app.schemas.catalog import DrisValue, Ingredient
from app.schemas.enums import (
    TARGET_NUTRIENTS,
    ConditionCode,
    ConditionType,
    ElementalBasis,
    FrequencyType,
    IngredientCategory,
    RuleStatus,
    ScopeStatus,
    ULPhrasing,
    ULScope,
)
from app.schemas.label import VerifiedProduct
from app.schemas.reference import ReferenceData
from app.schemas.rules import Rule

# 藥品劑量只取得含鈣／含鎂制酸劑；其餘這幾項不計入藥品來源，報告必須揭露
_DRUG_SOURCE_NUTRIENTS = ("calcium", "magnesium", "iron")

_PHRASING = {
    (ULScope.SUPPLEMENT_ONLY, True): ULPhrasing.EXCEEDED_SUPPLEMENT_ONLY,
    (ULScope.SUPPLEMENT_ONLY, False): ULPhrasing.PERCENT_SUPPLEMENT_ONLY,
    (ULScope.TOTAL_INTAKE, True): ULPhrasing.EXCEEDED_TOTAL_INTAKE,
    (ULScope.TOTAL_INTAKE, False): ULPhrasing.PERCENT_TOTAL_INTAKE,
}


class MissingReferenceError(LookupError):
    """參考資料缺了評估必需的值（例如某營養素沒有這個性別、年齡組的 DRIs）。"""


@dataclass
class _Total:
    peak: Fraction = Fraction(0)
    average: Fraction = Fraction(0)
    bases: set[ElementalBasis] = field(default_factory=set)
    supplemented: bool = False

    @property
    def quantified(self) -> bool:
        return bool(self.bases)


def assess(case: CaseProfile, ref: ReferenceData) -> Assessment:
    ingredients = ref.catalog.ingredients
    order = {i.code: n for n, i in enumerate(ingredients)}
    totals = _supplement_totals(case.supplements)
    drug_intake = _drug_intakes(case.drugs.selected, ref)
    findings = _interactions(case, ref, order)
    triggered = {f.ingredient_code for f in findings if f.ingredient_code in TARGET_NUTRIENTS}
    return Assessment(
        case_id=case.case_id,
        decision_data_version=case.decision_data_version,
        relevant_nutrients=_relevant_nutrients(case, ref, totals, drug_intake, triggered),
        interactions=findings,
        disclosures=_disclosures(case, ref, drug_intake),
    )


# ─── 1. 加總 ────────────────────────────────────────────────


def _supplement_totals(products: list[VerifiedProduct]) -> dict[str, _Total]:
    totals: dict[str, _Total] = {}
    for product in products:
        for row in product.nutrients:
            if row.scope_status is not ScopeStatus.IN_SCOPE or row.standard_code not in TARGET_NUTRIENTS:
                continue
            total = totals.setdefault(row.standard_code, _Total())
            total.supplemented = True
            if row.elemental_basis is ElementalBasis.UNKNOWN or row.peak_daily_amount is None:
                continue  # 含量無法判定或不可量化（as_needed）：不加總
            total.peak += Fraction(str(row.peak_daily_amount))
            total.average += Fraction(str(row.average_daily_amount or 0))
            total.bases.add(row.elemental_basis)
    return totals


def _basis_of(total: _Total | None) -> ElementalBasis:
    """任一來源是 estimated 就是 estimated（報告寫「推估」）；其次是標示值。"""
    if total is None or not total.supplemented:
        return ElementalBasis.NOT_APPLICABLE
    for basis in (ElementalBasis.ESTIMATED, ElementalBasis.LABEL_STATED, ElementalBasis.NOT_APPLICABLE):
        if basis in total.bases:
            return basis
    return ElementalBasis.UNKNOWN


# ─── 3. 藥物來源 ────────────────────────────────────────────


def _drug_intakes(drugs: list[SelectedDrug], ref: ReferenceData) -> dict[str, Fraction]:
    """需要劑量的藥（制酸劑類）→ 各營養素每日元素量（mg）。分開呈現，不加進補充劑。"""
    needs_dose = {d.active_ingredient_code for d in ref.catalog.drug_items if d.requires_dose}
    result: dict[str, Fraction] = {}
    for drug in drugs:
        if drug.scope_status is not ScopeStatus.IN_SCOPE or drug.active_ingredient_code not in needs_dose:
            continue
        if drug.dose_mg is None or drug.times_per_day is None:
            continue
        for row in ref.catalog.drug_nutrient_doses:
            if row.active_ingredient_code != drug.active_ingredient_code:
                continue
            per_dose = Fraction(str(row.elemental_mg_per_unit)) * Fraction(str(drug.dose_mg)) / Fraction(str(row.dose_option_mg))
            result[row.nutrient_code] = result.get(row.nutrient_code, Fraction(0)) + per_dose * drug.times_per_day
    return result


# ─── 2. 建議量與上限 ────────────────────────────────────────


def _dris_of(case: CaseProfile, ref: ReferenceData) -> dict[str, DrisValue]:
    profile = case.basic_profile
    return {v.nutrient_code: v for v in ref.dris_values if v.sex is profile.sex and v.age_band is profile.age_band}


def _relevant_nutrients(
    case: CaseProfile,
    ref: ReferenceData,
    totals: dict[str, _Total],
    drug_intake: dict[str, Fraction],
    triggered: set[str],
) -> list[RelevantNutrient]:
    dris = _dris_of(case, ref)
    result = []
    for ingredient in ref.catalog.ingredients:
        code = ingredient.code
        if ingredient.category is not IngredientCategory.TARGET_NUTRIENT:
            continue  # 允許成分只判有沒有，不放這裡
        total = totals.get(code)
        supplemented = total is not None and total.supplemented
        from_drug = drug_intake.get(code)
        triggered_by_drug = code in triggered or from_drug is not None
        if not (supplemented or triggered_by_drug):
            continue
        if code not in dris:
            raise MissingReferenceError(f"DRIs 沒有 {code}／{case.basic_profile.sex}／{case.basic_profile.age_band}")
        result.append(_nutrient(ingredient, dris[code], total, from_drug, supplemented, triggered_by_drug))
    return result


def _nutrient(
    ingredient: Ingredient,
    dris: DrisValue,
    total: _Total | None,
    from_drug: Fraction | None,
    supplemented: bool,
    triggered_by_drug: bool,
) -> RelevantNutrient:
    peak = total.peak if total else Fraction(0)
    average = total.average if total else Fraction(0)
    return RelevantNutrient(
        nutrient_code=ingredient.code,
        is_supplemented=supplemented,
        triggered_by_drug=triggered_by_drug,
        peak_intake_from_supplements=float(peak),
        average_intake_from_supplements=float(average),
        intake_from_drugs=float(from_drug) if from_drug is not None else None,
        unit=dris.unit,
        basis=_basis_of(total),
        recommended_total_intake=RecommendedIntake(reference_type=dris.reference_type, value=dris.reference_value),
        ul=_ul_comparison(ingredient, dris, peak) if total is not None and total.quantified else None,
    )


def _ul_comparison(ingredient: Ingredient, dris: DrisValue, peak: Fraction) -> ULComparison | None:
    """UL 為空（鉀、B12）不做數值比對；沒有任何可量化來源時也不比（避免寫出「0%」）。"""
    if dris.ul_value is None or ingredient.ul_scope is None:
        return None
    ratio = peak / Fraction(str(dris.ul_value))
    exceeded = ratio >= 1  # 剛好 100% 算超過
    return ULComparison(
        ul_value=dris.ul_value,
        ratio=float(ratio),
        exceeded=exceeded,
        scope=ingredient.ul_scope,
        phrasing=_PHRASING[(ingredient.ul_scope, exceeded)],
    )


# ─── 4. 規則比對 ────────────────────────────────────────────


def _interactions(case: CaseProfile, ref: ReferenceData, order: dict[str, int]) -> list[InteractionFinding]:
    drugs = [d for d in case.drugs.selected if d.scope_status is ScopeStatus.IN_SCOPE]
    active_classes = {c for d in drugs for c in d.drug_class_codes}
    active_ingredients = {d.active_ingredient_code for d in drugs}

    hits: dict[str, list[tuple[Rule, list[UUID]]]] = {}
    for rule in ref.rules:
        if rule.status is not RuleStatus.REVIEWED or not _condition_active(rule, active_classes, active_ingredients):
            continue
        matched = _matched_products(case.supplements, rule)
        if rule.requires_supplement_intake and not matched:
            continue
        hits.setdefault(rule.ingredient_code, []).append((rule, matched))

    findings = [_finding(code, entries, case.supplements) for code, entries in hits.items()]
    # 使用者手上有東西可以處理的在前，同組內依成分目錄順序（ADR-0012）
    return sorted(findings, key=lambda f: (not f.user_has_supplement, order[f.ingredient_code]))


def _condition_active(rule: Rule, classes: set[str], ingredients: set[str | None]) -> bool:
    if rule.condition_type is ConditionType.DRUG_CLASS:
        return rule.condition_code in classes
    return rule.condition_code in ingredients


def _matched_products(products: list[VerifiedProduct], rule: Rule) -> list[UUID]:
    """有這個成分、且符合規則限定型態的產品（空 ＝ 所有型態）。只看 in_scope 的列。"""
    forms = set(rule.ingredient_form_codes)
    return [
        p.product_id
        for p in products
        if any(
            n.scope_status is ScopeStatus.IN_SCOPE
            and n.standard_code == rule.ingredient_code
            and (not forms or n.nutrient_form_code in forms)
            for n in p.nutrients
        )
    ]


def _finding(code: str, entries: list[tuple[Rule, list[UUID]]], products: list[VerifiedProduct]) -> InteractionFinding:
    matched_ids = {pid for _, ids in entries for pid in ids}
    triggers = [_trigger(rule) for rule, _ in entries]
    return InteractionFinding(
        ingredient_code=code,
        requires_professional_review=any(t.requires_professional_review for t in triggers),
        user_has_supplement=bool(matched_ids),
        matched_product_ids=[p.product_id for p in products if p.product_id in matched_ids],
        triggers=triggers,
    )


def _trigger(rule: Rule) -> Trigger:
    return Trigger(
        rule_id=rule.rule_id,
        condition_type=rule.condition_type,
        condition_code=rule.condition_code,
        interaction_type=rule.interaction_type,
        advice_code=rule.advice_code,
        requires_professional_review=rule.requires_professional_review,
        separation_hours=rule.separation_hours,
        reason_zh=rule.reason_zh,
        citation_ids=list(rule.citation_ids),
    )


# ─── 5. 揭露 ────────────────────────────────────────────────


def undetermined_amounts(case: CaseProfile) -> list[UndeterminedAmount]:
    """13 項目標營養素裡，含量無法判定（elemental_basis = unknown）的成分列。

    紅麴、葡萄糖胺、魚油這類允許成分只判有沒有、本來就沒有含量，不算。
    """
    return [
        UndeterminedAmount(product_id=p.product_id, row_id=n.row_id, raw_name=n.raw_name, nutrient_code=n.standard_code)
        for p in case.supplements
        for n in p.nutrients
        if n.standard_code in TARGET_NUTRIENTS and n.elemental_basis is ElementalBasis.UNKNOWN
    ]


def _disclosures(case: CaseProfile, ref: ReferenceData, drug_intake: dict[str, Fraction]) -> Disclosures:
    rows = [(n, p) for p in case.supplements for n in p.nutrients]
    drugs = case.drugs.selected
    has_in_scope_drug = any(d.scope_status is ScopeStatus.IN_SCOPE for d in drugs)
    present = {n.standard_code for n, _ in rows if n.scope_status is ScopeStatus.IN_SCOPE}
    return Disclosures(
        covered_known_conditions=list(ConditionCode),
        covered_drug_classes=[c.drug_class_code for c in ref.catalog.drug_classes],
        covered_nutrients=[i.code for i in ref.catalog.ingredients if i.category is IngredientCategory.TARGET_NUTRIENT],
        known_conditions_none=case.conditions.none_selected,
        drugs_none=case.drugs.none_selected,
        healthy_population_caveat=bool(case.conditions.selected),
        peak_same_day_assumption=any(p.user_intake.frequency_type is not FrequencyType.DAILY for p in case.supplements),
        out_of_scope_ingredients=_names(rows, ScopeStatus.OUT_OF_SCOPE),
        unresolved_ingredients=_names(rows, ScopeStatus.UNRESOLVED),
        out_of_scope_drugs=[d.raw_name for d in drugs if d.scope_status is ScopeStatus.OUT_OF_SCOPE],
        unresolved_drugs=[d.raw_name for d in drugs if d.scope_status is ScopeStatus.UNRESOLVED],
        # 有用藥的人，鈣、鎂、鐵只要出現在補充劑裡，除了取得劑量的制酸劑之外都沒有算進藥品來源
        drug_source_not_counted=[
            code for code in _DRUG_SOURCE_NUTRIENTS if has_in_scope_drug and code in present and code not in drug_intake
        ],
        undetermined_amounts=undetermined_amounts(case),
    )


def _names(rows, status: ScopeStatus) -> list[str]:
    """raw_name 去重、保留出現順序；沒有原文的列（使用者新增）略過。"""
    return list(dict.fromkeys(n.raw_name for n, _ in rows if n.scope_status is status and n.raw_name))
