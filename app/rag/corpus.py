"""語料探索：掃描 data/sources/ 下要 ingest 的文件，判定來源類型、成分標記，並整理成 source_documents 的一列。

文件代碼（document_id）＝相對 data/sources/ 的路徑（用 / 分隔），與 citations.document_path 相同。
成分標記：NIH ODS／NCCIH 依檔名；TFDA 仿單依資料夾名稱（有效成分代碼）；DRIs 依段落中的成分名稱（逐塊判定）。
"""

import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from app.schemas.catalog import CatalogResponse
from app.schemas.enums import CitationSource, Jurisdiction

SOURCES_DIR = Path(__file__).resolve().parents[2] / "data" / "sources"
# NIH ODS 與 DRIs 檔案本身沒有抓取日期，沿用 scripts/convert_reference.py 的 RETRIEVED_AT（同一批轉檔）
UNDATED_RETRIEVED_AT = date(2026, 10, 19)

_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z])(?=[A-Z])")
_NIH_VERSION = re.compile(r"^\*\*(?:Last )?Updated:\*\*\s*(.+?)(?:\s*\[.*)?$", re.MULTILINE)
_NCCIH_HEADER = re.compile(r"^<!--\s*來源：(?P<url>\S+?)（.*?抓取日期\s*(?P<date>\d{4}-\d{2}-\d{2})")
_TFDA_HEADER = re.compile(r"^(許可證字號|原始檔名|抓取日期|有效成分)：(.+)$", re.MULTILINE)
_TITLE = re.compile(r"^# (.+)$", re.MULTILINE)


@dataclass(frozen=True)
class SourceFile:
    document_id: str
    path: Path
    source: CitationSource
    ingredients: tuple[str, ...]  # 文件層級的成分／有效成分代碼；空 ＝ 逐塊判定
    tag_by_content: bool

    @property
    def name(self) -> str:
        return self.path.name


@dataclass(frozen=True)
class DocumentRow:
    """catalog.source_documents 的一列。"""

    document_id: str
    source: CitationSource
    title: str
    url: str | None
    jurisdiction: Jurisdiction
    retrieved_at: date
    source_version: str | None

    def as_tuple(self) -> tuple[object, ...]:
        """對齊 import_catalog 的 source_documents 欄位順序（最後一欄 file_path 同 document_id）。"""
        return (self.document_id, self.source.value, self.title, self.url, self.jurisdiction.value,
                self.retrieved_at.isoformat(), self.source_version, self.document_id)  # fmt: skip


def normalize_name(name: str) -> str:
    """名稱比對用：NFKC 正規化、去空白、忽略大小寫（NFKC 會把 DRIs 表裡的康熙部首「⽣」還原成「生」）。"""
    return "".join(unicodedata.normalize("NFKC", name).split()).casefold()


def discover_documents(sources_dir: Path, catalog: CatalogResponse) -> list[SourceFile]:
    """掃出 sources_dir 下所有要 ingest 的文件，順序固定。找不到成分對應時直接報錯，不默默略過。"""
    names = {normalize_name(s): i.code.value for i in catalog.ingredients for s in (i.display_name_zh, *i.synonyms)}
    drug_codes = {d.active_ingredient_code for d in catalog.drug_items}
    found: list[SourceFile] = []
    for path in sorted((sources_dir / "dris").glob("*.md")):
        found.append(_file(sources_dir, path, CitationSource.DRIS_TW, (), True))
    for folder, source in (("nih_ods", CitationSource.NIH_ODS), ("nccih", CitationSource.NCCIH)):
        for path in sorted((sources_dir / folder).glob("*.md")):
            found.append(_file(sources_dir, path, source, (_code_from_filename(path.stem, names),), False))
    for path in sorted((sources_dir / "tfda").glob("*/*.md")):
        code = path.parent.name
        if code not in drug_codes:
            raise ValueError(f"{path}：資料夾名稱 {code!r} 不是 drug_items 的有效成分代碼")
        found.append(_file(sources_dir, path, CitationSource.TFDA_LABEL, (code,), False))
    return found


def _file(sources_dir: Path, path: Path, source: CitationSource, ingredients: tuple[str, ...], by_content: bool) -> SourceFile:
    return SourceFile(path.relative_to(sources_dir).as_posix(), path, source, ingredients, by_content)


def _code_from_filename(stem: str, names: dict[str, str]) -> str:
    """`VitaminB12-HealthProfessional` → vitamin_b12；找不到對應就報錯。"""
    name = _CAMEL_BOUNDARY.sub(" ", stem.split("-")[0])
    code = names.get(normalize_name(name))
    if code is None:
        raise ValueError(f"檔名 {stem!r} 對應不到任何成分（試過 {name!r}）；請改檔名或補同義詞")
    return code


def ingredients_mentioned(text: str, catalog: CatalogResponse) -> tuple[str, ...]:
    """DRIs 沒有逐成分的檔案：以成分顯示名稱與同義詞是否出現在段落中標記。"""
    haystack = normalize_name(text)
    return tuple(
        i.code.value
        for i in catalog.ingredients
        if any(normalize_name(n) in haystack for n in (i.display_name_zh, *i.synonyms))
    )


def describe_document(document: SourceFile) -> DocumentRow:
    """從檔案內容整理出 source_documents 的一列（沒有引文可參考的文件用）。"""
    text = document.path.read_text(encoding="utf-8")
    title_match = _TITLE.search(text)
    first_line = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    title = title_match[1].strip() if title_match else (first_line[:80] or document.path.stem)
    if document.source is CitationSource.NIH_ODS:
        version = _NIH_VERSION.search(text)
        return DocumentRow(
            document.document_id, document.source, title,
            f"https://ods.od.nih.gov/factsheets/{document.path.stem}/", Jurisdiction.US,
            UNDATED_RETRIEVED_AT, f"Updated: {version[1]}" if version else None,
        )  # fmt: skip
    if document.source is CitationSource.NCCIH:
        header = _NCCIH_HEADER.match(text)
        version = _NIH_VERSION.search(text)
        return DocumentRow(
            document.document_id, document.source, title,
            header["url"] if header else None, Jurisdiction.US,
            date.fromisoformat(header["date"]) if header else UNDATED_RETRIEVED_AT,
            f"Updated: {version[1]}" if version else None,
        )  # fmt: skip
    if document.source is CitationSource.TFDA_LABEL:
        fields = dict(_TFDA_HEADER.findall(text[:600]))
        if not {"許可證字號", "原始檔名", "抓取日期"} <= fields.keys():
            raise ValueError(f"{document.document_id} 缺少檔頭（許可證字號、原始檔名、抓取日期）")
        return DocumentRow(
            document.document_id, document.source,
            f"{fields['許可證字號']} 仿單（{document.ingredients[0]}）", None, Jurisdiction.TW,
            date.fromisoformat(fields["抓取日期"]), fields["原始檔名"],
        )  # fmt: skip
    return DocumentRow(
        document.document_id, document.source, title, None, Jurisdiction.TW, UNDATED_RETRIEVED_AT, None
    )
