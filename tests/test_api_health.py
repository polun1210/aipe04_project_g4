from fastapi.testclient import TestClient

from app.main import create_app


def test_health_returns_ok():
    client = TestClient(create_app())
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_upload_fields_are_binary_so_swagger_shows_file_picker():
    schemas = TestClient(create_app()).get("/openapi.json").json()["components"]["schemas"]
    fields = {
        "Body_create_drug_draft_api_drug_drafts_post": "images",
        "Body_create_supplement_draft_api_supplement_drafts_post": "ingredient_images",
    }
    for schema_name, field in fields.items():
        assert schemas[schema_name]["properties"][field]["items"] == {"type": "string", "format": "binary"}
    nutrition = schemas["Body_create_supplement_draft_api_supplement_drafts_post"]["properties"]["nutrition_images"]
    assert nutrition["items"] == {"type": "string", "format": "binary"}
