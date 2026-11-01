"""pgvector 與三個 schema：catalog（醫療參考資料）、app（使用者資料）、evidence（RAG 語料）。

Revision ID: 0001
Revises:
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    for schema in ("catalog", "app", "evidence"):
        op.execute(f"CREATE SCHEMA {schema}")


def downgrade() -> None:
    for schema in ("evidence", "app", "catalog"):
        op.execute(f"DROP SCHEMA {schema} CASCADE")
