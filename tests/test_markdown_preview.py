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
