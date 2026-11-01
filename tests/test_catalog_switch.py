"""CATALOG_SOURCE 切換：預設 csv，不需要資料庫。"""

import pytest

from app.catalog_source import CsvCatalogSource, get_catalog_source


@pytest.fixture(autouse=True)
def _clear_cache():
    get_catalog_source.cache_clear()
    yield
    get_catalog_source.cache_clear()


def test_預設讀CSV(monkeypatch):
    monkeypatch.delenv("CATALOG_SOURCE", raising=False)
    assert isinstance(get_catalog_source(), CsvCatalogSource)


def test_設成pg回傳資料庫版且建立時不連線(monkeypatch):
    from app.db.catalog_source import PgCatalogSource

    monkeypatch.setenv("CATALOG_SOURCE", "pg")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert isinstance(get_catalog_source(), PgCatalogSource)


def test_不認得的值直接報錯(monkeypatch):
    monkeypatch.setenv("CATALOG_SOURCE", "mysql")
    with pytest.raises(RuntimeError, match="csv 或 pg"):
        get_catalog_source()
