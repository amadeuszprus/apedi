"""Pure text operations behind the editing commands."""

from __future__ import annotations

import pytest

from apedi import editing


# ---------- line comments ----------


def test_comment_single_line_at_its_indent() -> None:
    assert editing.toggle_line_comment(["    x = 1"], "#") == ["    # x = 1"]


def test_uncomment_single_line() -> None:
    assert editing.toggle_line_comment(["    # x = 1"], "#") == ["    x = 1"]


def test_uncomment_without_space_after_token() -> None:
    assert editing.toggle_line_comment(["//foo()"], "//") == ["foo()"]


def test_comment_block_aligns_to_shallowest_indent_and_skips_blank_lines() -> None:
    lines = ["def f():", "    return 1", "", "  # already"]
    assert editing.toggle_line_comment(lines, "#") == [
        "# def f():", "#     return 1", "", "#   # already",
    ]


def test_mixed_block_gets_commented_not_uncommented() -> None:
    lines = ["# a", "b"]
    assert editing.toggle_line_comment(lines, "#") == ["# # a", "# b"]


def test_fully_commented_block_is_uncommented() -> None:
    lines = ["  # a", "", "  #b"]
    assert editing.toggle_line_comment(lines, "#") == ["  a", "", "  b"]


def test_only_blank_lines_are_left_alone() -> None:
    assert editing.toggle_line_comment(["", "   "], "#") == ["", "   "]


def test_comment_with_tabs() -> None:
    assert editing.toggle_line_comment(["\tfoo", "\t\tbar"], "//") == ["\t// foo", "\t// \tbar"]


# ---------- block comments ----------


def test_block_comment_wraps_text() -> None:
    assert editing.toggle_block_comment("<p>hi</p>", "<!--", "-->") == "<!-- <p>hi</p> -->"


def test_block_comment_unwraps_text() -> None:
    assert editing.toggle_block_comment("<!-- <p>hi</p> -->", "<!--", "-->") == "<p>hi</p>"


def test_block_comment_unwraps_without_inner_spaces() -> None:
    assert editing.toggle_block_comment("/*a*/", "/*", "*/") == "a"


def test_block_comment_keeps_surrounding_whitespace() -> None:
    assert editing.toggle_block_comment("  color: red;  ", "/*", "*/") == "  /* color: red; */  "
    assert editing.toggle_block_comment("  /* color: red; */", "/*", "*/") == "  color: red;"


def test_comment_tokens_override_twig() -> None:
    assert editing.comment_tokens("twig", "#", "{#", "#}") == (None, ("{#", "#}"))
    assert editing.comment_tokens("python3", "#", None, None) == ("#", None)
    assert editing.comment_tokens("json", None, None, None) == (None, None)


# ---------- occurrences ----------


def test_word_at() -> None:
    text = "foo bar_baz(qux)"
    assert editing.word_at(text, 5) == (4, 11)
    assert editing.word_at(text, 4) == (4, 11)
    assert editing.word_at(text, 11) == (4, 11)
    assert editing.word_at(text, 3) == (0, 3)
    assert editing.word_at("a  b", 2) is None


def test_next_occurrence_wraps_around() -> None:
    text = "ab x ab y ab"
    assert editing.next_occurrence(text, "ab", 2) == (5, 7)
    assert editing.next_occurrence(text, "ab", 12) == (0, 2)
    assert editing.next_occurrence(text, "zz", 0) is None


def test_next_occurrence_is_case_sensitive() -> None:
    assert editing.next_occurrence("Ab ab", "ab", 1) == (3, 5)


# ---------- auto-pairs ----------


@pytest.mark.parametrize(
    ("char", "prev", "nxt", "lang", "expected"),
    [
        ("(", "", "", "python3", editing.PAIR),
        ("(", "x", " ", "python3", editing.PAIR),
        ("(", "", ")", "python3", editing.PAIR),
        ("(", "", "x", "python3", None),
        ("[", "", "", None, editing.PAIR),
        (")", "(", ")", "python3", editing.SKIP),
        (")", "x", "", "python3", None),
        ('"', "", "", "python3", editing.PAIR),
        ('"', "x", "", "python3", None),
        ('"', "(", ")", "js", editing.PAIR),
        ('"', "a", '"', "python3", editing.SKIP),
        ("'", "n", "", "python3", None),
        ("'", " ", "", None, None),
        ("'", " ", "", "markdown", None),
        ("`", " ", "", "markdown", editing.PAIR),
        ("`", " ", "", "python3", None),
        ("x", "", "", "python3", None),
    ],
)
def test_pair_action(char: str, prev: str, nxt: str, lang: str | None, expected: str | None) -> None:
    assert editing.pair_action(char, prev, nxt, lang) == expected


@pytest.mark.parametrize(
    ("char", "lang", "expected"),
    [
        ("(", "python3", ("(", ")")),
        ('"', "python3", ('"', '"')),
        ("'", None, None),
        ("`", "markdown", ("`", "`")),
        ("*", "markdown", None),
    ],
)
def test_wrap_pair(char: str, lang: str | None, expected: tuple[str, str] | None) -> None:
    assert editing.wrap_pair(char, lang) == expected


@pytest.mark.parametrize(
    ("prev", "nxt", "expected"),
    [("(", ")", True), ("[", "]", True), ('"', '"', True), ("(", "]", False), ("", ")", False)],
)
def test_backspace_deletes_empty_pair(prev: str, nxt: str, expected: bool) -> None:
    assert editing.deletes_pair(prev, nxt) is expected
