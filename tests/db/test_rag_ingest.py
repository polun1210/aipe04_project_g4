"""ingest：寫入 evidence.chunks、冪等、換型號重算、文件改了換掉舊塊。用假 embedder，不打外部 API。"""

from pathlib import Path

import pytest

from app.catalog_source import CsvCatalogSource
from app.rag.corpus import describe_document, discover_documents
from app.rag.ingest import ingest_corpus
from tests.fake_embedder import BagOfWordsEmbedder

B64 = "![x](data:image/png;base64," + "QUJD" * 200 + ")"
CALCIUM = """# Calcium

## Introduction

Calcium builds bones.

## Interactions with Medications

### Levothyroxine

Calcium carbonate may reduce levothyroxine absorption. Separate doses by 4 hours.
"""
LABEL_HEADER = (
    "<!-- 來源：TFDA 藥品仿單（衛生福利部食品藥物管理署）\n許可證字號：{lic}\n原始檔名：{lic}_20261019.md\n"
    "抓取日期：2026-10-19\n有效成分：{code}\n處理：已移除內嵌圖片，內文照原檔 -->\n\n"
)


def write(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def register(db, sources: Path) -> None:
    """模擬 import_catalog：把 sources 底下的文件登記到 catalog.source_documents。"""
    for d in discover_documents(sources, CsvCatalogSource().load()):
        db.execute(
            "INSERT INTO catalog.source_documents (document_id, source, title, url, jurisdiction, retrieved_at, "
            "source_version, file_path) VALUES (%s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
            describe_document(d).as_tuple(),
        )


def ingest(db, sources: Path, embedder=None):
    register(db, sources)
    return ingest_corpus(db, embedder or BagOfWordsEmbedder(), sources)


def rows(db, where="true", params=()):
    return db.execute(
        "SELECT chunk_id, document_id, section, start_line, end_line, ingredient_codes, text, embedding_model "
        f"FROM evidence.chunks WHERE {where} ORDER BY chunk_id",
        params,
    ).fetchall()


@pytest.fixture
def sources(tmp_path: Path) -> Path:
    write(tmp_path, "nih_ods/Calcium-HealthProfessional.md", CALCIUM)
    write(tmp_path, "nccih/RedYeastRice-NCCIH.md", "# Red Yeast Rice\n\n## Safety\n\nMonacolin K equals lovastatin.\n")
    return tmp_path


def test_chunks_record_metadata_traceable_to_the_source_file(db, sources):
    ingest(db, sources)

    (row,) = rows(db, "section = %s", ("Interactions with Medications > Levothyroxine",))
    _id, document_id, _section, start_line, end_line, codes, text, model = row
    assert document_id == "nih_ods/Calcium-HealthProfessional.md"
    assert codes == ["calcium"]
    assert model == "fake-bow"
    lines = (sources / document_id).read_text(encoding="utf-8").splitlines()
    assert "\n".join(lines[start_line - 1 : end_line]) == text


def test_rerun_is_idempotent_and_does_not_reembed(db, sources):
    ingest(db, sources)
    before = rows(db)

    second = BagOfWordsEmbedder()
    result = ingest_corpus(db, second, sources)

    assert rows(db) == before
    assert second.embedded == []
    assert (result.added, result.removed) == (0, 0)


def test_new_document_only_embeds_the_new_chunks(db, sources):
    ingest(db, sources)
    count = len(rows(db))
    write(sources, "nih_ods/Zinc-HealthProfessional.md", "# Zinc\n\n## Interactions with Medications\n\nZinc binds quinolones.\n")

    embedder = BagOfWordsEmbedder()
    result = ingest(db, sources, embedder)

    assert result.added == 1 and len(embedder.embedded) == 1
    assert len(rows(db)) == count + 1
    assert rows(db, "ingredient_codes = %s", (["zinc"],))


def test_changed_document_replaces_stale_chunks(db, sources):
    ingest(db, sources)
    write(sources, "nih_ods/Calcium-HealthProfessional.md", CALCIUM.replace("4 hours", "6 hours"))

    ingest_corpus(db, BagOfWordsEmbedder(), sources)

    texts = [r[6] for r in rows(db, "document_id = %s", ("nih_ods/Calcium-HealthProfessional.md",))]
    assert any("6 hours" in t for t in texts)
    assert not any("4 hours" in t for t in texts)


def test_removed_document_loses_its_chunks(db, sources):
    ingest(db, sources)
    (sources / "nccih" / "RedYeastRice-NCCIH.md").unlink()

    ingest_corpus(db, BagOfWordsEmbedder(), sources)

    assert not rows(db, "document_id LIKE %s", ("nccih/%",))


def test_changing_the_embedding_model_recomputes_every_chunk(db, sources):
    ingest(db, sources, BagOfWordsEmbedder("model-a"))
    count = len(rows(db))

    embedder = BagOfWordsEmbedder("model-b")
    ingest_corpus(db, embedder, sources)

    assert {r[7] for r in rows(db)} == {"model-b"}
    assert len(embedder.embedded) == count


def test_tfda_label_is_tagged_by_folder_and_has_no_images(db, tmp_path):
    header = LABEL_HEADER.format(lic="衛署藥輸字第000001號", code="atorvastatin")
    write(tmp_path, "tfda/atorvastatin/衛署藥輸字第000001號.md", f"{header}【交互作用】\n與葡萄柚汁併用。\n{B64}\n")

    ingest(db, tmp_path)

    found = rows(db, "document_id LIKE %s", ("tfda/%",))
    assert {tuple(r[5]) for r in found} == {("atorvastatin",)}
    assert not any("base64" in r[6] for r in found)
    assert "交互作用" in {r[2] for r in found}


def test_dris_chunks_are_tagged_by_the_nutrients_they_mention(db, tmp_path):
    write(tmp_path, "dris/notes.md", "# DRIs\n\n## UL\n\n鈣的 UL 是每日 2500 毫克。\n\n## 其他\n\n水分沒有 UL。\n")

    ingest(db, tmp_path)

    by_section = {r[2]: r[5] for r in rows(db)}
    assert by_section["UL"] == ["calcium"]
    assert by_section["其他"] == []


def test_nul_in_source_becomes_replacement_char(db, tmp_path):
    write(tmp_path, "nih_ods/Zinc-HealthProfessional.md", "# Zinc\n\n## Intro\n\nMIC \x002 mcg/mL\n")

    ingest(db, tmp_path)

    texts = [r[6] for r in rows(db)]
    assert any("MIC �2 mcg/mL" in t for t in texts)
    assert not any("\x00" in t for t in texts)


def test_document_not_registered_in_the_catalog_is_an_error(db, tmp_path):
    write(tmp_path, "nccih/Zinc-NCCIH.md", "# Zinc\n\n## A\n\ntext\n")  # 真實語料沒有這份，catalog 沒登記
    with pytest.raises(RuntimeError, match="import_catalog"):
        ingest_corpus(db, BagOfWordsEmbedder(), tmp_path)


class _FailsOnSecondBatch(BagOfWordsEmbedder):
    def __init__(self) -> None:
        super().__init__()
        self.batches = 0

    def embed(self, texts):
        self.batches += 1
        if self.batches == 2:
            raise RuntimeError("429")
        return super().embed(texts)


def test_failure_mid_document_writes_none_of_that_document(db, tmp_path):
    sections = "".join(f"## Part {i}\n\nZinc fact {i}.\n\n" for i in range(70))
    write(tmp_path, "nih_ods/Zinc-HealthProfessional.md", "# Zinc\n\n" + sections)
    register(db, tmp_path)

    with pytest.raises(RuntimeError):
        ingest_corpus(db, _FailsOnSecondBatch(), tmp_path)

    assert rows(db, "document_id = %s", ("nih_ods/Zinc-HealthProfessional.md",)) == []


def test_import_catalog_registers_every_file_under_data_sources(db):
    """引文沒引用到的文件（其他營養素、DRIs、仿單）也要有 source_documents，RAG 切塊才有地方指。"""
    from app.rag.corpus import SOURCES_DIR

    expected = {p.relative_to(SOURCES_DIR).as_posix() for p in SOURCES_DIR.rglob("*.md")}
    registered = {r[0] for r in db.execute("SELECT document_id FROM catalog.source_documents")}
    assert expected <= registered

    tfda = db.execute(
        "SELECT DISTINCT source, jurisdiction FROM catalog.source_documents WHERE document_id LIKE 'tfda/%'"
    ).fetchall()
    assert tfda == [("tfda_label", "TW")]
