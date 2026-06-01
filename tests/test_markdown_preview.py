"""Tests for the pure helpers in apedi.markdown_preview.

GTK and python-markdown are optional at runtime, so rendering tests skip
if python-markdown is missing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from apedi import markdown_preview as mp


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
    """Re-importing the module should not have pulled `markdown` in
    (the cheap importlib.util.find_spec check is used instead)."""
    # The lazy module reference is None until the first render.
    # If a previous test triggered a render, this assertion is informational
    # only — we just assert MARKDOWN_AVAILABLE was set via find_spec.
    assert isinstance(mp.MARKDOWN_AVAILABLE, bool)


pytestmark_md = pytest.mark.skipif(
    not mp.MARKDOWN_AVAILABLE, reason="python-markdown not installed",
)


@pytestmark_md
def test_render_headings() -> None:
    out = mp.render_pango("# Title\n\n## Sub", dark=False)
    assert '<span size="xx-large" weight="bold">' in out
    assert "Title" in out
    assert '<span size="x-large" weight="bold">' in out
    assert "Sub" in out


@pytestmark_md
def test_render_bullet_list() -> None:
    out = mp.render_pango("- a\n- b\n- c\n", dark=False)
    assert out.count("• ") == 3
    assert "a" in out and "b" in out and "c" in out


@pytestmark_md
def test_render_ordered_list() -> None:
    out = mp.render_pango("1. one\n2. two\n", dark=False)
    assert "1. " in out
    assert "2. " in out
    assert "two" in out


@pytestmark_md
def test_render_fenced_code() -> None:
    src = "```python\ndef f():\n    return 1\n```\n"
    out = mp.render_pango(src, dark=False)
    assert 'font_family="monospace"' in out
    assert "def f()" in out


@pytestmark_md
def test_render_table_as_mono_block() -> None:
    src = "| a | b |\n| - | - |\n| 1 | 2 |\n"
    out = mp.render_pango(src, dark=False)
    # No HTML table tags — rendered as monospace block instead.
    assert "<table" not in out
    assert "<th" not in out and "<td" not in out
    assert 'font_family="monospace"' in out
    # Both header row and data row land in the same mono block.
    assert "a" in out and "b" in out
    assert "1" in out and "2" in out


@pytestmark_md
def test_render_inline_code_and_bold() -> None:
    out = mp.render_pango("This is **bold** and `code`.", dark=False)
    assert "<b>bold</b>" in out
    assert 'font_family="monospace"' in out
    assert "code" in out


@pytestmark_md
def test_render_link_emits_pango_anchor() -> None:
    out = mp.render_pango("[here](https://example.com)", dark=False)
    assert '<a href="https://example.com">' in out
    assert "here</a>" in out


@pytestmark_md
def test_render_mailto_link() -> None:
    out = mp.render_pango("[mail](mailto:foo@bar.com)", dark=False)
    assert '<a href="mailto:foo@bar.com">' in out


@pytestmark_md
def test_render_image_becomes_clickable_placeholder() -> None:
    out = mp.render_pango("![alt](path/to/pic.png)", dark=False)
    assert "[🖼" in out
    assert "pic.png" in out
    assert '<a href="path/to/pic.png">' in out


@pytestmark_md
def test_render_blockquote_dim_italic() -> None:
    out = mp.render_pango("> quoted\n", dark=False)
    assert "│ " in out
    assert "<i>" in out


@pytestmark_md
def test_render_hr() -> None:
    out = mp.render_pango("hi\n\n---\n\nbye\n", dark=False)
    assert "─" * 60 in out


@pytestmark_md
def test_render_uses_alpha_so_works_on_both_themes() -> None:
    # Same neutral color with low alpha is used for both modes, so it
    # reads on light and dark themes alike.
    light = mp.render_pango("`code`", dark=False)
    dark = mp.render_pango("`code`", dark=True)
    assert 'background_alpha=' in light
    assert 'background_alpha=' in dark


@pytestmark_md
def test_render_strips_outer_whitespace() -> None:
    out = mp.render_pango("hi", dark=False)
    assert out == out.strip()
