"""報告產生的替換點。

LLM 敘述與輸出檢查的真版本好了之後，只要換掉 get_reporter 回傳的實作，網址與前端都不用改。
FakeReporter 不管輸入，一律回傳 08_report 範例（編號、時間、版本戳換成這次的），
所以它的內容不可當作正確結果。
"""

from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from app.schemas.assessment import Assessment
from app.schemas.case import CaseProfile
from app.schemas.report import Report

_EXAMPLE_REPORT = Path(__file__).resolve().parents[1] / "docs" / "schemas" / "examples" / "08_report.json"


class Reporter(Protocol):
    def build(self, case: CaseProfile, assessment: Assessment, generated_at: datetime) -> Report:
        """評估結果 → 報告（之後在這裡接 LLM 敘述與輸出檢查）。"""
        ...


class FakeReporter:
    def build(self, case: CaseProfile, assessment: Assessment, generated_at: datetime) -> Report:
        example = Report.model_validate_json(_EXAMPLE_REPORT.read_text(encoding="utf-8"))
        return example.model_copy(
            update={
                "report_id": uuid4(),
                "case_id": case.case_id,
                "generated_at": generated_at,
                "decision_data_version": case.decision_data_version,
            }
        )


@lru_cache(maxsize=1)
def get_reporter() -> Reporter:
    return FakeReporter()
