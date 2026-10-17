import pytest
from fastapi.testclient import TestClient

from app.extraction import ExtractionError
from app.extractor import StubExtractor, get_extractor
from app.main import create_app
from app.schemas.drug_label import DrugDraft
from app.schemas.enums import QualityStatus, RejectReason
from app.schemas.label import SourceImage
from app.store import TEST_USER_ID, InMemoryStore, get_store


class RejectAllExtractor(StubExtractor):
    def check_quality(self, images):
        return [
            SourceImage(
                image_id=img.image_id,
                quality_status=QualityStatus.REJECTED,
                reject_reason=RejectReason.GLARE,
                image_kind=img.image_kind,
            )
            for img in images
        ]


class FailingExtractor(StubExtractor):
    def extract_drugs(self, draft_id, images, quality):
        raise ExtractionError("引擎逾時")


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


def _jpeg(n: int) -> tuple[str, tuple[str, bytes, str]]:
    return ("images", (f"p{n}.jpg", b"\xff\xd8fake", "image/jpeg"))


# ── POST /api/drug-drafts ───────────────────────────────────


def test_upload_two_images_returns_valid_draft(client, store):
    response = client.post("/api/drug-drafts", files=[_jpeg(1), _jpeg(2)])
    assert response.status_code == 201
    draft = DrugDraft.model_validate(response.json())
    assert [s.image_id for s in draft.source_images] == ["img-01", "img-02"]
    assert all(s.image_kind == "drug_package" for s in draft.source_images)
    assert {r.source_image_id for r in draft.rows} == {"img-01"}
    assert draft.extraction_meta.ocr_version == "stub"
    assert store.drug_drafts == [(TEST_USER_ID, draft)]


def test_upload_without_images_is_422(client):
    response = client.post("/api/drug-drafts")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_upload_non_image_is_422(client):
    files = [("images", ("a.txt", b"hello", "text/plain"))]
    response = client.post("/api/drug-drafts", files=files)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_all_images_rejected_is_422_with_reasons(app, client, store):
    app.dependency_overrides[get_extractor] = lambda: RejectAllExtractor()
    response = client.post("/api/drug-drafts", files=[_jpeg(1), _jpeg(2)])
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "all_images_rejected"
    assert error["details"] == ["img-01：反光", "img-02：反光"]
    assert store.drug_drafts == []


def test_extraction_error_is_502(app, client):
    app.dependency_overrides[get_extractor] = lambda: FailingExtractor()
    response = client.post("/api/drug-drafts", files=[_jpeg(1)])
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "extraction_failed"


# ── GET /api/drugs/lookup ───────────────────────────────────


def test_lookup_tradename_maps_and_lists_candidate(client):
    body = client.get("/api/drugs/lookup", params={"name": "立普妥"}).json()
    assert body["mapped"]["scope_status"] == "in_scope"
    assert body["candidates"][0]["active_ingredient_code"] == "atorvastatin"
    assert body["candidates"][0]["matched_name"] == "立普妥"


def test_lookup_partial_name_is_unresolved_with_candidates(client):
    body = client.get("/api/drugs/lookup", params={"name": "立普"}).json()
    assert body["mapped"]["scope_status"] == "unresolved"
    assert "atorvastatin" in [c["active_ingredient_code"] for c in body["candidates"]]


def test_lookup_gibberish_has_no_candidates(client):
    body = client.get("/api/drugs/lookup", params={"name": "亂打的藥名"}).json()
    assert body["mapped"]["scope_status"] == "unresolved"
    assert body["candidates"] == []


@pytest.mark.parametrize("name", ["", "   "])
def test_lookup_blank_name_is_422(client, name):
    response = client.get("/api/drugs/lookup", params={"name": name})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
