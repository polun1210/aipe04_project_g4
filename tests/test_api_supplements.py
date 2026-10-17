import pytest
from fastapi.testclient import TestClient

from app.extractor import StubExtractor, get_extractor
from app.main import create_app
from app.schemas.label import ExtractionDraft
from app.store import TEST_USER_ID, InMemoryStore, get_store


class UnnamedExtractor(StubExtractor):
    """假辨識沒讀到產品名稱。"""

    def extract_supplement(self, product_id, images, quality):
        draft = super().extract_supplement(product_id, images, quality)
        return draft.model_copy(update={"product_name": None})


@pytest.fixture
def store() -> InMemoryStore:
    return InMemoryStore()


@pytest.fixture
def app(store):
    app = create_app()
    app.dependency_overrides[get_store] = lambda: store
    return app


@pytest.fixture
def client(app) -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


def _file(field: str, name: str = "a.jpg", content_type: str = "image/jpeg"):
    return (field, (name, b"\xff\xd8fake", content_type))


def test_one_ingredient_and_one_nutrition_image_returns_draft(client, store):
    response = client.post(
        "/api/supplement-drafts", files=[_file("ingredient_images"), _file("nutrition_images", "b.jpg")]
    )
    assert response.status_code == 201
    draft = ExtractionDraft.model_validate(response.json())
    assert [(s.image_id, s.image_kind) for s in draft.source_images] == [
        ("img-01", "supplement_ingredients"),
        ("img-02", "supplement_nutrition"),
    ]
    assert store.supplement_drafts == [(TEST_USER_ID, draft)]


def test_no_images_in_either_field_is_422(client):
    response = client.post("/api/supplement-drafts")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_non_image_is_422(client):
    response = client.post("/api/supplement-drafts", files=[_file("nutrition_images", "a.txt", "text/plain")])
    assert response.status_code == 422


def test_category_fills_product_name_when_extraction_has_none(app, client):
    app.dependency_overrides[get_extractor] = lambda: UnnamedExtractor()
    response = client.post(
        "/api/supplement-drafts", files=[_file("ingredient_images")], data={"category": " 魚油 "}
    )
    assert response.status_code == 201
    assert response.json()["product_name"] == "魚油"


def test_extracted_product_name_wins_over_category(client):
    response = client.post("/api/supplement-drafts", files=[_file("ingredient_images")], data={"category": "魚油"})
    assert response.json()["product_name"] == "綜合維他命錠"


def test_blank_category_is_treated_as_missing(app, client):
    app.dependency_overrides[get_extractor] = lambda: UnnamedExtractor()
    response = client.post("/api/supplement-drafts", files=[_file("ingredient_images")], data={"category": "  "})
    assert response.status_code == 201
    assert response.json()["product_name"] is None


def test_category_over_30_chars_is_422(client):
    response = client.post(
        "/api/supplement-drafts", files=[_file("ingredient_images")], data={"category": "魚" * 31}
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
