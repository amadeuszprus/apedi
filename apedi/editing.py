"""Pure text operations behind the editing commands, kept free of GTK for testing."""

from __future__ import annotations

PAIR = "pair"
SKIP = "skip"

_OPENERS = {"(": ")", "[": "]", "{": "}"}
_CLOSERS = set(_OPENERS.values())
_QUOTES = {'"', "'", "`"}
# A pair is only inserted when the cursor sits before one of these or at the end of a line.
_PAIR_BEFORE = set(" \t\n;:,.=)]}>")
_EMPTY_PAIRS = {"()", "[]", "{}", '""', "''", "``"}

# Prose languages, where apostrophes and quotes are ordinary punctuation.
_PROSE = {None, "", "markdown", "text", "latex", "rst", "asciidoc"}
_BACKTICK_LANGS = {"markdown", "js", "jsx", "typescript", "typescript-jsx", "sh", "go"}

# GtkSourceView metadata that is wrong for the language.
_COMMENT_OVERRIDES: dict[str, tuple[str | None, tuple[str, str] | None]] = {
    "twig": (None, ("{#", "#}")),
}


def comment_tokens(
    lang_id: str | None, line: str | None, block_start: str | None, block_end: str | None,
) -> tuple[str | None, tuple[str, str] | None]:
    """Line comment token and block comment pair for a language, either may be None."""
    if lang_id in _COMMENT_OVERRIDES:
        return _COMMENT_OVERRIDES[lang_id]
    block = (block_start, block_end) if block_start and block_end else None
    return (line or None), block


def _indent_len(line: str) -> int:
    return len(line) - len(line.lstrip())


def toggle_line_comment(lines: list[str], token: str) -> list[str]:
    """Comment every non-blank line at the shallowest indent, or uncomment if all already are."""
    content = [line for line in lines if line.strip()]
    if not content:
        return list(lines)
    if all(line.lstrip().startswith(token) for line in content):
        out = []
        for line in lines:
            if not line.strip():
                out.append(line)
                continue
            idx = _indent_len(line)
            rest = line[idx + len(token):]
            if rest.startswith(" "):
                rest = rest[1:]
            out.append(line[:idx] + rest)
        return out
    col = min(_indent_len(line) for line in content)
    return [line[:col] + token + " " + line[col:] if line.strip() else line for line in lines]


def toggle_block_comment(text: str, start: str, end: str) -> str:
    """Wrap `text` in a block comment, or unwrap it if it already is one."""
    core = text.strip()
    if not core:
        return text
    lead = text[: len(text) - len(text.lstrip())]
    trail = text[len(text.rstrip()):]
    if core.startswith(start) and core.endswith(end) and len(core) >= len(start) + len(end):
        inner = core[len(start): len(core) - len(end)]
        if inner.startswith(" "):
            inner = inner[1:]
        if inner.endswith(" "):
            inner = inner[:-1]
        return lead + inner + trail
    return f"{lead}{start} {core} {end}{trail}"


def _is_word(ch: str) -> bool:
    return ch.isalnum() or ch == "_"


def word_at(text: str, offset: int) -> tuple[int, int] | None:
    """Bounds of the word touching `offset` on either side, or None between non-word characters."""
    start = offset
    while start > 0 and _is_word(text[start - 1]):
        start -= 1
    end = offset
    while end < len(text) and _is_word(text[end]):
        end += 1
    return (start, end) if start < end else None


def next_occurrence(text: str, needle: str, start: int) -> tuple[int, int] | None:
    """Next exact match of `needle` at or after `start`, wrapping to the top."""
    if not needle:
        return None
    idx = text.find(needle, start)
    if idx < 0:
        idx = text.find(needle)
    return (idx, idx + len(needle)) if idx >= 0 else None


def _pairs_quote(char: str, lang_id: str | None) -> bool:
    if char == "`":
        return lang_id in _BACKTICK_LANGS
    return lang_id not in _PROSE


def pair_action(char: str, prev: str, nxt: str, lang_id: str | None) -> str | None:
    """What typing `char` between `prev` and `nxt` should do: PAIR, SKIP or nothing special."""
    if char in _OPENERS:
        return PAIR if nxt == "" or nxt in _PAIR_BEFORE else None
    if char in _CLOSERS:
        return SKIP if nxt == char else None
    if char in _QUOTES:
        if nxt == char:
            return SKIP
        if not _pairs_quote(char, lang_id):
            return None
        if prev and (_is_word(prev) or prev == char):
            return None
        return PAIR if nxt == "" or nxt in _PAIR_BEFORE else None
    return None


def wrap_pair(char: str, lang_id: str | None) -> tuple[str, str] | None:
    """Delimiters that typing `char` over a selection wraps it in, if any."""
    if char in _OPENERS:
        return char, _OPENERS[char]
    if char in _QUOTES and _pairs_quote(char, lang_id):
        return char, char
    return None


def deletes_pair(prev: str, nxt: str) -> bool:
    """Backspace between an empty pair removes both halves."""
    return prev + nxt in _EMPTY_PAIRS
