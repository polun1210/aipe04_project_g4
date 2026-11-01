"""證據段落檢索：先用成分標記篩選，再依 embedding 餘弦相似度排序。只在系統內的語料找，不呼叫外部資料庫。"""

from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache

import psycopg

from app.catalog_source import CsvCatalogSource
from app.rag.embedder import Embedder
from app.rag.ingest import vector_literal
from app.schemas.catalog import CatalogResponse

DEFAULT_LIMIT = 8
MAX_CHUNKS_PER_DOCUMENT = 2


@dataclass(frozen=True)
class Evidence:
    chunk_id: str  # 穩定 ID；重跑 ingest 後不變
    document_id: str  # 相對 data/sources/，同 catalog.source_documents
    source: str  # nih_ods / nccih / dris_tw / tfda_label
    title: str
    url: str | None
    section: str
    start_line: int
    end_line: int
    ingredient_codes: tuple[str, ...]
    text: str
    similarity: float  # 餘弦相似度，越大越相近


_SQL = """
WITH ranked AS (
    SELECT c.chunk_id, c.document_id, d.source, d.title, d.url, c.section, c.start_line, c.end_line,
           c.ingredient_codes, c.text,
           1 - (c.embedding <=> %(vector)s::vector) AS similarity,
           row_number() OVER (PARTITION BY c.document_id ORDER BY c.embedding <=> %(vector)s::vector, c.chunk_id)
               AS rank_in_document
    FROM evidence.chunks c JOIN catalog.source_documents d USING (document_id)
    WHERE c.ingredient_codes && %(codes)s::text[] AND c.embedding_model = %(model)s
),
chosen AS (
    SELECT * FROM ranked ORDER BY rank_in_document > %(per_document)s, similarity DESC, chunk_id LIMIT %(limit)s
)
SELECT chunk_id, document_id, source, title, url, section, start_line, end_line, ingredient_codes, text, similarity
FROM chosen ORDER BY similarity DESC, chunk_id
"""


def retrieve_evidence(
    conn: psycopg.Connection,
    embedder: Embedder,
    ingredient_code: str,
    drug_ingredient_codes: Sequence[str],
    limit: int = DEFAULT_LIMIT,
) -> list[Evidence]:
    """替一個判定（成分＋藥）找證據段落。

    篩選：段落標記的成分或有效成分，至少有一個在 (成分, 藥) 之中；只比用同一個 embedding 型號算的塊。
    排序：與查詢文字的餘弦相似度。查詢文字列出成分、藥與藥物類別的中英文名稱，只寫類別的原文也找得到。
    入選：每份文件相似度前 MAX_CHUNKS_PER_DOCUMENT 段優先，名額有剩再依相似度補滿；
    仿單每段都提到藥名，不這樣分配會佔滿結果。回傳時依相似度排序。
    """
    (query_vector,) = embedder.embed([query_text(ingredient_code, drug_ingredient_codes)])
    rows = conn.execute(
        _SQL,
        {
            "vector": vector_literal(query_vector),
            "codes": [ingredient_code, *drug_ingredient_codes],
            "model": embedder.model,
            "per_document": MAX_CHUNKS_PER_DOCUMENT,
            "limit": limit,
        },
    ).fetchall()
    return [Evidence(*row[:8], tuple(row[8]), *row[9:]) for row in rows]


@lru_cache(maxsize=1)
def _catalog() -> CatalogResponse:
    return CsvCatalogSource().load()


def query_text(ingredient_code: str, drug_ingredient_codes: Sequence[str]) -> str:
    """成分的中文名與英文同義詞，藥的中英文名與類別；目錄外的代碼照原樣放入。"""
    catalog = _catalog()
    ingredients = {i.code.value: i for i in catalog.ingredients}
    drugs = {d.active_ingredient_code: d for d in catalog.drug_items}
    classes = {c.drug_class_code: c for c in catalog.drug_classes}
    parts: list[str] = []
    ingredient = ingredients.get(ingredient_code)
    if ingredient is None:
        parts.append(ingredient_code)
    else:
        parts.append(ingredient.display_name_zh)
        parts.extend(s for s in ingredient.synonyms if s.isascii())
    for code in drug_ingredient_codes:
        drug = drugs.get(code)
        if drug is None:
            parts.append(code)
            continue
        parts.extend([drug.english_name, drug.display_name_zh])
        for class_code in drug.drug_class_codes:
            drug_class = classes.get(class_code)
            parts.append(str(class_code).replace("_", " "))
            if drug_class:
                parts.append(drug_class.display_name_zh)
    return " ".join([*parts, "drug interaction 交互作用"])
