"""Whitespace normalization — the cleanup pass for text no formatter owns.

Terminal output, browser copy-paste and hand-edited notes arrive with CRLF
endings, trailing spaces, a uniform indent the surrounding UI added, and long
runs of blank lines. External formatters (black, prettier, …) fix that for the
languages they support; this module is what everything else gets.

Deliberately conservative by default: it touches line endings, trailing
whitespace, leading indentation and blank-line runs, and nothing else. Spacing
*inside* a line is left alone, so aligned tables and ASCII art survive, and
non-breaking spaces are preserved because rewriting them would change string
literals.

Re-joining hard-wrapped lines (`unwrap=True`) is the one lossy operation here —
no heuristic can tell a line the terminal wrapped from a line someone broke on
purpose. It is off by default and the editor only offers it on a selection, so
the blast radius is whatever the user highlighted.
"""

from __future__ import annotations

import re

DEFAULT_TAB_WIDTH = 4

# A line shorter than this plausibly ended where its author wanted it to, so it
# is treated as the end of a paragraph rather than as a wrap.
UNWRAP_MIN_LEN = 60

# Markers that start a new block and must never be swallowed into the line above.
_STRUCTURAL = re.compile(
    r"""^(
        [-*+•]\s
      | \d+[.)]\s
      | \#{1,6}\s
      | >
      | \|
      | ```
      | ~~~
      | [-=]{3,}\s*$
    )""",
    re.VERBOSE,
)

_FENCE = re.compile(r"^(```|~~~)")

# GtkSourceView language ids whose line breaks carry no meaning, so re-joining
# them is safe. Everything else — every programming language — is excluded: a
# statement that happens to run past UNWRAP_MIN_LEN would otherwise be glued to
# the next one, silently producing code that no longer parses. `None` (plain
# text: .txt, .log, an unsaved buffer) is the common case for terminal output.
PROSE_LANGUAGES = frozenset({"markdown", "rst", "asciidoc", "textile", "gtk-doc"})


def may_unwrap(language_id: str | None) -> bool:
    """Whether re-joining wrapped lines is safe for this language."""
    return language_id is None or language_id in PROSE_LANGUAGES


def _leading_width(line: str, tab_width: int) -> tuple[int, str]:
    """Split `line` into its indentation width (in columns) and its body."""
    width = 0
    for i, ch in enumerate(line):
        if ch == " ":
            width += 1
        elif ch == "\t":
            # A tab advances to the next multiple of tab_width, which is what
            # the editor renders — not a fixed tab_width columns.
            width += tab_width - (width % tab_width)
        else:
            return width, line[i:]
    return width, ""


def _indent_for(width: int, tab_width: int, use_spaces: bool) -> str:
    if use_spaces:
        return " " * width
    # Whole tabs, then any remainder as spaces: rounding the remainder up to a
    # full tab would silently move continuation lines that were aligned by eye.
    return "\t" * (width // tab_width) + " " * (width % tab_width)


def _unwrap(lines: list[str], tab_width: int) -> list[str]:
    """Join lines that look hard-wrapped back into single paragraphs."""
    out: list[str] = []
    in_fence = False
    for line in lines:
        if _FENCE.match(line.lstrip()):
            in_fence = not in_fence
            out.append(line)
            continue
        if in_fence or not line or not out or not out[-1]:
            out.append(line)
            continue
        prev = out[-1]
        # Short previous line — it ended where it meant to.
        if len(prev) < UNWRAP_MIN_LEN:
            out.append(line)
            continue
        # A bullet, heading, table row or rule begins its own block. (A
        # structural *previous* line is fine: that is a wrapped list item, and
        # pulling its continuation back up is exactly right.)
        if _STRUCTURAL.match(line.lstrip()):
            out.append(line)
            continue
        # Deeper indentation means a nested block (code, a sub-item) — never a
        # wrap. Equal or shallower is fine: a terminal wrapping a line does not
        # re-indent what it pushed onto the next row, so the continuation of an
        # indented paragraph very often arrives in column 0.
        if _leading_width(line, tab_width)[0] > _leading_width(prev, tab_width)[0]:
            out.append(line)
            continue
        out[-1] = prev + " " + line.lstrip()
    return out


def normalize_text(
    text: str,
    *,
    tab_width: int = DEFAULT_TAB_WIDTH,
    use_spaces: bool = True,
    unwrap: bool = False,
    ensure_final_newline: bool = True,
) -> str:
    """Return `text` with its whitespace normalized.

    - CRLF and lone CR become LF
    - trailing whitespace is stripped from every line
    - the indentation every non-blank line shares is removed, and what is left
      is re-emitted as tabs or spaces per `use_spaces`
    - runs of blank lines collapse to a single blank line
    - leading blank lines are dropped (an input that is entirely whitespace
      normalizes to the empty string)

    With `unwrap`, lines that look hard-wrapped are re-joined into paragraphs.

    `ensure_final_newline` forces exactly one trailing LF; with it off, a
    trailing newline is kept only if the input had one — which is what a
    selection in the middle of a line needs.
    """
    if not text:
        return ""
    if tab_width < 1:
        tab_width = DEFAULT_TAB_WIDTH
    had_final_newline = text.endswith(("\n", "\r"))

    kept: list[str] = []
    pending_blank = False
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        stripped = raw.rstrip()
        if not stripped:
            # Hold the blank back: a run of them collapses to one, and a run
            # at the very start or the very end disappears entirely.
            pending_blank = bool(kept)
            continue
        if pending_blank:
            kept.append("")
            pending_blank = False
        kept.append(stripped)
    if not kept:
        return ""

    if unwrap:
        # Before measuring the shared indent, not after: a line the terminal
        # wrapped lands in column 0 and would otherwise drag the common indent
        # to zero, defeating the dedent for the whole block.
        kept = _unwrap(kept, tab_width)

    split = [None if line == "" else _leading_width(line, tab_width) for line in kept]
    widths = [p[0] for p in split if p is not None]
    common = min(widths) if widths else 0

    lines: list[str] = []
    for part in split:
        if part is None:
            lines.append("")
            continue
        width, body = part
        lines.append(_indent_for(max(0, width - common), tab_width, use_spaces) + body)

    out = "\n".join(lines)
    if ensure_final_newline or had_final_newline:
        out += "\n"
    return out


def changed(
    text: str,
    *,
    tab_width: int = DEFAULT_TAB_WIDTH,
    use_spaces: bool = True,
    unwrap: bool = False,
    ensure_final_newline: bool = True,
) -> bool:
    """True when normalizing `text` would actually alter it."""
    return normalize_text(
        text,
        tab_width=tab_width,
        use_spaces=use_spaces,
        unwrap=unwrap,
        ensure_final_newline=ensure_final_newline,
    ) != text
