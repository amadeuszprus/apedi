"""Parsing `file:line` references printed in the terminal."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from apedi.locations import PATH_PATTERN, PYTHON_TRACE_PATTERN, Location, parse, resolve


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("apedi/window.py", Location("apedi/window.py", 0, 0)),
        ("apedi/window.py:120", Location("apedi/window.py", 120, 0)),
        ("src/app.ts:12:5", Location("src/app.ts", 12, 5)),
        ("src/app.ts(12,5)", Location("src/app.ts", 12, 5)),
        ("/abs/path/x.php:7:", Location("/abs/path/x.php", 7, 0)),
        ('File "/tmp/x.py", line 42', Location("/tmp/x.py", 42, 0)),
        ("./a.py:3", Location("./a.py", 3, 0)),
    ],
)
def test_parse(text: str, expected: Location) -> None:
    assert parse(text) == expected


@pytest.mark.parametrize(
    ("line", "match"),
    [
        ("  File \"/home/u/p/x.py\", line 12, in main", 'File "/home/u/p/x.py", line 12'),
    ],
)
def test_python_trace_pattern(line: str, match: str) -> None:
    found = re.search(PYTHON_TRACE_PATTERN, line)
    assert found is not None and found.group(0) == match


@pytest.mark.parametrize(
    ("line", "match"),
    [
        ("error in apedi/window.py:120:4 unexpected", "apedi/window.py:120:4"),
        ("tests/test_x.py::test_a FAILED", "tests/test_x.py"),
        ("see /var/log/app.log now", "/var/log/app.log"),
        ("src/app.ts(12,5): error TS2322", "src/app.ts(12,5)"),
    ],
)
def test_path_pattern(line: str, match: str) -> None:
    found = re.search(PATH_PATTERN, line)
    assert found is not None and found.group(0) == match


def test_plain_words_are_not_paths() -> None:
    assert re.search(PATH_PATTERN, "hello world 3.14 v1.2") is None


def test_resolve_prefers_existing_candidates(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    (project / "src").mkdir(parents=True)
    target = project / "src" / "a.py"
    target.write_text("x\n")
    assert resolve("src/a.py", [tmp_path / "missing", project]) == target
    assert resolve(str(target), []) == target
    assert resolve("src/nope.py", [project]) is None
