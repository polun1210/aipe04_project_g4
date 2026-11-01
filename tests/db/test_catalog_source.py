"""PgCatalogSource 與匯入腳本：同一份 CSV，資料庫版和 CSV 版回傳的東西要完全一樣。"""

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.catalog_source import CsvCatalogSource, get_catalog_source
from app.db import import_catalog as importer
from app.db.catalog_source import PgCatalogSource
from app.main import create_app


def test_資料庫版與CSV版回傳完全相同的參考資料(test_database_url):
    csv_source, pg_source = CsvCatalogSource(), PgCatalogSource(test_database_url)
    assert pg_source.load_reference() == csv_source.load_reference()
    assert pg_source.load() == csv_source.load()
    assert pg_source.load_citations() == csv_source.load_citations()


def test_資料庫版的藥名表與CSV版相同(test_database_url):
    assert PgCatalogSource(test_database_url).load_drug_products() == CsvCatalogSource().load_drug_products()


def test_GET_api_catalog_兩種來源回應相同(test_database_url):
    def fetch(source) -> dict:
        app = create_app()
        app.dependency_overrides[get_catalog_source] = lambda: source
        return TestClient(app).get("/api/catalog").json()

    assert fetch(PgCatalogSource(test_database_url)) == fetch(CsvCatalogSource())


def _counts(conn: psycopg.Connection) -> dict[str, int]:
    tables = [r[0] for r in conn.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'catalog'")]
    return {t: conn.execute(f"SELECT count(*) FROM catalog.{t}").fetchone()[0] for t in sorted(tables)}


def test_重跑匯入結果相同(test_database_url):
    with psycopg.connect(test_database_url) as conn:
        before = _counts(conn)
    importer.import_catalog(test_database_url)
    importer.import_catalog(test_database_url)
    with psycopg.connect(test_database_url) as conn:
        assert _counts(conn) == before
    assert PgCatalogSource(test_database_url).load_reference() == CsvCatalogSource().load_reference()


def test_匯入中途失敗整批回滾(test_database_url, monkeypatch):
    with psycopg.connect(test_database_url) as conn:
        before = _counts(conn)
    real_insert = importer._insert

    def failing_insert(cur, table, columns, rows):
        if table == "rules":  # 前面的表都已經清空、寫入了
            raise RuntimeError("模擬中途失敗")
        real_insert(cur, table, columns, rows)

    monkeypatch.setattr(importer, "_insert", failing_insert)
    with pytest.raises(RuntimeError, match="模擬中途失敗"):
        importer.import_catalog(test_database_url)
    with psycopg.connect(test_database_url) as conn:
        assert _counts(conn) == before


def test_表與view的數量與設計文件一致(db):
    def count(sql_text: str) -> int:
        return db.execute(sql_text).fetchone()[0]

    tables = "SELECT count(*) FROM pg_tables WHERE schemaname = %s"
    assert db.execute(tables, ["catalog"]).fetchone()[0] == 20
    assert db.execute(tables, ["app"]).fetchone()[0] == 12
    assert db.execute(tables, ["evidence"]).fetchone()[0] == 1
    assert count("SELECT count(*) FROM pg_views WHERE schemaname = 'catalog'") == 12
