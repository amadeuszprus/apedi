"""Tests for apedi.markdown_preview — block-level rendering.

python-markdown is optional at runtime, so rendering tests skip if
it's missing. All rendering tests assert on the pure `render_blocks()`
output (headless — no GTK required).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from apedi import markdown_preview as mp


# ---------- Path detection ----------

def test_is_markdown_path_none() -> None:
    assert mp.is_markdown_path(None) is False


@pytest.mark.parametrize("name", [
    "README.md", "notes.markdown", "x.mdown", "x.mkd", "x.mkdn", "X.MD",
])
def test_is_markdown_path_yes(name: str) -> None:
    assert mp.is_markdown_path(Path(name)) is True


@pytest.mark.parametrize("name", [
    "main.py", "notes.txt", "config.toml", "a.html", "Makefile",
])
def test_is_markdown_path_no(name: str) -> None:
    assert mp.is_markdown_path(Path(name)) is False


def test_module_import_does_not_load_markdown() -> None:
    assert isinstance(mp.MARKDOWN_AVAILABLE, bool)


pytestmark_md = pytest.mark.skipif(
    not mp.MARKDOWN_AVAILABLE, reason="python-markdown not installed",
)


# ---------- render_blocks — skeleton ----------

@pytestmark_md
def test_render_blocks_returns_list() -> None:
    blocks = mp.render_blocks("hi")
    assert isinstance(blocks, list)
    assert len(blocks) == 1
    assert isinstance(blocks[0], mp.ProseBlock)
    assert "hi" in blocks[0].pango_markup


@pytestmark_md
def test_render_heading_present() -> None:
    blocks = mp.render_blocks("# Title\n\n## Sub")
    assert len(blocks) == 1
    m = blocks[0].pango_markup
    assert '<span size="xx-large" weight="bold">' in m
    assert "Title" in m
    assert '<span size="x-large" weight="bold">' in m
    assert "Sub" in m


@pytestmark_md
def test_render_bullet_list() -> None:
    blocks = mp.render_blocks("- a\n- b\n- c\n")
    m = blocks[0].pango_markup
    assert m.count("• ") == 3
    assert "a" in m and "b" in m and "c" in m


@pytestmark_md
def test_render_ordered_list() -> None:
    blocks = mp.render_blocks("1. one\n2. two\n")
    m = blocks[0].pango_markup
    assert "1. " in m and "2. " in m and "two" in m


@pytestmark_md
def test_render_inline_bold_and_code() -> None:
    m = mp.render_blocks("This is **bold** and `code`.")[0].pango_markup
    assert "<b>bold</b>" in m
    assert 'font_family="monospace"' in m


@pytestmark_md
def test_render_link() -> None:
    m = mp.render_blocks("[here](https://example.com)")[0].pango_markup
    assert '<a href="https://example.com">' in m
    assert "here</a>" in m


@pytestmark_md
def test_render_mailto() -> None:
    m = mp.render_blocks("[mail](mailto:foo@bar.com)")[0].pango_markup
    assert '<a href="mailto:foo@bar.com">' in m


@pytestmark_md
def test_render_image_placeholder() -> None:
    m = mp.render_blocks("![alt](path/to/pic.png)")[0].pango_markup
    assert "[🖼" in m
    assert "pic.png" in m
    assert '<a href="path/to/pic.png">' in m


@pytestmark_md
def test_render_hr() -> None:
    m = mp.render_blocks("hi\n\n---\n\nbye\n")[0].pango_markup
    assert "─" * 60 in m


@pytestmark_md
def test_render_blockquote() -> None:
    m = mp.render_blocks("> quoted\n")[0].pango_markup
    assert "│ " in m
    assert "<i>" in m


@pytestmark_md
def test_render_strips_outer_whitespace() -> None:
    m = mp.render_blocks("hi")[0].pango_markup
    assert m == m.strip()


@pytestmark_md
def test_render_empty_input_returns_empty_list() -> None:
    assert mp.render_blocks("") == []
    assert mp.render_blocks("   \n  \n") == []


@pytestmark_md
def test_render_splits_prose_and_table() -> None:
    src = "before\n\n| a | b |\n| - | - |\n| 1 | 2 |\n\nafter\n"
    blocks = mp.render_blocks(src)
    types = [type(b).__name__ for b in blocks]
    assert types == ["ProseBlock", "TableBlock", "ProseBlock"]
    tb = blocks[1]
    assert tb.header == ["a", "b"]
    assert tb.rows == [["1", "2"]]


@pytestmark_md
def test_render_table_alone() -> None:
    src = "| a | b |\n| - | - |\n| 1 | 2 |\n| 3 | 4 |\n"
    blocks = mp.render_blocks(src)
    assert [type(b).__name__ for b in blocks] == ["TableBlock"]
    tb = blocks[0]
    assert tb.header == ["a", "b"]
    assert tb.rows == [["1", "2"], ["3", "4"]]


@pytestmark_md
def test_table_alignment_from_colons() -> None:
    src = "| a | b | c |\n|:--|:-:|--:|\n| 1 | 2 | 3 |\n"
    tb = mp.render_blocks(src)[0]
    assert tb.aligns == [mp.Align.LEFT, mp.Align.CENTER, mp.Align.RIGHT]


@pytestmark_md
def test_table_cell_preserves_inline_markup() -> None:
    src = "| a | b |\n| - | - |\n| **hi** | `x` |\n"
    tb = mp.render_blocks(src)[0]
    assert "<b>hi</b>" in tb.rows[0][0]
    assert 'font_family="monospace"' in tb.rows[0][1]


@pytestmark_md
def test_table_short_row_padded() -> None:
    # Malformed table: header has 3, row has 2 — pad to header width.
    src = "| a | b | c |\n| - | - | - |\n| 1 | 2 |\n"
    tb = mp.render_blocks(src)[0]
    assert len(tb.rows[0]) == 3
    assert tb.rows[0][2] == ""


@pytestmark_md
def test_render_splits_prose_and_code() -> None:
    src = "before\n\n```python\ndef f():\n    return 1\n```\n\nafter\n"
    blocks = mp.render_blocks(src)
    types = [type(b).__name__ for b in blocks]
    assert types == ["ProseBlock", "CodeBlock", "ProseBlock"]
    cb = blocks[1]
    assert cb.lang == "python"
    assert cb.text == "def f():\n    return 1"


@pytestmark_md
def test_code_block_lang_none_when_absent() -> None:
    src = "```\nplain\ntext\n```\n"
    blocks = mp.render_blocks(src)
    assert isinstance(blocks[0], mp.CodeBlock)
    assert blocks[0].lang is None
    assert blocks[0].text == "plain\ntext"


@pytestmark_md
def test_inline_code_stays_in_prose() -> None:
    # Inline `code` is not a fenced block — must remain in ProseBlock.
    blocks = mp.render_blocks("this is `inline` code")
    assert len(blocks) == 1
    assert isinstance(blocks[0], mp.ProseBlock)
    assert 'font_family="monospace"' in blocks[0].pango_markup


@pytestmark_md
def test_heading_underline_h1() -> None:
    m = mp.render_blocks("# Title")[0].pango_markup
    assert "━" in m


@pytestmark_md
def test_heading_underline_h2() -> None:
    m = mp.render_blocks("## Sub")[0].pango_markup
    assert "─" in m


@pytestmark_md
def test_heading_no_underline_h3() -> None:
    m = mp.render_blocks("### Small")[0].pango_markup
    assert "━" not in m
    # The hr uses '─' × 60 — but h3 alone (no hr) must not have '─'.
    assert "─" not in m
