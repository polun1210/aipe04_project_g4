from app.rag.chunking import PREAMBLE_SECTION, chunk_markdown, strip_base64_images
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
