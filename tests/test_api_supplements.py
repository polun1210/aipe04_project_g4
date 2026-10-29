import pytest
from uuid import UUID
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


@pytest.mark.parametrize("outside_only", [False, True])
def test_out_of_scope_rows_need_no_lock_and_survive_product_assessment_and_report(client, store, outside_only):
    draft_response = client.post("/api/supplement-drafts", files=[_file("nutrition_images")])
    assert draft_response.status_code == 201
    draft = draft_response.json()
    # Keep the original OCR draft; only choose which rows need review in the submitted product.
    rows = [
        {
            "row_id": row["row_id"],
            "standard_code": None,
            "scope_status": "out_of_scope",
            "nutrient_form_code": row["nutrient_form_code"],
            "per_serving": row["per_serving"],
            "unit": row["unit"],
            "stated_elemental_amount": row["stated_elemental_amount"],
        }
        for row in draft["nutrients"]
    ]
    if not outside_only:
        rows[0].update(standard_code="calcium", scope_status="in_scope", per_serving=100, unit="mg")
        rows[1].update(scope_status="unresolved")
    rows[-1].update(per_serving=None, unit=None, stated_elemental_amount=None)
    response = client.post(
        "/api/products",
        json={
            "draft_product_id": draft["product_id"],
            "product_name": draft["product_name"],
            "serving_info": {"serving_size": 1, "dose_unit": "tablet"},
            "user_intake": {"frequency_type": "daily", "times_per_day": 1, "amount_per_time": 1},
            "nutrients": rows,
        },
    )
    assert response.status_code == 201, response.text
    product_id = response.json()["product_id"]
    [product] = store.get_products([UUID(product_id)])
    assert len(product.nutrients) == len(draft["nutrients"])
    assert [row.row_id for row in product.nutrients] == [row["row_id"] for row in draft["nutrients"]]
    outside = [row for row in product.nutrients if row.scope_status == "out_of_scope"]
    assert outside
    assert all(row.peak_daily_amount is None and not row.ul_applicable for row in outside)
    saved_draft = store.get_supplement_draft(TEST_USER_ID, UUID(draft["product_id"]))
    assert saved_draft.model_dump(mode="json") == draft
    assert not any(c.correction_type == "removed" for _, c in store.label_corrections)
    assessment = client.post(
        "/api/assessments", json={"drugs": {"none_selected": True}, "product_ids": [product_id]}
    )
    assert assessment.status_code == 200, assessment.text
    report = client.post(f"/api/assessments/{assessment.json()['case_id']}/report")
    assert report.status_code == 201, report.text
