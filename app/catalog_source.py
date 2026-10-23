"""選單資料的來源。

現在讀 repo 範例 CSV；DB 組員的資料表好了之後，只要換掉 get_catalog_source 回傳的實作，
網址與前端都不用改。
"""

from functools import lru_cache
from pathlib import Path
from typing import Protocol

from app.schemas.catalog import CatalogResponse, DrugClass, DrugItem, DrugNutrientDose, Ingredient, KnownCondition
from app.schemas.csv_io import load_csv
from app.schemas.rules import Citation

_EXAMPLE_CATALOG_DIR = Path(__file__).resolve().parents[1] / "docs" / "schemas" / "examples" / "catalog"


class CatalogSource(Protocol):
    def load(self) -> CatalogResponse: ...

    def load_citations(self) -> list[Citation]:
        """報告展開出處用；不放進 GET /api/catalog（前端選單用不到）。"""
        ...


class CsvCatalogSource:
    def __init__(self, directory: Path) -> None:
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


@lru_cache(maxsize=1)
def get_catalog_source() -> CatalogSource:
    return CsvCatalogSource(_EXAMPLE_CATALOG_DIR)
