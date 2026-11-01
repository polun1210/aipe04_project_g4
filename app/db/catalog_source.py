"""從資料庫的 catalog.v_* view 讀參考資料，回傳跟 CsvCatalogSource 一樣的模型。

view 的欄位名稱與型別對齊 app/schemas，這裡只是逐列 model_validate。第一次用到時讀一次並快取
（參考資料改版要重啟伺服器），跟 CSV 版一樣。
"""

from functools import cached_property
from typing import TypeVar

import psycopg
from psycopg.rows import dict_row
from pydantic import BaseModel

from app.db.config import database_url
from app.schemas.catalog import (
    CatalogResponse,
    CompoundRatio,
    ConversionFactor,
    DrisValue,
    DrugClass,
    DrugItem,
    DrugNutrientDose,
    Ingredient,
    KnownCondition,
    OutOfScopeName,
)
from app.schemas.reference import DrugProduct, ReferenceData
from app.schemas.rules import Citation, Rule

M = TypeVar("M", bound=BaseModel)


class PgCatalogSource:
    def __init__(self, url: str | None = None) -> None:
        self._url = url

    def load(self) -> CatalogResponse:
        return self._reference.catalog

    def load_citations(self) -> list[Citation]:
        return self._reference.citations

    def load_reference(self) -> ReferenceData:
        return self._reference

    def load_drug_products(self) -> list[DrugProduct]:
        return self._drug_products

    @cached_property
    def _reference(self) -> ReferenceData:
        with psycopg.connect(self._url or database_url(), row_factory=dict_row) as conn:
            version = conn.execute("SELECT version FROM catalog.data_versions ORDER BY imported_at DESC LIMIT 1")
            row = version.fetchone()
            if row is None:
                raise RuntimeError("資料庫裡沒有參考資料，請先執行 python -m app.db.import_catalog")

            def read(view: str, model: type[M]) -> list[M]:
                return [model.model_validate(r) for r in conn.execute(f"SELECT * FROM catalog.{view}")]

            return ReferenceData(
                version=row["version"],
                catalog=CatalogResponse(
                    known_conditions=read("v_known_conditions", KnownCondition),
                    drug_classes=read("v_drug_classes", DrugClass),
                    drug_items=read("v_drug_items", DrugItem),
                    drug_nutrient_doses=read("v_drug_nutrient_doses", DrugNutrientDose),
                    ingredients=read("v_ingredients", Ingredient),
                ),
                out_of_scope_names=read("v_out_of_scope_names", OutOfScopeName),
                dris_values=read("v_dris_values", DrisValue),
                compounds=read("v_compounds", CompoundRatio),
                conversion_factors=read("v_conversion_factors", ConversionFactor),
                rules=read("v_rules", Rule),
                citations=read("v_citations", Citation),
            )

    @cached_property
    def _drug_products(self) -> list[DrugProduct]:
        with psycopg.connect(self._url or database_url(), row_factory=dict_row) as conn:
            return [DrugProduct.model_validate(r) for r in conn.execute("SELECT * FROM catalog.v_drug_products")]
