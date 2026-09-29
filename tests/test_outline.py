"""Markdown headings for the outline panel."""

from __future__ import annotations

import pytest

from apedi.outline import Heading, current_heading, markdown_headings


def test_atx_headings_with_levels_and_lines() -> None:
    text = "# Title\n\nintro\n\n## Setup ##\n### Deep\n####### not a heading\n#nospace\n"
    assert markdown_headings(text) == [
        Heading(1, "Title", 1), Heading(2, "Setup", 5), Heading(3, "Deep", 6),
    ]


def test_setext_headings() -> None:
    text = "Main\n====\n\ntext\n\nSection\n-------\n\n---\n"
    assert markdown_headings(text) == [Heading(1, "Main", 1), Heading(2, "Section", 6)]


def test_fenced_code_is_skipped() -> None:
    text = "# Real\n```bash\n# comment, not heading\n```\n~~~~\n# also code\n~~~~\n## After\n"
    assert markdown_headings(text) == [Heading(1, "Real", 1), Heading(2, "After", 8)]


def test_front_matter_is_skipped() -> None:
    text = "---\ntitle: x\n---\n# Doc\n"
    assert markdown_headings(text) == [Heading(1, "Doc", 4)]


@pytest.mark.parametrize(
    ("raw", "clean"),
    [
        ("**Bold** and *it*", "Bold and it"),
        ("Use `apedi --help`", "Use apedi --help"),
        ("[Link text](http://x) here", "Link text here"),
        ("A_b_c", "A_b_c"),
    ],
)
def test_inline_markup_is_stripped(raw: str, clean: str) -> None:
    assert markdown_headings(f"# {raw}\n")[0].title == clean


def test_current_heading() -> None:
    heads = [Heading(1, "A", 1), Heading(2, "B", 5), Heading(2, "C", 9)]
    assert current_heading(heads, 1) == 0
    assert current_heading(heads, 7) == 1
    assert current_heading(heads, 50) == 2
    assert current_heading([Heading(1, "A", 3)], 1) is None
