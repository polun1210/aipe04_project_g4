"""計算層與藥名比對一次取回的參考資料（資料來源可以是 CSV 或資料庫）。"""

from typing import Literal

from pydantic import Field

from app.schemas.catalog import (
    CatalogResponse,
    Code,
    CompoundRatio,
    ConversionFactor,
    DrisValue,
    OutOfScopeName,
)
from app.schemas.common import PipeList, StrictModel
from app.schemas.rules import Citation, Rule


class DrugProduct(StrictModel):
    """drug_products.csv（約 4 萬列）：TFDA 有效許可證的品名 → 範圍內有效成分（複方多個）。"""

    name: str
    lang: Literal["zh", "en"]
    active_ingredient_codes: PipeList[Code] = Field(default_factory=list)  # 空 ＝ 處方成分全部範圍外
    out_of_scope_ingredients: PipeList[str] = Field(default_factory=list)  # 範圍外處方成分原文


class ReferenceData(StrictModel):
    """計算層一次取回的參考資料。"""

    version: str  # 參考資料版本，寫進 CaseProfile.decision_data_version
    catalog: CatalogResponse
    out_of_scope_names: list[OutOfScopeName]
    dris_values: list[DrisValue]
    compounds: list[CompoundRatio]
    conversion_factors: list[ConversionFactor]
    rules: list[Rule]  # 所有狀態都回；計算層只用 status = reviewed
    citations: list[Citation]
