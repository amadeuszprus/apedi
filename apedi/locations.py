"""File references printed by compilers, linters and tracebacks."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# PCRE2-compatible, since the terminal hands these to Vte.Regex as well.
PATH_PATTERN = (
    r"(?:~|\.{1,2})?/?(?:[A-Za-z0-9_.@+-]+/)*[A-Za-z0-9_@+-][A-Za-z0-9_.@+-]*"
    r"\.[A-Za-z][A-Za-z0-9]{0,9}(?![A-Za-z0-9_.@+-])"
    r"(?:\(\d+,\d+\)|:\d+(?::\d+)?:?)?"
)
PYTHON_TRACE_PATTERN = r'File "[^"]+", line \d+'

_TRACE_RE = re.compile(r'File "(?P<path>[^"]+)", line (?P<line>\d+)')
_PAREN_RE = re.compile(r"^(?P<path>.+?)\((?P<line>\d+),(?P<col>\d+)\)$")
_COLON_RE = re.compile(r"^(?P<path>.+?)(?::(?P<line>\d+)(?::(?P<col>\d+))?)?:?$")


@dataclass(frozen=True)
class Location:
    path: str
    line: int  # 1-based, 0 when unknown
    col: int  # 1-based, 0 when unknown


def parse(text: str) -> Location | None:
    """Split a matched reference into path, line and column."""
    text = text.strip()
    for regex in (_TRACE_RE, _PAREN_RE, _COLON_RE):
        m = regex.match(text)
        if m is None:
            continue
        groups = m.groupdict()
        line = int(groups.get("line") or 0)
        col = int(groups.get("col") or 0)
        return Location(groups["path"], line, col)
    return None


def resolve(path: str, bases: list[Path]) -> Path | None:
    """First existing file the reference can mean, trying each base for relative paths."""
    candidate = Path(path).expanduser()
    if candidate.is_absolute():
        return candidate if candidate.is_file() else None
    for base in bases:
        full = (base / candidate).resolve()
        if full.is_file():
            return full
    return None
