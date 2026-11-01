"""檢索：成分標記篩選、餘弦相似度排序、每份文件最多 2 段。假 embedder 只比字詞重疊，語意品質由 evals/rag 量。"""

from collections import Counter
from pathlib import Path

import pytest

from app.rag.search import MAX_CHUNKS_PER_DOCUMENT, retrieve_evidence
from tests.db.test_rag_ingest import LABEL_HEADER, ingest, write
from tests.fake_embedder import BagOfWordsEmbedder

LICENSE = "衛署藥輸字第000002號"


@pytest.fixture
def corpus(db, tmp_path: Path) -> Path:
    write(
        tmp_path, "nih_ods/Calcium-HealthProfessional.md",
        "# Calcium\n\n## Introduction\n\nCalcium builds bones and teeth.\n\n"
        "## Interactions with Medications\n\n### Thiazide diuretics\n\n"
        "Thiazide diuretics decrease urinary calcium excretion.\n",
    )  # fmt: skip
    write(
        tmp_path, "nih_ods/Zinc-HealthProfessional.md",
        "# Zinc\n\n## Interactions with Medications\n\nThiazide diuretics increase zinc excretion in the urine.\n",
    )  # fmt: skip
    header = LABEL_HEADER.format(lic=LICENSE, code="indapamide")
    write(
        tmp_path, f"tfda/indapamide/{LICENSE}.md",
        header + "【交互作用】\nIndapamide 與鈣劑併用，尿中鈣排出量減少。\n",
    )  # fmt: skip
    ingest(db, tmp_path)
    return tmp_path


def test_filters_by_ingredient_or_drug_then_ranks_by_similarity(db, corpus):
    results = retrieve_evidence(db, BagOfWordsEmbedder(), "calcium", ["indapamide"])

    assert results
    assert all("zinc" not in r.ingredient_codes for r in results)
    assert {r.source for r in results} == {"nih_ods", "tfda_label"}
    sims = [r.similarity for r in results]
    assert sims == sorted(sims, reverse=True)


def test_evidence_carries_what_a_footnote_needs(db, corpus):
    results = retrieve_evidence(db, BagOfWordsEmbedder(), "calcium", ["indapamide"])
    label = next(r for r in results if r.source == "tfda_label")

    assert label.document_id == f"tfda/indapamide/{LICENSE}.md"
    assert label.title.startswith(LICENSE)
    assert label.section == "交互作用"
    assert label.start_line <= label.end_line
    assert "尿中鈣排出量減少" in label.text


def test_chunk_ids_are_stable_across_reingest(db, corpus):
    embedder = BagOfWordsEmbedder()
    first = [r.chunk_id for r in retrieve_evidence(db, embedder, "calcium", ["indapamide"])]
    ingest(db, corpus)
    assert first == [r.chunk_id for r in retrieve_evidence(db, embedder, "calcium", ["indapamide"])]


def test_limit_caps_results(db, corpus):
    assert len(retrieve_evidence(db, BagOfWordsEmbedder(), "calcium", ["indapamide"], limit=1)) == 1


def test_ingredient_without_chunks_returns_nothing(db, corpus):
    assert retrieve_evidence(db, BagOfWordsEmbedder(), "selenium", []) == []


def test_only_chunks_from_the_same_embedding_model_are_compared(db, corpus):
    assert retrieve_evidence(db, BagOfWordsEmbedder("other-model"), "calcium", ["indapamide"]) == []


def test_one_long_label_cannot_fill_all_results(db, tmp_path):
    """仿單每段都含藥名；單一文件最多佔 2 段，不會把營養素文件的段落擠掉。"""
    header = LABEL_HEADER.format(lic=LICENSE, code="indapamide")
    label = "".join(f"【第{i}節】\nIndapamide 吲達帕胺 說明 {i}。\n\n" for i in range(10))
    write(tmp_path, f"tfda/indapamide/{LICENSE}.md", header + label)
    write(
        tmp_path, "nih_ods/Zinc-HealthProfessional.md",
        "# Zinc\n\n## Interactions with Medications\n\nThiazide diuretics increase zinc excretion in the urine.\n",
    )  # fmt: skip
    ingest(db, tmp_path)

    results = retrieve_evidence(db, BagOfWordsEmbedder(), "zinc", ["indapamide"], limit=3)

    per_document = Counter(r.document_id for r in results)
    assert per_document[f"tfda/indapamide/{LICENSE}.md"] == MAX_CHUNKS_PER_DOCUMENT
    assert "nih_ods/Zinc-HealthProfessional.md" in per_document


def test_few_documents_still_fill_the_limit(db, tmp_path):
    header = LABEL_HEADER.format(lic=LICENSE, code="indapamide")
    label = "".join(f"【第{i}節】\nIndapamide 吲達帕胺 說明 {i}。\n\n" for i in range(10))
    write(tmp_path, f"tfda/indapamide/{LICENSE}.md", header + label)
    ingest(db, tmp_path)

    assert len(retrieve_evidence(db, BagOfWordsEmbedder(), "zinc", ["indapamide"], limit=5)) == 5


def test_query_names_the_nutrient_drug_and_drug_class(db, corpus):
    embedder = BagOfWordsEmbedder()

    retrieve_evidence(db, embedder, "zinc", ["indapamide"])

    query = embedder.embedded[-1]
    for expected in ("鋅", "Zinc", "Indapamide", "吲達帕胺", "thiazide diuretic"):
        assert expected in query
