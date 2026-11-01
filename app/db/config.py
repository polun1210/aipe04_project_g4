"""連線字串。預設值下不需要資料庫（CATALOG_SOURCE=csv、STORE=memory）。"""

import os


def database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("需要資料庫時請在 .env 設定 DATABASE_URL（見 docs/database.md）")
    return url


def sqlalchemy_url(url: str) -> str:
    """alembic 走 SQLAlchemy，指定使用 psycopg 3 驅動。"""
    return url.replace("postgresql://", "postgresql+psycopg://", 1)
