"""Search and selective replace behind Find / Replace in Files."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("gi")

from apedi.find_in_files import (  # noqa: E402
    compile_query,
    find_in_text,
    replace_file,
    replace_in_text,
)


def test_compile_query_literal_and_regex() -> None:
    assert compile_query("a.b", regex=False, case_sensitive=True).search("axb") is None
    assert compile_query("a.b", regex=True, case_sensitive=True).search("axb") is not None
    assert compile_query("ABC", regex=False, case_sensitive=False).search("xabcx") is not None
    with pytest.raises(ValueError):
        compile_query("(", regex=True, case_sensitive=True)


def test_find_in_text_reports_every_match_per_line() -> None:
    pattern = compile_query("foo", regex=False, case_sensitive=True)
    hits = find_in_text("foo foo\nbar\r\nxfoo\r\n", pattern)
    assert [(line, body, [m.span() for m in ms]) for line, body, ms in hits] == [
        (1, "foo foo", [(0, 3), (4, 7)]),
        (3, "xfoo", [(1, 4)]),
    ]


def test_find_in_text_skips_empty_matches() -> None:
    pattern = compile_query("x*", regex=True, case_sensitive=True)
    assert find_in_text("ab\nxx", pattern)[0][0] == 2


def test_replace_only_selected_matches_and_keep_line_endings() -> None:
    text = "foo foo\r\nbar\r\nfoo\n"
    pattern = compile_query("foo", regex=False, case_sensitive=True)
    new, n = replace_in_text(text, pattern, "baz", {(1, 4, 7), (3, 0, 3)}, use_regex=False)
    assert new == "foo baz\r\nbar\r\nbaz\n"
    assert n == 2


def test_replace_with_regex_groups() -> None:
    pattern = compile_query(r"(\w+)=(\d+)", regex=True, case_sensitive=True)
    new, n = replace_in_text("a=1 b=2", pattern, r"\2:\1", {(1, 0, 3), (1, 4, 7)}, use_regex=True)
    assert (new, n) == ("1:a 2:b", 2)


def test_literal_replacement_is_not_interpreted() -> None:
    pattern = compile_query("x", regex=False, case_sensitive=True)
    new, _n = replace_in_text("x", pattern, r"\1\n", {(1, 0, 1)}, use_regex=False)
    assert new == r"\1\n"


def test_stale_selection_is_ignored() -> None:
    pattern = compile_query("foo", regex=False, case_sensitive=True)
    new, n = replace_in_text("foo", pattern, "bar", {(1, 5, 8), (2, 0, 3)}, use_regex=False)
    assert (new, n) == ("foo", 0)


def test_replace_file_keeps_its_encoding(tmp_path: Path) -> None:
    target = tmp_path / "latin.txt"
    target.write_bytes("zażółć foo\r\n".encode("utf-8"))
    pattern = compile_query("foo", regex=False, case_sensitive=True)
    assert replace_file(target, pattern, "bar", {(1, 7, 10)}, use_regex=False) == 1
    assert target.read_bytes() == "zażółć bar\r\n".encode("utf-8")

    legacy = tmp_path / "legacy.txt"
    legacy.write_bytes("caf\xe9 foo\n".encode("latin-1"))
    assert replace_file(legacy, pattern, "bar", {(1, 5, 8)}, use_regex=False) == 1
    assert legacy.read_bytes() == "caf\xe9 bar\n".encode("latin-1")
