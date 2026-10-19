"""辨識服務的切換：明確指定才用真辨識，設錯就報錯，不默默用假資料。"""

import pytest

from app.extraction import ExtractionError
from app.extractor import OpenRouterExtractor, StubExtractor, get_extractor


@pytest.fixture(autouse=True)
def fresh():
    get_extractor.cache_clear()
    yield
    get_extractor.cache_clear()


def test_沒設定時是假版本(monkeypatch):
    monkeypatch.delenv("EXTRACTOR", raising=False)
    assert type(get_extractor()) is StubExtractor


def test_指定_openrouter_時用真辨識(monkeypatch):
    monkeypatch.setenv("EXTRACTOR", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("OPENROUTER_MODEL", "google/gemini-3.8-flash")
    monkeypatch.setenv("OPENROUTER_PROVIDER", "google-ai-studio")
    assert isinstance(get_extractor(), OpenRouterExtractor)


def test_指定_openrouter_但沒有金鑰時報錯而不是改用假版本(monkeypatch):
    monkeypatch.setenv("EXTRACTOR", "openrouter")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(ExtractionError, match="OPENROUTER_API_KEY"):
        get_extractor()


def test_切換值打錯時報錯(monkeypatch):
    monkeypatch.setenv("EXTRACTOR", "openrouterr")
    with pytest.raises(ValueError, match="EXTRACTOR"):
        get_extractor()
