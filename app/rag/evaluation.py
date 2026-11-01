"""RAG 評估的資料格式與計分。

一筆個案 ＝ 問題（成分＋藥）→ 預期檢索到的證據段落 → 預期解釋要涵蓋的重點。
預期段落用「文件路徑＋段落內一句原文」定位（段落 ID 是內容雜湊，重新切塊就變）；
預期重點用「任一關鍵字出現就算涵蓋」，不用 LLM 當裁判，結果可重現（重點由 C-3 的解釋整合使用）。
"""

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel

from app.rag.search import Evidence


class ExpectedEvidence(BaseModel):
    document_path: str  # 相對 data/sources/（同 document_id）
    contains: str  # 該段落內的一句原文


class ExpectedPoint(BaseModel):
    label: str
    any_of: list[str]


class RagCase(BaseModel):
    id: str
    question: str
    ingredient_code: str
    drug_ingredient_codes: list[str]
    expected_evidence: list[ExpectedEvidence]
    expected_points: list[ExpectedPoint]


@dataclass(frozen=True)
class Score:
    found: int
    total: int

    @property
    def ratio(self) -> float:
        return self.found / self.total if self.total else 1.0


def load_cases(path: Path) -> list[RagCase]:
    return [RagCase.model_validate(item) for item in json.loads(Path(path).read_text("utf-8"))]


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text).casefold()


def score_retrieval(case: RagCase, retrieved: Sequence[Evidence]) -> Score:
    found = sum(
        any(e.document_id == expected.document_path and _squash(expected.contains) in _squash(e.text) for e in retrieved)
        for expected in case.expected_evidence
    )
    return Score(found, len(case.expected_evidence))


def score_points(case: RagCase, explanation_text: str) -> Score:
    text = _squash(explanation_text)
    found = sum(any(_squash(k) in text for k in p.any_of) for p in case.expected_points)
    return Score(found, len(case.expected_points))


def validate_against_corpus(case: RagCase, sources_dir: Path) -> list[str]:
    """離線檢查：預期原文真的在語料裡，避免評估資料本身寫錯。"""
    problems = []
    for expected in case.expected_evidence:
        path = Path(sources_dir) / expected.document_path
        if not path.exists():
            problems.append(f"找不到文件：{expected.document_path}")
        elif _squash(expected.contains) not in _squash(path.read_text("utf-8")):
            problems.append(f"文件裡沒有這句原文：{expected.contains}")
    return problems
