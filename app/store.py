"""產品、草稿、評估結果與報告的存放處。

預設存在記憶體（重啟就沒了）；STORE=pg 時改存資料庫的 app schema（app/db/store.py）。
網址與前端都不用改。登入方式由環境變數 AUTH 決定（見 app/auth.py）。
"""

import os
from dataclasses import dataclass
from datetime import date, timedelta, timezone
from functools import lru_cache
from typing import Protocol
from uuid import UUID, uuid4

from app.schemas.assessment import Assessment
from app.schemas.case import AccountProfile, CaseProfile
from app.schemas.common import ExclusiveSelection
from app.schemas.drug_label import DrugCorrection, DrugDraft
from app.schemas.enums import ConditionCode, Sex
from app.schemas.label import ExtractionDraft, LabelCorrection, VerifiedProduct
from app.schemas.report import Report

TAIPEI_TZ = timezone(timedelta(hours=8))  # 報告日期以台灣時間判斷是哪一天
TEST_USER_ID = UUID("b0000000-0000-4000-8000-000000000001")  # 同 case_profile.json 範例


@dataclass(frozen=True)
class AccountUser:
    """登入帳號的基本資料（後端內部使用，不進 API 模型）。"""

    user_id: UUID
    email: str | None
    name: str | None


class Store(Protocol):
    def find_or_create_google_user(self, sub: str, email: str | None, name: str | None) -> UUID:
        """同一個 Google sub 永遠回同一個 UUID；已存在時更新 email、name。"""
        ...

    def get_user(self, user_id: UUID) -> AccountUser | None: ...

    def save_product(self, user_id: UUID, product: VerifiedProduct) -> None: ...

    def get_products(self, user_id: UUID, product_ids: list[UUID]) -> list[VerifiedProduct]:
        """只回這個使用者自己的產品，依傳入順序；找不到或不是自己的編號直接略過，由呼叫端比對。"""
        ...

    def get_profile(self, user_id: UUID) -> AccountProfile | None:
        """評估時從帳號讀出的基本資料；還沒填過回 None。"""
        ...

    def save_profile(self, user_id: UUID, profile: AccountProfile) -> None: ...

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


# 測試帳號（AUTH=test）預設已有的基本資料，和範例個案一致
TEST_PROFILE = AccountProfile(
    birth_year=1954,
    birth_month=3,
    sex=Sex.MALE,
    conditions=ExclusiveSelection[ConditionCode](
        selected=[ConditionCode.HYPERTENSION, ConditionCode.DYSLIPIDEMIA], none_selected=False
    ),
)
TEST_USER_NAME = "測試帳號"


class InMemoryStore:
    def __init__(self) -> None:
        self._products: dict[UUID, tuple[UUID, VerifiedProduct]] = {}
        self._users: dict[UUID, AccountUser] = {TEST_USER_ID: AccountUser(TEST_USER_ID, None, TEST_USER_NAME)}
        self._google_subs: dict[str, UUID] = {}
        self._profiles: dict[UUID, AccountProfile] = {TEST_USER_ID: TEST_PROFILE}
        self.assessments: list[tuple[CaseProfile, Assessment]] = []
        self.drug_drafts: list[tuple[UUID, DrugDraft]] = []
        self.supplement_drafts: list[tuple[UUID, ExtractionDraft]] = []
        self.label_corrections: list[tuple[UUID, LabelCorrection]] = []
        self.drug_corrections: list[tuple[UUID, DrugCorrection]] = []
        self._reports: list[tuple[UUID, Report]] = []

    def find_or_create_google_user(self, sub: str, email: str | None, name: str | None) -> UUID:
        user_id = self._google_subs.get(sub) or uuid4()
        self._google_subs[sub] = user_id
        self._users[user_id] = AccountUser(user_id, email, name)
        return user_id

    def get_user(self, user_id: UUID) -> AccountUser | None:
        return self._users.get(user_id)

    def save_product(self, user_id: UUID, product: VerifiedProduct) -> None:
        self._products[product.product_id] = (user_id, product)

    def get_products(self, user_id: UUID, product_ids: list[UUID]) -> list[VerifiedProduct]:
        mine = {pid: p for pid, (owner, p) in self._products.items() if owner == user_id}
        return [mine[pid] for pid in product_ids if pid in mine]

    def get_profile(self, user_id: UUID) -> AccountProfile | None:
        return self._profiles.get(user_id)

    def save_profile(self, user_id: UUID, profile: AccountProfile) -> None:
        self._profiles[user_id] = profile

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


def store_mode() -> str:
    mode = os.environ.get("STORE", "memory")
    if mode not in ("memory", "pg"):
        raise RuntimeError(f"STORE 只接受 memory 或 pg，收到 {mode!r}")
    return mode


@lru_cache(maxsize=1)
def get_store() -> Store:
    if store_mode() == "pg":
        from app.db.pool import get_pool  # 預設模式不需要載入資料庫套件
        from app.db.store import PgStore

        return PgStore(get_pool())
    return InMemoryStore()


def init_store() -> None:
    """伺服器啟動時呼叫：STORE=pg 時開連線池；AUTH=test 時確認測試帳號存在（不存在就建立）。"""
    if store_mode() != "pg":
        return
    store = get_store()
    if os.environ.get("AUTH", "test") == "test":
        store.ensure_test_user()  # type: ignore[attr-defined]


def close_store() -> None:
    """伺服器關閉時呼叫：關連線池。"""
    if store_mode() == "pg":
        from app.db.pool import close_pool

        close_pool()
        get_store.cache_clear()
