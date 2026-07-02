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
