"""產品與評估結果的存放處。

現在存在記憶體（重啟就沒了）；DB 組員的資料表好了之後，只要換掉 get_store 回傳的實作，
網址與前端都不用改。第一週還沒有登入，一律用固定的測試帳號。
"""

from functools import lru_cache
from typing import Protocol
from uuid import UUID

from app.schemas.assessment import Assessment
from app.schemas.case import CaseProfile
from app.schemas.label import VerifiedProduct

TEST_USER_ID = UUID("b0000000-0000-4000-8000-000000000001")  # 同 case_profile.json 範例


class Store(Protocol):
    def save_product(self, product: VerifiedProduct) -> None: ...

    def get_products(self, product_ids: list[UUID]) -> list[VerifiedProduct]:
        """依傳入順序回傳；找不到的編號直接略過，由呼叫端比對。"""
        ...

    def save_assessment(self, case: CaseProfile, assessment: Assessment) -> None: ...


class InMemoryStore:
    def __init__(self) -> None:
        self._products: dict[UUID, VerifiedProduct] = {}
        self.assessments: list[tuple[CaseProfile, Assessment]] = []

    def save_product(self, product: VerifiedProduct) -> None:
        self._products[product.product_id] = product

    def get_products(self, product_ids: list[UUID]) -> list[VerifiedProduct]:
        return [self._products[pid] for pid in product_ids if pid in self._products]

    def save_assessment(self, case: CaseProfile, assessment: Assessment) -> None:
        self.assessments.append((case, assessment))


@lru_cache(maxsize=1)
def get_store() -> Store:
    return InMemoryStore()
