import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel, field_validator

from app.main import create_app
from app.schemas.api import ErrorResponse


class Payload(BaseModel):
    age: int
    name: str

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("名稱不可空白")
        return v


@pytest.fixture
def client() -> TestClient:
    app = create_app()

    @app.post("/api/_test/echo")
    def echo(payload: Payload) -> dict[str, int]:
        return {"age": payload.age}

    @app.get("/api/_test/unauthorized")
    def unauthorized() -> None:
        raise HTTPException(status_code=401)

    return TestClient(app)


def test_unknown_path_returns_not_found_error(client):
    response = client.get("/api/no-such-path")
    assert response.status_code == 404
    body = ErrorResponse.model_validate(response.json())
    assert body.error.code == "not_found"


def test_invalid_body_returns_validation_error_with_field_details(client):
    response = client.post("/api/_test/echo", json={"age": "abc", "name": "x"})
    assert response.status_code == 422
    body = ErrorResponse.model_validate(response.json())
    assert body.error.code == "validation_error"
    assert body.error.details is not None
    assert any(d.startswith("age：") for d in body.error.details)


def test_missing_field_is_reported_by_field_name(client):
    response = client.post("/api/_test/echo", json={"age": 30})
    details = ErrorResponse.model_validate(response.json()).error.details
    assert details is not None and any(d.startswith("name：") for d in details)


def test_custom_validator_message_is_kept_without_prefix(client):
    response = client.post("/api/_test/echo", json={"age": 30, "name": " "})
    details = ErrorResponse.model_validate(response.json()).error.details
    assert details == ["name：名稱不可空白"]


def test_validation_error_does_not_echo_input_values(client):
    response = client.post("/api/_test/echo", json={"age": "secret-value", "name": "x"})
    assert "secret-value" not in response.text


def test_http_401_maps_to_unauthorized(client):
    response = client.get("/api/_test/unauthorized")
    assert response.status_code == 401
    assert ErrorResponse.model_validate(response.json()).error.code == "unauthorized"
