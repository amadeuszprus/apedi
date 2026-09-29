"""Markdown export to a self-contained HTML page and to PDF."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from apedi import markdown_preview as mp

pytestmark = pytest.mark.skipif(not mp.MARKDOWN_AVAILABLE, reason="python-markdown not installed")

md_export = pytest.importorskip("apedi.md_export")

ICON = Path(__file__).resolve().parent.parent / "data" / "apedi-icon.png"


def test_front_matter_is_split_off() -> None:
    meta, body = md_export.split_front_matter("---\ntitle: My Doc\ntags: [a]\n---\n# Hi\n")
    assert meta == {"title": "My Doc"}
    assert body == "# Hi\n"
    assert md_export.split_front_matter("# Plain\n") == ({}, "# Plain\n")


def test_title_prefers_front_matter_then_first_heading_then_name() -> None:
    assert md_export.document_title("---\ntitle: FM\n---\n# H\n", "file") == "FM"
    assert md_export.document_title("text\n\n# First *one*\n## Second\n", "file") == "First one"
    assert md_export.document_title("no headings", "readme") == "readme"


def test_html_is_self_contained(tmp_path: Path) -> None:
    shutil.copy(ICON, tmp_path / "pic one.png")
    text = (
        "---\ntitle: Report\n---\n# Report\n\n![logo](pic%20one.png)\n\n"
        "| a | b |\n|---|---|\n| 1 | 2 |\n\n```py\nprint(1)\n```\n\n![remote](https://x.org/a.png)\n"
    )
    html = md_export.to_html(text, tmp_path, "fallback")
    assert "<title>Report</title>" in html
    assert "title: Report" not in html
    assert re.search(r'<img alt="logo" src="data:image/png;base64,[A-Za-z0-9+/=]{100,}"', html)
    assert 'src="https://x.org/a.png"' in html
    assert "<table>" in html and "<pre><code" in html
    assert "<style>" in html


def test_html_escapes_the_title() -> None:
    assert "<title>a &lt;b&gt;</title>" in md_export.to_html("x", None, "a <b>")


def test_pdf_paginates_and_embeds_images(tmp_path: Path) -> None:
    shutil.copy(ICON, tmp_path / "icon.png")
    paragraphs = "\n\n".join(f"Paragraph {i} with **bold** and a [link](http://x)." for i in range(120))
    text = (
        f"# Title\n\n![i](icon.png)\n\n{paragraphs}\n\n| k | v |\n|---|---|\n| a | b |\n\n"
        "```\ncode line\n```\n\n- item\n- [ ] task\n"
    )
    out = tmp_path / "out.pdf"
    md_export.to_pdf(text, tmp_path, out)
    data = out.read_bytes()
    assert data.startswith(b"%PDF")
    assert b"/Subtype /Image" in data or b"/Subtype/Image" in data
    if shutil.which("pdfinfo"):
        info = subprocess.run(["pdfinfo", str(out)], capture_output=True, text=True, check=True).stdout
        pages = int(re.search(r"^Pages:\s+(\d+)", info, re.MULTILINE).group(1))
        assert pages >= 3


def test_invalid_markup_falls_back_to_plain_text() -> None:
    from gi.repository import Pango, PangoCairo

    layout = Pango.Layout.new(PangoCairo.FontMap.get_default().create_context())
    md_export._set_markup(layout, "<b>unclosed")
    assert layout.get_text() == "unclosed"
    md_export._set_markup(layout, "<b>fine</b>")
    assert layout.get_text() == "fine"
