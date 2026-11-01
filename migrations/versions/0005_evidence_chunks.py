"""evidence.chunks：RAG 語料切塊與向量（C-2 寫入）。

embedding 不固定維度（ADR-0003：4096 維超過 pgvector 近似索引上限，所以不建向量索引，
先用成分標籤篩選再算距離，循序掃描就夠快）。引文與切塊指向同一張 catalog.source_documents。

Revision ID: 0005
Revises: 0004
"""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE TABLE evidence.chunks ("
        "chunk_id text PRIMARY KEY, "
        "document_id text NOT NULL REFERENCES catalog.source_documents, "
        "section text NOT NULL, "
        "start_line int NOT NULL, "
        "end_line int NOT NULL, "
        "ingredient_codes text[] NOT NULL DEFAULT '{}', "
        "text text NOT NULL, "
        "embedding vector NOT NULL, "
        "embedding_model text NOT NULL)"
    )
    op.execute("CREATE INDEX chunks_ingredient_codes_idx ON evidence.chunks USING gin (ingredient_codes)")
    op.execute("CREATE INDEX chunks_document_idx ON evidence.chunks (document_id)")


def downgrade() -> None:
    op.execute("DROP TABLE evidence.chunks")
