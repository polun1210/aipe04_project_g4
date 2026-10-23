"""產品、草稿、評估結果與報告的存放處。

現在存在記憶體（重啟就沒了）；DB 組員的資料表好了之後，只要換掉 get_store 回傳的實作，
網址與前端都不用改。還沒有登入前，一律用固定的測試帳號。
"""

from datetime import date, timedelta, timezone
from functools import lru_cache
from typing import Protocol
from uuid import UUID

from app.schemas.assessment import Assessment
from app.schemas.case import AccountProfile, CaseProfile
from app.schemas.common import ExclusiveSelection
from app.schemas.drug_label import DrugCorrection, DrugDraft
from app.schemas.enums import ConditionCode, Sex
from app.schemas.label import ExtractionDraft, LabelCorrection, VerifiedProduct
from app.schemas.report import Report

TAIPEI_TZ = timezone(timedelta(hours=8))  # 報告日期以台灣時間判斷是哪一天
TEST_USER_ID = UUID("b0000000-0000-4000-8000-000000000001")  # 同 case_profile.json 範例


class Store(Protocol):
    def save_product(self, product: VerifiedProduct) -> None: ...

    def get_products(self, product_ids: list[UUID]) -> list[VerifiedProduct]:
        """依傳入順序回傳；找不到的編號直接略過，由呼叫端比對。"""
        ...

    def get_profile(self, user_id: UUID) -> AccountProfile:
        """評估時從帳號讀出的基本資料。"""
        ...

    def save_assessment(self, case: CaseProfile, assessment: Assessment) -> None: ...

    def save_drug_draft(self, user_id: UUID, draft: DrugDraft) -> None: ...

    def get_drug_draft(self, user_id: UUID, draft_id: UUID) -> DrugDraft | None:
        """不存在或不屬於這個使用者都回 None。"""
        ...

    def save_supplement_draft(self, user_id: UUID, draft: ExtractionDraft) -> None: ...

    def get_supplement_draft(self, user_id: UUID, product_id: UUID) -> ExtractionDraft | None:
        """不存在或不屬於這個使用者都回 None。"""
        ...

    def save_label_corrections(self, user_id: UUID, corrections: list[LabelCorrection]) -> None: ...

    def save_drug_corrections(self, user_id: UUID, corrections: list[DrugCorrection]) -> None: ...

    def get_case(self, user_id: UUID, case_id: UUID) -> tuple[CaseProfile, Assessment] | None:
        """不存在或不屬於這個使用者都回 None。"""
        ...

    def save_report(self, user_id: UUID, report: Report) -> None: ...

    def get_report_by_case(self, user_id: UUID, case_id: UUID) -> Report | None: ...

    def get_report(self, user_id: UUID, report_id: UUID) -> Report | None: ...

    def list_reports(self, user_id: UUID, date_from: date | None, date_to: date | None) -> list[Report]:
        """依 generated_at 新到舊；日期（含當天）以台灣時間判斷。"""
        ...


class InMemoryStore:
    def __init__(self) -> None:
        self._products: dict[UUID, VerifiedProduct] = {}
        self.assessments: list[tuple[CaseProfile, Assessment]] = []
        self.drug_drafts: list[tuple[UUID, DrugDraft]] = []
        self.supplement_drafts: list[tuple[UUID, ExtractionDraft]] = []
        self.label_corrections: list[tuple[UUID, LabelCorrection]] = []
        self.drug_corrections: list[tuple[UUID, DrugCorrection]] = []
        self._reports: list[tuple[UUID, Report]] = []

    def save_product(self, product: VerifiedProduct) -> None:
        self._products[product.product_id] = product

    def get_products(self, product_ids: list[UUID]) -> list[VerifiedProduct]:
        return [self._products[pid] for pid in product_ids if pid in self._products]

    def get_profile(self, user_id: UUID) -> AccountProfile:
        """第一週沒有登入：固定回測試帳號，和範例個案一致。"""
        return AccountProfile(
            birth_year=1954,
            birth_month=3,
            sex=Sex.MALE,
            conditions=ExclusiveSelection[ConditionCode](
                selected=[ConditionCode.HYPERTENSION, ConditionCode.DYSLIPIDEMIA], none_selected=False
            ),
        )

    def save_assessment(self, case: CaseProfile, assessment: Assessment) -> None:
        self.assessments.append((case, assessment))

    def save_drug_draft(self, user_id: UUID, draft: DrugDraft) -> None:
        self.drug_drafts.append((user_id, draft))

    def get_drug_draft(self, user_id: UUID, draft_id: UUID) -> DrugDraft | None:
        return next((d for u, d in self.drug_drafts if u == user_id and d.draft_id == draft_id), None)

    def save_supplement_draft(self, user_id: UUID, draft: ExtractionDraft) -> None:
        self.supplement_drafts.append((user_id, draft))

    def get_supplement_draft(self, user_id: UUID, product_id: UUID) -> ExtractionDraft | None:
        return next((d for u, d in self.supplement_drafts if u == user_id and d.product_id == product_id), None)

    def save_label_corrections(self, user_id: UUID, corrections: list[LabelCorrection]) -> None:
        self.label_corrections += [(user_id, c) for c in corrections]

    def save_drug_corrections(self, user_id: UUID, corrections: list[DrugCorrection]) -> None:
        self.drug_corrections += [(user_id, c) for c in corrections]

    def get_case(self, user_id: UUID, case_id: UUID) -> tuple[CaseProfile, Assessment] | None:
        return next(
            ((c, a) for c, a in self.assessments if c.case_id == case_id and c.user_id == user_id),
            None,
        )

    def save_report(self, user_id: UUID, report: Report) -> None:
        self._reports.append((user_id, report))

    def get_report_by_case(self, user_id: UUID, case_id: UUID) -> Report | None:
        return next((r for u, r in self._reports if u == user_id and r.case_id == case_id), None)

    def get_report(self, user_id: UUID, report_id: UUID) -> Report | None:
        return next((r for u, r in self._reports if u == user_id and r.report_id == report_id), None)

    def list_reports(self, user_id: UUID, date_from: date | None, date_to: date | None) -> list[Report]:
        mine = [r for u, r in self._reports if u == user_id]
        in_range = [r for r in mine if _in_range(r.generated_at.astimezone(TAIPEI_TZ).date(), date_from, date_to)]
        return sorted(in_range, key=lambda r: r.generated_at, reverse=True)


def _in_range(day: date, date_from: date | None, date_to: date | None) -> bool:
    return (date_from is None or day >= date_from) and (date_to is None or day <= date_to)


@lru_cache(maxsize=1)
def get_store() -> Store:
    return InMemoryStore()
