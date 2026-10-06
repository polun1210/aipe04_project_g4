from fastapi.testclient import TestClient

from app.catalog_source import get_catalog_source
from app.main import create_app
from app.schemas.catalog import CatalogResponse, DrugItem


class FakeCatalogSource:
    def load(self) -> CatalogResponse:
        item = DrugItem(
            active_ingredient_code="fake_drug",
            display_name_zh="假藥",
            english_name="Fake",
            drug_class_codes=["ppi"],
            common_tradenames_tw=["假藥錠"],
        )
        return CatalogResponse(
            known_conditions=[], drug_classes=[], drug_items=[item], drug_nutrient_doses=[], ingredients=[]
        )


class BrokenCatalogSource:
    def load(self) -> CatalogResponse:
        raise OSError("C:/secret/path/drug_items.csv 讀取失敗")


def test_catalog_returns_valid_catalog_response():
    response = TestClient(create_app()).get("/api/catalog")
    assert response.status_code == 200
    catalog = CatalogResponse.model_validate(response.json())
    assert catalog.drug_items
    assert catalog.known_conditions
    assert catalog.ingredients


def test_catalog_uses_injected_source():
    app = create_app()
    app.dependency_overrides[get_catalog_source] = FakeCatalogSource
    response = TestClient(app).get("/api/catalog")
    assert [d["active_ingredient_code"] for d in response.json()["drug_items"]] == ["fake_drug"]


def test_catalog_source_failure_returns_internal_error_without_leaking_path():
    app = create_app()
    app.dependency_overrides[get_catalog_source] = BrokenCatalogSource
    response = TestClient(app, raise_server_exceptions=False).get("/api/catalog")
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert "secret" not in response.text
