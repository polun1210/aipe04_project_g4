"""替每條交互作用檢索證據段落（ADR-0013）。檢索失敗或沒設資料庫時回傳空，報告退回只用規則引文。"""

import logging
import os
from collections.abc import Sequence
from functools import lru_cache
from typing import Protocol

import psycopg

from app.rag.embedder import Embedder, embedder_from_env
from app.rag.search import Evidence, retrieve_evidence
from app.schemas.assessment import Assessment, InteractionFinding
from app.schemas.case import CaseProfile
from app.schemas.enums import ConditionType
from app.schemas.narration import NarrationEvidence

EVIDENCE_PER_FINDING = 4  # 每條交互作用交給 LLM 的段落數，控制提示詞長度

logger = logging.getLogger(__name__)


class EvidenceSource(Protocol):
    def retrieve(self, case: CaseProfile, assessment: Assessment) -> list[NarrationEvidence]:
        """每條交互作用各檢索一次。失敗時丟例外，呼叫端負責退回。"""
        ...


class RagEvidenceSource:
    def __init__(self, database_url: str, embedder: Embedder | None = None) -> None:
        self._database_url = database_url
        self._embedder = embedder

    def retrieve(self, case: CaseProfile, assessment: Assessment) -> list[NarrationEvidence]:
        if not assessment.interactions:
            return []
        embedder = self._embedder or embedder_from_env()
        with psycopg.connect(self._database_url, autocommit=True) as conn:
            return [
                _to_evidence(finding, e)
                for finding in assessment.interactions
                for e in retrieve_evidence(
                    conn, embedder, finding.ingredient_code.value, drug_codes(case, finding), EVIDENCE_PER_FINDING
                )
            ]


def drug_codes(case: CaseProfile, finding: InteractionFinding) -> Sequence[str]:
    """這條交互作用的規則牽涉到、而且使用者真的在吃的藥（有效成分代碼）。"""
    wanted_ingredients = {
        t.condition_code for t in finding.triggers if t.condition_type is ConditionType.DRUG_INGREDIENT
    }
    wanted_classes = {t.condition_code for t in finding.triggers if t.condition_type is ConditionType.DRUG_CLASS}
    return list(
        dict.fromkeys(
            d.active_ingredient_code
            for d in case.drugs.selected
            if d.active_ingredient_code
            and (
                d.active_ingredient_code in wanted_ingredients
                or {c.value for c in d.drug_class_codes} & wanted_classes
            )
        )
    )


def _to_evidence(finding: InteractionFinding, e: Evidence) -> NarrationEvidence:
    return NarrationEvidence(
        for_ingredient=finding.ingredient_code,
        chunk_id=e.chunk_id,
        source=e.source,
        title=e.title,
        url=e.url,
        section=e.section,
        text=e.text,
    )


def safe_retrieve(source: EvidenceSource | None, case: CaseProfile, assessment: Assessment) -> list[NarrationEvidence]:
    """任何失敗都退回空清單：報告一定要產得出來。"""
    if source is None:
        return []
    try:
        return source.retrieve(case, assessment)
    except Exception:  # noqa: BLE001 - 資料庫、embedding 服務、設定缺漏都不該讓報告失敗
        logger.warning("證據檢索失敗，報告退回只用規則引文", exc_info=True)
        return []


@lru_cache(maxsize=1)
def get_evidence_source() -> EvidenceSource | None:
    """None ＝ 不檢索：NARRATOR=template 或沒設 DATABASE_URL。"""
    url = os.environ.get("DATABASE_URL")
    if os.environ.get("NARRATOR", "template") == "template" or not url:
        return None
    return RagEvidenceSource(url)
