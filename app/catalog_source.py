"""參考資料的來源。

現在讀 data/catalog/ 的 CSV（正本，進 git）；資料庫版好了之後，只要換掉
get_catalog_source 回傳的實作，網址與前端都不用改。
"""

from functools import cached_property, lru_cache
from pathlib import Path
from typing import Protocol

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
from app.schemas.csv_io import load_csv
from app.schemas.reference import DrugProduct, ReferenceData
from app.schemas.rules import Citation, Rule

CATALOG_DIR = Path(__file__).resolve().parents[1] / "data" / "catalog"
EXAMPLE_CATALOG_DIR = Path(__file__).resolve().parents[1] / "docs" / "schemas" / "examples" / "catalog"


class CatalogSource(Protocol):
    def load(self) -> CatalogResponse: ...

    def load_citations(self) -> list[Citation]:
        """報告展開出處用；不放進 GET /api/catalog（前端選單用不到）。"""
        ...

    def load_reference(self) -> ReferenceData:
        """計算層一次取回所有參考資料。"""
        ...

    def load_drug_products(self) -> list[DrugProduct]:
        """TFDA 品名對照（約 4 萬筆），不放進 GET /api/catalog。"""
        ...


class CsvCatalogSource:
    def __init__(self, directory: Path = CATALOG_DIR) -> None:
        self._directory = directory

    def load(self) -> CatalogResponse:
        d = self._directory
        return CatalogResponse(
            known_conditions=load_csv(d / "known_conditions.csv", KnownCondition),
            drug_classes=load_csv(d / "drug_classes.csv", DrugClass),
            drug_items=load_csv(d / "drug_items.csv", DrugItem),
            drug_nutrient_doses=load_csv(d / "drug_nutrient_doses.csv", DrugNutrientDose),
            ingredients=load_csv(d / "ingredients.csv", Ingredient),
        )

    def load_citations(self) -> list[Citation]:
        return load_csv(self._directory / "citations.csv", Citation)

    def load_reference(self) -> ReferenceData:
        return self._reference

    def load_drug_products(self) -> list[DrugProduct]:
        return self._drug_products

    # 4 萬列的藥名表與整包參考資料只讀一次
    @cached_property
    def _reference(self) -> ReferenceData:
        d = self._directory
        version_file = d / "VERSION"
        if not version_file.is_file():
            raise FileNotFoundError(f"找不到參考資料版本檔：{version_file}")
        return ReferenceData(
            version=version_file.read_text(encoding="utf-8").strip(),
            catalog=self.load(),
            out_of_scope_names=load_csv(d / "out_of_scope_names.csv", OutOfScopeName),
            dris_values=load_csv(d / "dris_values.csv", DrisValue),
            compounds=load_csv(d / "compound_ratios.csv", CompoundRatio),
            conversion_factors=load_csv(d / "conversion_factors.csv", ConversionFactor),
            rules=load_csv(d / "rules.csv", Rule),
            citations=self.load_citations(),
        )

    @cached_property
    def _drug_products(self) -> list[DrugProduct]:
        return load_csv(self._directory / "drug_products.csv", DrugProduct)


@lru_cache(maxsize=1)
def get_catalog_source() -> CatalogSource:
    return CsvCatalogSource(CATALOG_DIR)
