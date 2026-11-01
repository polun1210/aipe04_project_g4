"""資料庫測試夾具。沒設 DATABASE_URL 就整組略過。

測試用另一個資料庫（原名稱加 _test），每次測試程序開始時砍掉重建，不會動到開發用的資料。
"""

import os
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg import sql

from app.db.config import sqlalchemy_url
from app.db.import_catalog import import_catalog

ROOT = Path(__file__).resolve().parents[1]


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if "tests/db/" in item.nodeid.replace("\\", "/"):
            item.add_marker(pytest.mark.db)


def _recreate_database(admin_url: str, name: str) -> None:
    if not name.endswith("_test"):  # 防呆：只准砍測試用資料庫
        raise RuntimeError(f"拒絕重建資料庫 {name!r}：測試資料庫名稱須以 _test 結尾")
    with psycopg.connect(admin_url, autocommit=True) as conn:
        conn.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name)))
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))


@pytest.fixture(scope="session")
def test_database_url() -> Iterator[str]:
    base = os.environ.get("DATABASE_URL")
    if not base:
        pytest.skip("沒設 DATABASE_URL，略過資料庫測試")
    parts = urlsplit(base)
    name = parts.path.lstrip("/") + "_test"
    _recreate_database(base, name)
    url = urlunsplit(parts._replace(path=f"/{name}"))
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    config.attributes["url"] = sqlalchemy_url(url)
    command.upgrade(config, "head")
    import_catalog(url)
    yield url


@pytest.fixture
def db(test_database_url: str) -> Iterator[psycopg.Connection]:
    """每個測試一條連線、一個交易，結束時 rollback，測試之間互不影響。"""
    with psycopg.connect(test_database_url) as conn:
        yield conn
        conn.rollback()
