"""語料 ingest：去圖、切塊、產生 embedding，寫入 evidence.chunks（冪等）。

    uv run python -m app.rag.ingest

前置：資料庫已 `alembic upgrade head`，且已跑過 `python -m app.db.import_catalog`
（切塊指向 catalog.source_documents，import_catalog 會把 data/sources/ 的每份文件都建一列）。
環境變數：EMBEDDING_MODEL（必填）、OPENROUTER_API_KEY、DATABASE_URL。

切塊 ID 由「文件路徑＋章節＋內容」雜湊而來：重跑時只替新增的塊算 embedding，
文件改過就換掉舊塊，文件被移走就刪掉它的塊。換 EMBEDDING_MODEL 會讓舊型號的塊整批重算。
"""

import hashlib
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import psycopg

from app.catalog_source import CsvCatalogSource
from app.rag.chunking import NUL, REPLACEMENT_CHAR, Chunk, chunk_markdown, strip_base64_images
from app.rag.corpus import SOURCES_DIR, SourceFile, discover_documents, ingredients_mentioned
from app.rag.embedder import Embedder
from app.schemas.catalog import CatalogResponse

EMBED_BATCH_SIZE = 64
MAX_EMBED_CHARS = 2000
_MD_LINK_TARGET = re.compile(r"\]\([^)]*\)")
# 參考文獻、免責聲明不是證據，不進索引。
_NOISE_SECTIONS = frozenset({"references", "disclaimer", "top"})


@dataclass(frozen=True)
class IngestResult:
    documents: int
    added: int
    removed: int


@dataclass(frozen=True)
class _PreparedChunk:
    chunk_id: str
    chunk: Chunk
    ingredient_codes: tuple[str, ...]


def chunk_id(document_id: str, section: str, text: str) -> str:
    """穩定 ID：同一份文件、同一章節、同樣內容永遠得到同一個 ID。"""
    digest = hashlib.sha1(f"{document_id}\0{section}\0{text}".encode()).hexdigest()
    return f"ev-{digest[:16]}"


def vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(repr(float(v)) for v in vector) + "]"


def ingest_corpus(
    conn: psycopg.Connection,
    embedder: Embedder,
    sources_dir: Path = SOURCES_DIR,
    catalog: CatalogResponse | None = None,
) -> IngestResult:
    catalog = catalog or CsvCatalogSource().load()
    documents = discover_documents(Path(sources_dir), catalog)
    added = removed = 0
    for document in documents:
        prepared = _prepare(document, catalog)
        # 每份文件一個交易：中途失敗不留半份；搭配 autocommit 連線，重跑從下一份接著做。
        with conn.transaction():
            _require_registered(conn, document)
            existing = dict(
                conn.execute(
                    "SELECT chunk_id, embedding_model FROM evidence.chunks WHERE document_id = %s",
                    (document.document_id,),
                ).fetchall()
            )
            wanted = {p.chunk_id for p in prepared}
            kept = {cid for cid, model in existing.items() if model == embedder.model and cid in wanted}
            new = [p for p in prepared if p.chunk_id not in kept]
            drop = sorted(set(existing) - kept)  # 文件已改掉的舊塊，加上舊型號算的塊
            if drop:
                conn.execute("DELETE FROM evidence.chunks WHERE chunk_id = ANY(%s)", (drop,))
            _insert(conn, embedder, document, new)
        added += len(new)
        removed += len(drop)
    removed += _remove_vanished_documents(conn, [d.document_id for d in documents])
    return IngestResult(documents=len(documents), added=added, removed=removed)


def _require_registered(conn: psycopg.Connection, document: SourceFile) -> None:
    row = conn.execute(
        "SELECT 1 FROM catalog.source_documents WHERE document_id = %s", (document.document_id,)
    ).fetchone()
    if row is None:
        raise RuntimeError(
            f"{document.document_id} 還沒登記在 catalog.source_documents；請先跑 uv run python -m app.db.import_catalog"
        )


def _remove_vanished_documents(conn: psycopg.Connection, document_ids: list[str]) -> int:
    cur = conn.execute("DELETE FROM evidence.chunks WHERE document_id <> ALL(%s)", (document_ids,))
    return cur.rowcount


def _prepare(document: SourceFile, catalog: CatalogResponse) -> list[_PreparedChunk]:
    text = strip_base64_images(document.path.read_text(encoding="utf-8").replace(NUL, REPLACEMENT_CHAR))
    seen: set[str] = set()
    prepared: list[_PreparedChunk] = []
    for chunk in chunk_markdown(text):
        if chunk.section.split(" > ")[0].strip().lower() in _NOISE_SECTIONS:
            continue
        cid = chunk_id(document.document_id, chunk.section, chunk.text)
        if cid in seen:  # 同文件內完全相同的段落只留一份
            continue
        seen.add(cid)
        codes = ingredients_mentioned(chunk.text, catalog) if document.tag_by_content else document.ingredients
        prepared.append(_PreparedChunk(cid, chunk, tuple(codes)))
    return prepared


def _embedding_input(document: SourceFile, chunk: Chunk) -> str:
    body = _MD_LINK_TARGET.sub("]", chunk.text)
    return f"{document.name} / {chunk.section}\n{body}"[:MAX_EMBED_CHARS]


def _insert(conn: psycopg.Connection, embedder: Embedder, document: SourceFile, prepared: list[_PreparedChunk]) -> None:
    for offset in range(0, len(prepared), EMBED_BATCH_SIZE):
        batch = prepared[offset : offset + EMBED_BATCH_SIZE]
        vectors = embedder.embed([_embedding_input(document, p.chunk) for p in batch])
        if len(vectors) != len(batch):
            raise RuntimeError("embedding 數量與切塊數量不符")
        for item, vector in zip(batch, vectors, strict=True):
            conn.execute(
                "INSERT INTO evidence.chunks (chunk_id, document_id, section, start_line, end_line, "
                "ingredient_codes, text, embedding, embedding_model) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s::vector, %s)",
                (
                    item.chunk_id, document.document_id, item.chunk.section, item.chunk.start_line,
                    item.chunk.end_line, list(item.ingredient_codes), item.chunk.text,
                    vector_literal(vector), embedder.model,
                ),
            )  # fmt: skip


def main() -> int:
    from dotenv import load_dotenv

    from app.db.config import database_url
    from app.rag.embedder import embedder_from_env

    load_dotenv()
    embedder = embedder_from_env()
    with psycopg.connect(database_url(), autocommit=True) as conn:
        result = ingest_corpus(conn, embedder)
    print(f"型號 {embedder.model}：文件 {result.documents} 份，新增 {result.added} 塊，移除 {result.removed} 塊")
    return 0


if __name__ == "__main__":
    sys.exit(main())
