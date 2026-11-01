"""把 data/catalog/*.csv 匯入資料庫的 catalog schema。

    uv run python -m app.db.import_catalog

流程：先用 CsvCatalogSource（Pydantic 逐列驗證）讀進來，再在「一個交易」裡清空舊資料、寫入新資料、
記一筆 data_versions。中途失敗整批回滾；重跑結果相同（冪等，idempotent）。

known_conditions、ingredients、data_versions 會被 app 的表參照，source_documents 會被 evidence.chunks 參照，
所以用「更新或新增＋刪掉不在新資料裡的列」，不直接清空；其餘的表先全部清掉再寫入。

source_documents：引文引用的文件（屬性取自引文）加上 data/sources/ 裡沒被引用的文件（RAG 語料，屬性取自檔案內容）。
文件從 data/sources/ 移走時，它在 evidence.chunks 的切塊一併刪除；文件內容改了要重跑 app.rag.ingest。
"""

import argparse
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

import psycopg
from pydantic import BaseModel

from app.catalog_source import CATALOG_DIR, CsvCatalogSource
from app.rag.corpus import describe_document, discover_documents
from app.db.config import database_url
from app.schemas.reference import ReferenceData

SOURCES_DIR = CATALOG_DIR.parent / "sources"
# 清空順序：子表在前。known_conditions、ingredients 不在裡面（見模組說明）
_CLEAR_ORDER = (
    "rule_citations", "rules", "citations", "drug_product_ingredients",
    "drug_products", "drug_nutrient_doses", "drug_tradenames", "drug_item_conditions",
    "drug_item_classes", "drug_items", "drug_classes", "ingredient_synonyms", "dris_values",
    "compounds", "conversion_factors", "out_of_scope_names",
)  # fmt: skip
_BULK_COPY_THRESHOLD = 1000


def _rows(models: Iterable[BaseModel]) -> list[dict[str, Any]]:
    """模型 → 純 Python 值（列舉變字串、網址變字串、日期變 ISO 字串）。"""
    return [m.model_dump(mode="json") for m in models]


def _insert(cur: psycopg.Cursor, table: str, columns: Sequence[str], rows: Sequence[Sequence[Any]]) -> None:
    if not rows:
        return
    names = ", ".join(columns)
    marks = ", ".join(["%s"] * len(columns))
    if len(rows) >= _BULK_COPY_THRESHOLD:
        with cur.copy(f"COPY catalog.{table} ({names}) FROM STDIN") as copy:
            for row in rows:
                copy.write_row(row)
    else:
        cur.executemany(f"INSERT INTO catalog.{table} ({names}) VALUES ({marks})", rows)


def _upsert(cur: psycopg.Cursor, table: str, key: str, columns: Sequence[str], rows: list[Sequence[Any]]) -> None:
    sets = ", ".join(f"{c} = EXCLUDED.{c}" for c in columns if c != key)
    cur.executemany(
        f"INSERT INTO catalog.{table} ({', '.join(columns)}) VALUES ({', '.join(['%s'] * len(columns))}) "
        f"ON CONFLICT ({key}) DO UPDATE SET {sets}",
        rows,
    )
    cur.execute(f"DELETE FROM catalog.{table} WHERE {key} <> ALL(%s)", [[r[columns.index(key)] for r in rows]])


def _document_title(path: Path) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return path.stem


def _source_documents(ref: ReferenceData, sources_dir: Path) -> list[tuple[Any, ...]]:
    """引文的原文檔 → source_documents 一列一份文件。同一份文件的屬性必須一致。"""
    seen: dict[str, tuple[Any, ...]] = {}
    for c in ref.citations:
        if not c.document_path:
            raise ValueError(f"{c.citation_id} 沒有 document_path，無法建立 source_documents")
        path = sources_dir / c.document_path
        if not path.is_file():
            raise FileNotFoundError(f"{c.citation_id} 的原文檔不存在：{path}")
        attrs = (c.source.value, str(c.url) if c.url else None, c.jurisdiction.value, c.retrieved_at.isoformat(),
                 c.source_version)  # fmt: skip
        if seen.setdefault(c.document_path, attrs) != attrs:
            raise ValueError(f"同一份文件 {c.document_path} 的引文屬性不一致")
    return [
        (doc, a[0], _document_title(sources_dir / doc), a[1], a[2], a[3], a[4], doc) for doc, a in seen.items()
    ]


def _all_source_documents(ref: ReferenceData, sources_dir: Path) -> list[tuple[Any, ...]]:
    """被引文引用的文件，加上 data/sources/ 裡其餘的 RAG 語料文件。"""
    cited = _source_documents(ref, sources_dir)
    cited_ids = {row[0] for row in cited}
    extra = [
        describe_document(d).as_tuple()
        for d in discover_documents(sources_dir, ref.catalog)
        if d.document_id not in cited_ids
    ]
    return sorted([*cited, *extra], key=lambda row: row[0])


def _check_unique_synonyms(ref: ReferenceData) -> None:
    owner: dict[str, str] = {}
    for ing in ref.catalog.ingredients:
        for s in ing.synonyms:
            if owner.setdefault(s, ing.code.value) != ing.code.value:
                raise ValueError(f"同義詞「{s}」同時屬於 {owner[s]} 與 {ing.code.value}")


def _write(cur: psycopg.Cursor, ref: ReferenceData, products: list, sources_dir: Path) -> None:
    cat = ref.catalog
    docs = _all_source_documents(ref, sources_dir)
    _check_unique_synonyms(ref)

    cur.execute(
        "INSERT INTO catalog.data_versions (version, note) VALUES (%s, %s) "
        "ON CONFLICT (version) DO UPDATE SET imported_at = now(), note = EXCLUDED.note",
        [ref.version, "從 data/catalog/*.csv 匯入"],
    )
    for table in _CLEAR_ORDER:
        cur.execute(f"DELETE FROM catalog.{table}")

    conditions = _rows(cat.known_conditions)
    _upsert(cur, "known_conditions", "condition_code",
            ["condition_code", "display_name_zh", "backend_name", "sort_order", "ord"],
            [(r["condition_code"], r["display_name_zh"], r["backend_name"], r["sort_order"], i)
             for i, r in enumerate(conditions)])  # fmt: skip
    ingredients = _rows(cat.ingredients)
    _upsert(cur, "ingredients", "code",
            ["code", "category", "display_name_zh", "standard_unit", "accepted_units", "ul_scope", "ord"],
            [(r["code"], r["category"], r["display_name_zh"], r["standard_unit"], r["accepted_units"],
              r["ul_scope"], i) for i, r in enumerate(ingredients)])  # fmt: skip
    _insert(cur, "ingredient_synonyms", ["ingredient_code", "synonym"],
            [(r["code"], s) for r in ingredients for s in r["synonyms"]])  # fmt: skip

    classes = _rows(cat.drug_classes)
    _insert(cur, "drug_classes",
            ["drug_class_code", "condition_code", "display_name_zh", "plain_description_zh", "role", "menu_group", "ord"],
            [(r["drug_class_code"], None if r["menu_group"] == "gastrointestinal" else r["menu_group"],
              r["display_name_zh"], r["plain_description_zh"], r["role"], r["menu_group"], i)
             for i, r in enumerate(classes)])  # fmt: skip
    items = _rows(cat.drug_items)
    _insert(cur, "drug_items", ["active_ingredient_code", "display_name_zh", "english_name", "requires_dose", "ord"],
            [(r["active_ingredient_code"], r["display_name_zh"], r["english_name"], r["requires_dose"], i)
             for i, r in enumerate(items)])  # fmt: skip
    _insert(cur, "drug_item_classes", ["active_ingredient_code", "drug_class_code", "ord"],
            [(r["active_ingredient_code"], c, j) for r in items for j, c in enumerate(r["drug_class_codes"])])  # fmt: skip
    _insert(cur, "drug_item_conditions", ["active_ingredient_code", "condition_code", "ord"],
            [(r["active_ingredient_code"], c, j) for r in items for j, c in enumerate(r["related_conditions"])])  # fmt: skip
    _insert(cur, "drug_tradenames", ["active_ingredient_code", "tradename"],
            [(r["active_ingredient_code"], t) for r in items for t in r["common_tradenames_tw"]])  # fmt: skip
    _insert(cur, "drug_nutrient_doses",
            ["active_ingredient_code", "dose_option_mg", "nutrient_code", "elemental_mg_per_unit", "source", "ord"],
            [(r["active_ingredient_code"], r["dose_option_mg"], r["nutrient_code"], r["elemental_mg_per_unit"],
              r["source"], i) for i, r in enumerate(_rows(cat.drug_nutrient_doses))])  # fmt: skip

    prods = _rows(products)
    _insert(cur, "drug_products", ["product_id", "name", "lang", "out_of_scope_ingredients"],
            [(i, p["name"], p["lang"], p["out_of_scope_ingredients"]) for i, p in enumerate(prods, start=1)])  # fmt: skip
    _insert(cur, "drug_product_ingredients", ["product_id", "active_ingredient_code", "ord"],
            [(i, c, j) for i, p in enumerate(prods, start=1) for j, c in enumerate(p["active_ingredient_codes"])])  # fmt: skip

    _insert(cur, "out_of_scope_names", ["name", "note", "ord"],
            [(r["name"], r["note"], i) for i, r in enumerate(_rows(ref.out_of_scope_names))])  # fmt: skip
    _insert(cur, "dris_values",
            ["nutrient_code", "sex", "age_band", "reference_type", "reference_value", "ul_value", "unit", "ord"],
            [(r["nutrient_code"], r["sex"], r["age_band"], r["reference_type"], r["reference_value"],
              r["ul_value"], r["unit"], i) for i, r in enumerate(_rows(ref.dris_values))])  # fmt: skip
    _insert(cur, "compounds",
            ["compound_code", "nutrient_code", "display_name_zh", "synonyms", "formula", "ratio", "source", "ord"],
            [(r["compound_code"], r["nutrient_code"], r["display_name_zh"], r["synonyms"], r["formula"],
              r["ratio"], r["source"], i) for i, r in enumerate(_rows(ref.compounds))])  # fmt: skip
    _insert(cur, "conversion_factors",
            ["nutrient_code", "from_unit", "to_unit", "factor", "applies_to_form", "source"],
            [(r["nutrient_code"], r["from_unit"], r["to_unit"], r["factor"], r["applies_to_form"], r["source"])
             for r in _rows(ref.conversion_factors)])  # fmt: skip

    cur.execute("DELETE FROM evidence.chunks WHERE document_id <> ALL(%s)", [[d[0] for d in docs]])
    _upsert(cur, "source_documents", "document_id",
            ["document_id", "source", "title", "url", "jurisdiction", "retrieved_at", "source_version", "file_path"],
            docs)  # fmt: skip
    citations = _rows(ref.citations)
    _insert(cur, "citations", ["citation_id", "document_id", "section", "quote", "population", "source_record_id", "ord"],
            [(r["citation_id"], r["document_path"], r["section"], r["quote"], r["population"],
              r["source_record_id"], i) for i, r in enumerate(citations)])  # fmt: skip
    rules = _rows(ref.rules)
    _insert(cur, "rules",
            ["rule_id", "condition_type", "drug_class_code", "active_ingredient_code", "ingredient_code",
             "ingredient_form_codes", "interaction_type", "requires_supplement_intake",
             "requires_professional_review", "advice_code", "separation_hours", "reason_zh", "evidence_tier",
             "status", "curated_by", "reviewed_by", "reviewed_at", "curation_note", "data_version", "ord"],
            [(r["rule_id"], r["condition_type"],
              r["condition_code"] if r["condition_type"] == "drug_class" else None,
              r["condition_code"] if r["condition_type"] == "drug_ingredient" else None,
              r["ingredient_code"], r["ingredient_form_codes"], r["interaction_type"],
              r["requires_supplement_intake"], r["requires_professional_review"], r["advice_code"],
              r["separation_hours"], r["reason_zh"], r["evidence_tier"], r["status"], r["curated_by"],
              r["reviewed_by"], r["reviewed_at"], r["curation_note"], ref.version, i)
             for i, r in enumerate(rules)])  # fmt: skip
    _insert(cur, "rule_citations", ["rule_id", "citation_id", "ord"],
            [(r["rule_id"], c, j) for r in rules for j, c in enumerate(r["citation_ids"])])  # fmt: skip


def import_catalog(url: str, catalog_dir: Path = CATALOG_DIR, sources_dir: Path = SOURCES_DIR) -> str:
    """匯入並回傳參考資料版本。任何一步失敗都整批回滾。"""
    source = CsvCatalogSource(catalog_dir)
    ref = source.load_reference()
    products = source.load_drug_products()
    with psycopg.connect(url) as conn, conn.cursor() as cur:  # 離開 with 時 commit；例外則 rollback
        _write(cur, ref, products, sources_dir)
    return ref.version


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dir", type=Path, default=CATALOG_DIR, help="CSV 目錄（預設 data/catalog/）")
    args = parser.parse_args()
    version = import_catalog(database_url(), args.dir)
    print(f"已匯入參考資料版本 {version}")


if __name__ == "__main__":
    main()
