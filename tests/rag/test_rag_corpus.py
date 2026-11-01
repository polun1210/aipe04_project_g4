"""data/sources/ 的真實語料：每份文件都找得到成分標記、有 source_documents 資訊，仿單大小在預算內。"""

import re
from datetime import date

import pytest

from app.catalog_source import CsvCatalogSource
from app.rag.chunking import strip_base64_images
from app.rag.corpus import SOURCES_DIR, describe_document, discover_documents, ingredients_mentioned
from app.schemas.enums import CitationSource

TFDA_BUDGET_BYTES = 10 * 1024 * 1024


@pytest.fixture(scope="module")
def catalog():
    return CsvCatalogSource().load()


@pytest.fixture(scope="module")
def documents(catalog):
    return discover_documents(SOURCES_DIR, catalog)


def test_every_source_file_is_discovered(documents):
    on_disk = {p.relative_to(SOURCES_DIR).as_posix() for p in SOURCES_DIR.rglob("*.md")}
    assert {d.document_id for d in documents} == on_disk


def test_nih_and_nccih_files_are_tagged_by_filename(documents):
    tags = {d.document_id: d.ingredients for d in documents}
    assert tags["nih_ods/VitaminB12-HealthProfessional.md"] == ("vitamin_b12",)
    assert tags["nccih/RedYeastRice-NCCIH.md"] == ("red_yeast_rice",)
    assert tags["nccih/FishOil-NCCIH.md"] == ("omega_3",)


def test_tfda_labels_are_tagged_by_folder_and_are_in_drug_items(documents, catalog):
    drug_codes = {d.active_ingredient_code for d in catalog.drug_items}
    labels = [d for d in documents if d.source is CitationSource.TFDA_LABEL]
    assert len(labels) >= 30
    assert all(d.ingredients == (d.path.parent.name,) and d.ingredients[0] in drug_codes for d in labels)


def test_one_label_per_active_ingredient(documents):
    folders = [d.path.parent.name for d in documents if d.source is CitationSource.TFDA_LABEL]
    assert len(folders) == len(set(folders))


def test_tfda_labels_have_no_base64_images_and_fit_the_budget(documents):
    labels = [d for d in documents if d.source is CitationSource.TFDA_LABEL]
    total = 0
    for d in labels:
        text = d.path.read_text(encoding="utf-8")
        assert strip_base64_images(text) == text
        assert "data:image" not in text
        total += d.path.stat().st_size
    assert total <= TFDA_BUDGET_BYTES


def test_tfda_header_gives_license_original_name_and_fetch_date(documents):
    label = next(d for d in documents if d.document_id == "tfda/metformin/衛署藥輸字第007152號.md")
    row = describe_document(label)
    assert row.title.startswith("衛署藥輸字第007152號")
    assert row.source_version == "衛署藥輸字第007152號_20261019.md"
    assert row.retrieved_at == date(2026, 10, 19)


def test_every_document_can_be_described(documents):
    for d in documents:
        row = describe_document(d)
        assert row.title and row.document_id == d.document_id


def test_uncited_nih_document_gets_url_and_version(documents):
    zinc_like = next(d for d in documents if d.document_id == "nih_ods/VitaminC-HealthProfessional.md")
    row = describe_document(zinc_like)
    assert row.url == "https://ods.od.nih.gov/factsheets/VitaminC-HealthProfessional/"
    assert re.match(r"Updated: \w+ \d+, \d{4}", row.source_version or "")


def test_dris_text_is_tagged_by_the_nutrients_it_mentions(catalog):
    found = ingredients_mentioned("維⽣素D(7) 鈣 AI=1000 鐵", catalog)  # 表裡的「⽣」是康熙部首
    assert set(found) == {"vitamin_d", "calcium", "iron"}


def test_unknown_file_name_is_an_error(tmp_path, catalog):
    (tmp_path / "nih_ods").mkdir()
    (tmp_path / "nih_ods" / "Unobtainium-HealthProfessional.md").write_text("# x\n", encoding="utf-8")
    with pytest.raises(ValueError, match="對應不到"):
        discover_documents(tmp_path, catalog)


def test_unknown_tfda_folder_is_an_error(tmp_path, catalog):
    (tmp_path / "tfda" / "not_a_drug").mkdir(parents=True)
    (tmp_path / "tfda" / "not_a_drug" / "X.md").write_text("# x\n", encoding="utf-8")
    with pytest.raises(ValueError, match="不是 drug_items"):
        discover_documents(tmp_path, catalog)
