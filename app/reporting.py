"""報告產生：評估結果（判定層）＋ 顯示用名稱 ＋ 展開的出處 ＋ 通過檢查的敘述 → 08_report。

這一層不做任何判斷或計算：等級、數字、觸發哪條規則都照抄 Assessment。
敘述先交給 LLM（有設定的話），輸出檢查不合格重試最多 2 次，仍不合格改用固定模板；
沒設定 LLM 就直接用固定模板，所以不接 LLM 也能產出完整報告。
"""

import logging
from collections.abc import Sequence
from datetime import datetime
from functools import lru_cache
from typing import Protocol
from uuid import uuid4

from app.catalog_source import CatalogSource, get_catalog_source
from app.narration_check import check_narration
from app.narration_evidence import EvidenceSource, get_evidence_source, safe_retrieve
from app.narration_template import template_narration
from app.narrator import Narrator, NarratorError, get_narrator
from app.schemas.assessment import Assessment, Trigger
from app.schemas.case import CaseProfile
from app.schemas.catalog import CatalogResponse
from app.schemas.enums import IngredientCode, NarrationKind
from app.schemas.narration import NarrationEvidence, NarrationInput, NarrationOutput
from app.schemas.report import (
    Report,
    ReportFootnote,
    ReportCondition,
    ReportDrug,
    ReportInteraction,
    ReportNutrient,
    ReportProduct,
    ReportProfile,
    ReportTrigger,
)
from app.schemas.rules import Citation

MAX_RETRIES = 2
EXCERPT_LENGTH = 500
SOURCE_NAMES = {
    "nih_ods": "美國國家衛生研究院膳食補充劑辦公室（NIH ODS）",
    "nccih": "美國國家輔助與整合健康中心（NCCIH）",
    "dris_tw": "國人膳食營養素參考攝取量（DRIs）",
    "tfda_label": "衛福部食藥署藥品仿單",
}

logger = logging.getLogger(__name__)


class Reporter(Protocol):
    def build(self, case: CaseProfile, assessment: Assessment, generated_at: datetime) -> Report:
        """評估結果 → 報告。"""
        ...


class NarratedReporter:
    def __init__(
        self,
        catalog_source: CatalogSource,
        narrator: Narrator | None,
        evidence_source: EvidenceSource | None = None,
    ) -> None:
        self._catalog_source = catalog_source
        self._narrator = narrator
        self._evidence_source = evidence_source

    def build(self, case: CaseProfile, assessment: Assessment, generated_at: datetime) -> Report:
        catalog = self._catalog_source.load()
        citations = _cited(assessment, self._catalog_source.load_citations())
        names = {i.code: i.display_name_zh for i in catalog.ingredients}
        # 沒有 LLM 就不檢索（檢索只為了給 LLM 引用）
        evidence = safe_retrieve(self._evidence_source if self._narrator else None, case, assessment)
        narration = narrate(
            self._narrator, assessment, names, condition_names(catalog), list(citations.values()), evidence
        )
        return assemble_report(case, assessment, narration, generated_at, catalog, citations, evidence)


def narrate(
    narrator: Narrator | None,
    assessment: Assessment,
    names: dict[IngredientCode, str],
    conditions: dict[str, str],
    citations: list[Citation],
    evidence: Sequence[NarrationEvidence] = (),
) -> NarrationOutput:
    """LLM 寫白話 → 輸出檢查 → 不合格重試，最多 2 次 → 仍不合格改用固定模板。"""
    fallback = template_narration(assessment, names, conditions)
    if narrator is None:
        return fallback
    request = NarrationInput(assessment=assessment, citations=citations, evidence=list(evidence))
    for attempt in range(1, MAX_RETRIES + 2):
        try:
            output = narrator.narrate(request, names)
        except NarratorError as error:
            logger.warning("LLM 敘述第 %d 次失敗：%s", attempt, error)
            continue
        result = check_narration(output, assessment, evidence)
        if result.passed:
            return output
        logger.warning("LLM 敘述第 %d 次沒通過輸出檢查：%s", attempt, result.model_dump(exclude={"passed"}))
    logger.warning("LLM 敘述重試 %d 次仍不合格，改用固定模板", MAX_RETRIES)
    return fallback


def condition_names(catalog: CatalogResponse) -> dict[str, str]:
    """用藥類別代碼與有效成分代碼 → 中文名稱（兩者代碼不重複）。"""
    return {
        **{d.active_ingredient_code: d.display_name_zh for d in catalog.drug_items},
        **{c.drug_class_code.value: c.display_name_zh for c in catalog.drug_classes},
    }


def _cited(assessment: Assessment, citations: list[Citation]) -> dict[str, Citation]:
    """只取這次評估用到的出處；規則引用了不存在的出處是資料錯誤，直接報錯。"""
    by_id = {c.citation_id: c for c in citations}
    wanted = dict.fromkeys(cid for f in assessment.interactions for t in f.triggers for cid in t.citation_ids)
    missing = [cid for cid in wanted if cid not in by_id]
    if missing:
        raise ValueError(f"出處表找不到：{', '.join(missing)}")
    return {cid: by_id[cid] for cid in wanted}


def assemble_report(
    case: CaseProfile,
    assessment: Assessment,
    narration: NarrationOutput,
    generated_at: datetime,
    catalog: CatalogResponse,
    citations: dict[str, Citation],
    evidence: Sequence[NarrationEvidence] = (),
) -> Report:
    names = {i.code: i.display_name_zh for i in catalog.ingredients}
    conditions = condition_names(catalog)
    texts = {(i.kind, i.ingredient_code): i.text for i in narration.items}
    summary = texts[(NarrationKind.SUMMARY, None)]
    footnotes, numbers = _footnotes(narration, assessment, evidence)
    return Report.model_validate(
        {
            "report_id": uuid4(),
            "case_id": case.case_id,
            "generated_at": generated_at,
            "decision_data_version": assessment.decision_data_version,
            "narration_model": narration.model,
            "prompt_version": narration.prompt_version,
            "profile": _profile(case, catalog),
            "products": [
                ReportProduct(product_id=p.product_id, display_name=p.product_name or f"保健食品 {i}")
                for i, p in enumerate(case.supplements, start=1)
            ],
            "summary": summary,
            "nutrients": [
                ReportNutrient.model_validate(
                    {
                        **n.model_dump(),
                        "display_name_zh": names[n.nutrient_code],
                        "narration": texts.get((NarrationKind.NUTRIENT, n.nutrient_code)),
                    }
                )
                for n in assessment.relevant_nutrients
            ],
            "interactions": [
                ReportInteraction.model_validate(
                    {
                        **f.model_dump(exclude={"triggers"}),
                        "display_name_zh": names[f.ingredient_code],
                        "triggers": [_trigger(t, conditions, citations) for t in f.triggers],
                        "narration": texts.get((NarrationKind.INTERACTION, f.ingredient_code)),
                        "footnote_numbers": numbers.get(f.ingredient_code, []),
                    }
                )
                for f in assessment.interactions
            ],
            "disclosures": assessment.disclosures,
            "footnotes": footnotes,
        }
    )


def _footnotes(
    narration: NarrationOutput, assessment: Assessment, evidence: Sequence[NarrationEvidence]
) -> tuple[list[ReportFootnote], dict[IngredientCode, list[int]]]:
    """腳註編號依交互作用在報告中的順序、每則說明內的引用順序，第一次被引用時給號；同一段原文只列一次。"""
    by_id = {e.chunk_id: e for e in evidence}
    cited = {i.ingredient_code: i.evidence_ids for i in narration.items if i.kind is NarrationKind.INTERACTION}
    number_of: dict[str, int] = {}
    footnotes: list[ReportFootnote] = []
    numbers: dict[IngredientCode, list[int]] = {}
    for finding in assessment.interactions:
        for chunk_id in dict.fromkeys(cited.get(finding.ingredient_code, [])):
            e = by_id.get(chunk_id)
            if e is None:
                continue
            if chunk_id not in number_of:
                number_of[chunk_id] = len(footnotes) + 1
                footnotes.append(_footnote(number_of[chunk_id], e))
            numbers.setdefault(finding.ingredient_code, []).append(number_of[chunk_id])
    return footnotes, numbers


def _footnote(number: int, e: NarrationEvidence) -> ReportFootnote:
    excerpt = e.text.strip()
    if len(excerpt) > EXCERPT_LENGTH:
        excerpt = excerpt[:EXCERPT_LENGTH].rstrip() + "…"
    return ReportFootnote(
        number=number,
        chunk_id=e.chunk_id,
        source=e.source,
        source_name=SOURCE_NAMES.get(e.source, e.source),
        title=e.title,
        section=e.section,
        url=e.url,
        excerpt=excerpt,
    )


def _profile(case: CaseProfile, catalog: CatalogResponse) -> ReportProfile:
    condition_names = {c.condition_code: c.display_name_zh for c in catalog.known_conditions}
    return ReportProfile(
        age=case.basic_profile.age,
        sex=case.basic_profile.sex,
        age_band=case.basic_profile.age_band,
        known_conditions=[
            ReportCondition(condition_code=c, display_name_zh=condition_names[c]) for c in case.conditions.selected
        ],
        known_conditions_none=case.conditions.none_selected,
        drugs=[
            ReportDrug(
                raw_name=d.raw_name,
                scope_status=d.scope_status,
                active_ingredient_code=d.active_ingredient_code,
                display_name_zh=d.display_name_zh,
                drug_class_codes=d.drug_class_codes,
            )
            for d in case.drugs.selected
        ],
        drugs_none=case.drugs.none_selected,
    )


def _trigger(trigger: Trigger, conditions: dict[str, str], citations: dict[str, Citation]) -> ReportTrigger:
    return ReportTrigger.model_validate(
        {
            **trigger.model_dump(),
            "condition_display_name_zh": conditions.get(trigger.condition_code, trigger.condition_code),
            "citations": [citations[cid] for cid in trigger.citation_ids],
        }
    )


@lru_cache(maxsize=1)
def get_reporter() -> Reporter:
    return NarratedReporter(get_catalog_source(), get_narrator(), get_evidence_source())
