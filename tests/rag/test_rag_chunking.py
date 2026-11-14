from app.rag.chunking import (
    PREAMBLE_SECTION,
    chunk_markdown,
    is_residue_chunk,
    strip_base64_images,
    strip_boilerplate,
)
from app.rag.ingest import chunk_id

B64 = "![x](data:image/png;base64," + "QUJD" * 200 + ")"


def test_strips_base64_images_without_changing_line_numbers():
    text = f"# T\n\n## A\n\nbefore\n{B64}\nafter\n"
    stripped = strip_base64_images(text)
    assert "base64" not in stripped
    assert stripped.count("\n") == text.count("\n")


def test_sections_become_heading_paths_and_h1_is_not_in_the_path():
    text = "# Title\n\nintro\n\n## Interactions\n\n### Metformin\n\nlowers B12.\n"
    chunks = chunk_markdown(text)
    assert [c.section for c in chunks] == [PREAMBLE_SECTION, "Interactions > Metformin"]


def test_bracket_headings_of_tfda_labels_are_sections():
    chunks = chunk_markdown("【交互作用】\n與葡萄柚汁併用。\n\n【禁忌】\n過敏者。\n")
    assert [c.section for c in chunks] == ["交互作用", "禁忌"]


def test_text_before_first_heading_is_preamble():
    chunks = chunk_markdown("<!-- 來源 -->\n\n# T\n\n## A\n\nbody\n")
    assert chunks[0].section == PREAMBLE_SECTION


def test_chunk_text_and_lines_match_the_original_file():
    text = "# T\n\n## A\n\nfirst paragraph.\n\nsecond paragraph.\n\n## B\n\nthird.\n"
    lines = text.splitlines()
    for chunk in chunk_markdown(text):
        assert "\n".join(lines[chunk.start_line - 1 : chunk.end_line]) == chunk.text
        assert text[chunk.start : chunk.end] == chunk.text


def test_long_section_is_split_to_max_chars():
    body = "\n\n".join(f"paragraph {i} " + "x" * 400 for i in range(10))
    chunks = chunk_markdown(f"# T\n\n## A\n\n{body}\n", max_chars=1000)
    assert len(chunks) > 1
    assert all(len(c.text) <= 1000 for c in chunks)


def test_chunk_id_is_stable_and_depends_on_path_section_and_text():
    base = chunk_id("nih_ods/Zinc.md", "A", "text")
    assert base == chunk_id("nih_ods/Zinc.md", "A", "text")
    assert base != chunk_id("nih_ods/Iron.md", "A", "text")
    assert base != chunk_id("nih_ods/Zinc.md", "B", "text")
    assert base != chunk_id("nih_ods/Zinc.md", "A", "text2")


# ---- 沒有內容的雜訊段落 ----

TFDA_HEADER = (
    "<!-- 來源：TFDA 藥品仿單（衛生福利部食品藥物管理署）\n許可證字號：衛署藥輸字第000001號\n"
    "原始檔名：x.md\n抓取日期：2026-10-19\n有效成分：metformin\n處理：已移除內嵌圖片 -->\n"
)
NAV_PREAMBLE = (
    "[Skip navigation links](https://ods.od.nih.gov/factsheets/X/#maincontent)\n\n# Vitamin X\n\n"
    "Fact Sheet for Health Professionals\n\nExpand All\n\n"
    "_This is a fact sheet intended for health professionals. For a general overview, see our_ "
    "[consumer fact sheet](https://ods.od.nih.gov/factsheets/X-Consumer/).\n\n"
)
EXIT_TAIL = 'About/exit_disclaimer.aspx "External Website")\].'
EXIT_TAIL_LONG = (
    "l link disclaimer](https://ods.od.nih.gov/images/Common/externallink.png)]"
    '(https://ods.od.nih.gov/About/exit_disclaimer.aspx "External Website"), 2019.\].'
)


def _kept_text(text: str) -> list[str]:
    cleaned = strip_boilerplate(text)
    assert cleaned.count("\n") == text.count("\n")  # 行號不能位移
    return [c.text for c in chunk_markdown(cleaned) if not is_residue_chunk(c)]


def test_tfda_header_comment_is_removed_but_following_body_stays():
    text = TFDA_HEADER + "\n<details>\n<summary>seal</summary>\n\n## 用法\n\n每日一次。\n"
    kept = "\n".join(_kept_text(text))
    assert "來源：TFDA" not in kept
    assert "許可證字號" not in kept
    assert "<details>" in kept
    assert "每日一次。" in kept


def test_header_removal_keeps_line_numbers_of_body():
    text = TFDA_HEADER + "\n## A\n\nbody here.\n"
    chunks = chunk_markdown(strip_boilerplate(text))
    body = next(c for c in chunks if "body here." in c.text)
    assert text.splitlines()[body.start_line - 1] == "body here."


def test_comment_that_is_not_a_leading_source_header_is_kept():
    text = "# T\n\n## A\n\n<!-- page 2 of 3 -->\n\n內文很重要。\n"
    assert strip_boilerplate(text) == text


def test_nih_navigation_lines_are_removed_in_preamble():
    assert _kept_text(NAV_PREAMBLE + "## Intro\n\nVitamin X is useful.\n") == ["Vitamin X is useful."]


def test_navigation_block_with_real_body_keeps_the_body():
    text = "# T\n\nExpand All\n\n_For information on vitamin D and COVID-19, see our page._\n\n## A\n\nbody\n"
    kept = _kept_text(text)
    assert kept[0] == "_For information on vitamin D and COVID-19, see our page._"
    assert "Expand All" not in "\n".join(kept)


def test_navigation_words_inside_a_sentence_are_kept():
    text = "# T\n\n## A\n\nClick Expand All to open every section of the page.\n"
    assert _kept_text(text) == ["Click Expand All to open every section of the page."]


def test_exit_disclaimer_residue_chunk_is_dropped():
    assert _kept_text(f"# T\n\n## A\n\n{EXIT_TAIL}\n") == []
    assert _kept_text(f"# T\n\n## A\n\n{EXIT_TAIL_LONG}\n") == []


def test_chunk_with_disclaimer_link_and_real_text_is_kept():
    text = (
        "# T\n\n## A\n\nIron absorption falls with calcium [ref](https://x.org/a) "
        '[![external link disclaimer](https://x/externallink.png)](https://ods.od.nih.gov/About/exit_disclaimer.aspx "External Website").\n'
    )
    assert len(_kept_text(text)) == 1


def test_normal_short_chunk_is_not_residue():
    assert _kept_text("# T\n\n## A\n\n目前尚無資訊\n") == ["目前尚無資訊"]
