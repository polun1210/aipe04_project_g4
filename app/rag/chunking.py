"""語料切塊：移除 base64 圖片，依文件章節標題切成可回溯到原文的段落。"""

import re
from dataclasses import dataclass

DEFAULT_MAX_CHARS = 1500
PREAMBLE_SECTION = "(前言)"
NUL = chr(0)  # PostgreSQL text 欄位不接受 NUL
# 轉檔把符號（例如「≧」）弄丟時會留下 NUL；換成替代字元而不是刪掉，引用時看得出此處缺字。
REPLACEMENT_CHAR = "�"

_BASE64_IMAGE = re.compile(r"!\[[^\]]*\]\(\s*data:[^)]*\)|data:image/[a-zA-Z+.-]+;base64,[A-Za-z0-9+/=]+")
_MD_HEADING = re.compile(r"^(#{1,6})\s+(\S.*?)\s*#*\s*$")
_BRACKET_HEADING = re.compile(r"^[【\[]\s*([^】\]\n]{1,30}?)\s*[】\]]\s*$")
_PARAGRAPH_BREAK = re.compile(r"\n\s*\n")


@dataclass(frozen=True)
class Chunk:
    section: str
    text: str
    start: int  # 在傳入文字中的字元位置 [start, end)
    end: int
    start_line: int  # 1-based，含
    end_line: int


def strip_base64_images(text: str) -> str:
    """移除 base64 圖片資料；只在行內刪除，不動換行，所以行號與原檔一致。"""
    return _BASE64_IMAGE.sub("", text)


def chunk_markdown(text: str, max_chars: int = DEFAULT_MAX_CHARS) -> list[Chunk]:
    chunks: list[Chunk] = []
    for section, body_start, body_end in _sections(text):
        for start, end in _split_body(text, body_start, body_end, max_chars):
            chunks.append(_make_chunk(text, section, start, end))
    return chunks


def _sections(text: str) -> list[tuple[str, int, int]]:
    """回傳 (章節路徑, 內文起點, 內文終點)。第 1 層標題視為文件標題，不進路徑。"""
    path: list[tuple[int, str]] = []
    result: list[tuple[str, int, int]] = []
    current = PREAMBLE_SECTION
    body_start = 0
    offset = 0
    for line in text.splitlines(keepends=True):
        heading = _parse_heading(line.strip())
        if heading is not None:
            result.append((current, body_start, offset))
            level, title = heading
            path = [(lv, t) for lv, t in path if lv < level]
            if level > 1:
                path.append((level, title))
            current = " > ".join(t for _, t in path) or PREAMBLE_SECTION
            body_start = offset + len(line)
        offset += len(line)
    result.append((current, body_start, offset))
    return result


def _parse_heading(line: str) -> tuple[int, str] | None:
    if match := _MD_HEADING.match(line):
        return len(match.group(1)), match.group(2)
    if match := _BRACKET_HEADING.match(line):
        return 2, match.group(1)
    return None


def _split_body(text: str, start: int, end: int, max_chars: int) -> list[tuple[int, int]]:
    """把內文依段落打包成不超過 max_chars 的區間；單一段落過長就硬切。"""
    paragraphs: list[tuple[int, int]] = []
    cursor = start
    for brk in _PARAGRAPH_BREAK.finditer(text, start, end):
        paragraphs.append((cursor, brk.start()))
        cursor = brk.end()
    paragraphs.append((cursor, end))

    spans: list[tuple[int, int]] = []
    group: tuple[int, int] | None = None
    for p_start, p_end in paragraphs:
        if not text[p_start:p_end].strip():
            continue
        for s, e in _hard_split(p_start, p_end, max_chars):
            if group is not None and e - group[0] <= max_chars:
                group = (group[0], e)
            else:
                if group is not None:
                    spans.append(group)
                group = (s, e)
    if group is not None:
        spans.append(group)
    return [_trim(text, s, e) for s, e in spans]


def _hard_split(start: int, end: int, max_chars: int) -> list[tuple[int, int]]:
    return [(s, min(s + max_chars, end)) for s in range(start, end, max_chars)]


def _trim(text: str, start: int, end: int) -> tuple[int, int]:
    segment = text[start:end]
    return start + len(segment) - len(segment.lstrip()), end - (len(segment) - len(segment.rstrip()))


def _make_chunk(text: str, section: str, start: int, end: int) -> Chunk:
    start_line = text.count("\n", 0, start) + 1
    end_line = start_line + text.count("\n", start, end)
    return Chunk(section, text[start:end], start, end, start_line, end_line)
