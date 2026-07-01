# Markdown preview — block-level rendering — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single-`GtkLabel` markdown preview with a `GtkBox` of per-block widgets so tables render as real `GtkGrid` with borders/header/zebra, code blocks become full-width bordered rectangles, and prose gains task lists, nested blockquotes, heading underlines, and deeper nested-list indent.

**Architecture:** Split rendering into a pure `render_blocks(text) -> list[Block]` function (headless-testable) and a thin `_BlockRenderer` GTK dispatcher. `_BlockSplitter(HTMLParser)` walks python-markdown's HTML output and emits sealed dataclass blocks (`ProseBlock`, `TableBlock`, `CodeBlock`). CSS in `apedi/style.py` handles table/code styling with `alpha(currentColor, ...)` so light/dark themes need no per-mode swaps.

**Tech Stack:** Python 3.12+, GTK4 (`gi.repository`), python-markdown (existing dep). No new external libraries.

**Spec:** `docs/superpowers/specs/2026-07-01-markdown-preview-block-level-design.md`

---

## File Structure

**Modified:**
- `apedi/markdown_preview.py` — total rewrite of internals; public API preserved
- `apedi/style.py` — appends CSS for `.apedi-md-table` and `.apedi-md-code`
- `tests/test_markdown_preview.py` — rewritten around `render_blocks()`
- `apedi/__init__.py` — version bump `0.7.9` → `0.7.10`
- `snap/snapcraft.yaml` — version bump
- `pyproject.toml` — version bump
- `CHANGELOG.md` — new entry

No new files. Everything lives inside `apedi/markdown_preview.py` — the module is ~400 lines today and will grow to ~600, still a single-responsibility file.

---

## Task 1: Dataclasses + `render_blocks()` skeleton

Introduce the `Block` union and a `render_blocks()` entry point that handles the trivial case (any input → one `ProseBlock`). This lets subsequent tasks add features one at a time, each with its own failing test.

**Files:**
- Modify: `apedi/markdown_preview.py`
- Modify: `tests/test_markdown_preview.py`

- [ ] **Step 1: Write the failing test**

Replace the entire `tests/test_markdown_preview.py` file with:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/aprus/www/editor && python -m pytest tests/test_markdown_preview.py -v`
Expected: FAIL with `AttributeError: module 'apedi.markdown_preview' has no attribute 'render_blocks'` (or `ProseBlock`).

- [ ] **Step 3: Add dataclasses and skeleton `render_blocks()`**

Open `apedi/markdown_preview.py`. Add imports at the top (after existing `from typing import Callable`):

```python
from dataclasses import dataclass
from enum import Enum
```

Then add these definitions **after** `_ensure_md()` and **before** the `# ---------- HTML → Pango converter ----------` header:

```python
# ---------- Block model ----------


class Align(Enum):
    LEFT = "left"
    CENTER = "center"
    RIGHT = "right"


@dataclass(frozen=True)
class ProseBlock:
    """Headings, paragraphs, lists, blockquotes — rendered as Pango markup."""
    pango_markup: str


@dataclass(frozen=True)
class TableBlock:
    """Table with per-cell Pango markup and per-column alignment."""
    header: list[str]
    rows: list[list[str]]
    aligns: list[Align]


@dataclass(frozen=True)
class CodeBlock:
    """Fenced code block — raw text, no markup. `lang` preserved for future use."""
    text: str
    lang: str | None


Block = ProseBlock | TableBlock | CodeBlock
```

Add a placeholder `render_blocks()` at the module level (before the `if GTK_AVAILABLE:` block):

```python
def render_blocks(text: str) -> list[Block]:
    """Pure markdown → list of block descriptors. Headless-testable."""
    if not _ensure_md():
        return [ProseBlock(_("python-markdown not installed"))]
    builder = _PangoBuilder(dark=False)
    builder.feed(_html_escape(text, quote=False))
    builder.close()
    markup = builder.result()
    return [ProseBlock(markup)]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_markdown_preview.py::test_render_blocks_returns_list -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apedi/markdown_preview.py tests/test_markdown_preview.py
git commit -m "Add Block dataclass model + render_blocks() skeleton

Introduces ProseBlock/TableBlock/CodeBlock sealed union and a
placeholder render_blocks() that returns a single ProseBlock. Sets up
the seams for per-feature TDD in follow-up commits."
```

---

## Task 2: Real prose rendering via python-markdown

Replace the escape-only stub with a real `markdown → HTML → _PangoBuilder → ProseBlock` pipeline, so prose (headings, paragraphs, lists, links, bold, italic, inline code) works end-to-end.

**Files:**
- Modify: `apedi/markdown_preview.py`
- Modify: `tests/test_markdown_preview.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/test_markdown_preview.py`:

```python
@pytestmark_md
def test_render_heading_present() -> None:
    blocks = mp.render_blocks("# Title\n\n## Sub")
    assert len(blocks) == 1
    m = blocks[0].pango_markup
    assert '<span size="xx-large" weight="bold">' in m
    assert "Title" in m
    assert '<span size="x-large" weight="bold">' in m
    assert "Sub" in m


@pytestmark_md
def test_render_bullet_list() -> None:
    blocks = mp.render_blocks("- a\n- b\n- c\n")
    m = blocks[0].pango_markup
    assert m.count("• ") == 3
    assert "a" in m and "b" in m and "c" in m


@pytestmark_md
def test_render_ordered_list() -> None:
    blocks = mp.render_blocks("1. one\n2. two\n")
    m = blocks[0].pango_markup
    assert "1. " in m and "2. " in m and "two" in m


@pytestmark_md
def test_render_inline_bold_and_code() -> None:
    m = mp.render_blocks("This is **bold** and `code`.")[0].pango_markup
    assert "<b>bold</b>" in m
    assert 'font_family="monospace"' in m


@pytestmark_md
def test_render_link() -> None:
    m = mp.render_blocks("[here](https://example.com)")[0].pango_markup
    assert '<a href="https://example.com">' in m
    assert "here</a>" in m


@pytestmark_md
def test_render_mailto() -> None:
    m = mp.render_blocks("[mail](mailto:foo@bar.com)")[0].pango_markup
    assert '<a href="mailto:foo@bar.com">' in m


@pytestmark_md
def test_render_image_placeholder() -> None:
    m = mp.render_blocks("![alt](path/to/pic.png)")[0].pango_markup
    assert "[🖼" in m
    assert "pic.png" in m
    assert '<a href="path/to/pic.png">' in m


@pytestmark_md
def test_render_hr() -> None:
    m = mp.render_blocks("hi\n\n---\n\nbye\n")[0].pango_markup
    assert "─" * 60 in m


@pytestmark_md
def test_render_blockquote() -> None:
    m = mp.render_blocks("> quoted\n")[0].pango_markup
    assert "│ " in m
    assert "<i>" in m


@pytestmark_md
def test_render_strips_outer_whitespace() -> None:
    m = mp.render_blocks("hi")[0].pango_markup
    assert m == m.strip()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_markdown_preview.py -v -k "heading or bullet or ordered or inline or link or mailto or image or hr or blockquote or strips"`
Expected: multiple FAILs (markup mismatches — the stub `_html_escape`d instead of running the markdown pipeline).

- [ ] **Step 3: Wire `render_blocks()` to the real pipeline**

In `apedi/markdown_preview.py`, replace the whole `render_blocks()` body with:

```python
def render_blocks(text: str) -> list[Block]:
    """Pure markdown → list of block descriptors. Headless-testable."""
    if not _ensure_md():
        return [ProseBlock(_("python-markdown not installed"))]
    html = _md.Markdown(
        extensions=["fenced_code", "tables", "sane_lists"],
    ).convert(text)
    builder = _PangoBuilder(dark=False)
    builder.feed(html)
    builder.close()
    markup = builder.result()
    return [ProseBlock(markup)] if markup else []
```

Note: `nl2br` is **removed** from the extension list (was in the old code, caused list-wrapping issues).

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_markdown_preview.py -v`
Expected: all listed tests PASS.

- [ ] **Step 5: Commit**

```bash
git add apedi/markdown_preview.py tests/test_markdown_preview.py
git commit -m "Wire render_blocks() to python-markdown + _PangoBuilder

Prose (headings, lists, links, bold/italic, inline code, blockquote,
hr, image placeholder) now flows end-to-end through the block model.
Also drops nl2br which was causing list-wrapping issues."
```

---

## Task 3: Empty prose block filter

Empty input or whitespace-only input should return `[]`, not a `ProseBlock("")`.

**Files:**
- Modify: `tests/test_markdown_preview.py`

- [ ] **Step 1: Add failing test**

Append:

```python
@pytestmark_md
def test_render_empty_input_returns_empty_list() -> None:
    assert mp.render_blocks("") == []
    assert mp.render_blocks("   \n  \n") == []
```

- [ ] **Step 2: Run test**

Run: `python -m pytest tests/test_markdown_preview.py::test_render_empty_input_returns_empty_list -v`
Expected: If already PASSING (the Task 2 code has `if markup else []`), skip step 3 and commit as a "confirm behavior" test. If FAIL, proceed to step 3.

- [ ] **Step 3: Fix if needed**

The `_PangoBuilder.result()` already strips outer whitespace, and `render_blocks()` in Task 2 returns `[]` when markup is falsy. If whitespace-only inputs produce a non-empty markup (e.g., `"\n\n"` from python-markdown), add `markup = markup.strip()` after `builder.result()`:

```python
markup = builder.result().strip()
return [ProseBlock(markup)] if markup else []
```

- [ ] **Step 4: Re-run test**

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apedi/markdown_preview.py tests/test_markdown_preview.py
git commit -m "render_blocks(): drop empty ProseBlock for whitespace-only input"
```

---

## Task 4: Table extraction — `TableBlock` with header + rows

Introduce `_BlockSplitter` so `<table>` becomes a `TableBlock` while surrounding prose stays in `ProseBlock`s.

**Files:**
- Modify: `apedi/markdown_preview.py`
- Modify: `tests/test_markdown_preview.py`

- [ ] **Step 1: Add failing tests**

Append:

```python
@pytestmark_md
def test_render_splits_prose_and_table() -> None:
    src = "before\n\n| a | b |\n| - | - |\n| 1 | 2 |\n\nafter\n"
    blocks = mp.render_blocks(src)
    types = [type(b).__name__ for b in blocks]
    assert types == ["ProseBlock", "TableBlock", "ProseBlock"]
    tb = blocks[1]
    assert tb.header == ["a", "b"]
    assert tb.rows == [["1", "2"]]


@pytestmark_md
def test_render_table_alone() -> None:
    src = "| a | b |\n| - | - |\n| 1 | 2 |\n| 3 | 4 |\n"
    blocks = mp.render_blocks(src)
    assert [type(b).__name__ for b in blocks] == ["TableBlock"]
    tb = blocks[0]
    assert tb.header == ["a", "b"]
    assert tb.rows == [["1", "2"], ["3", "4"]]
```

- [ ] **Step 2: Run tests**

Expected: FAIL — no table splitting yet; current code emits one big ProseBlock via `_PangoBuilder`'s legacy `_flush_table` path.

- [ ] **Step 3: Implement `_BlockSplitter`**

In `apedi/markdown_preview.py`, **after** the existing `_PangoBuilder` class and **before** `render_pango`/`render_blocks`, add:

```python
class _BlockSplitter(HTMLParser):
    """Walks markdown's HTML output, splitting into Blocks.

    Prose accumulates into a running _PangoBuilder; a <table> or
    <pre><code> boundary flushes it and emits a dedicated Block.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[Block] = []
        self._prose = _PangoBuilder(dark=False)
        # Table state
        self._in_table = False
        self._table_header: list[str] | None = None
        self._table_rows: list[list[str]] = []
        self._table_aligns: list[Align] = []
        self._in_thead = False
        self._current_row: list[str] | None = None
        self._current_cell: _PangoBuilder | None = None
        self._current_cell_align: Align = Align.LEFT
        # Code state
        self._in_pre_code = False
        self._code_lang: str | None = None
        self._code_chunks: list[str] = []

    # ---- helpers ----

    def _flush_prose(self) -> None:
        markup = self._prose.result().strip()
        if markup:
            self.blocks.append(ProseBlock(markup))
        self._prose = _PangoBuilder(dark=False)

    @staticmethod
    def _parse_align(style: str) -> Align:
        s = style.lower()
        if "right" in s:
            return Align.RIGHT
        if "center" in s:
            return Align.CENTER
        return Align.LEFT

    @staticmethod
    def _parse_lang(class_attr: str) -> str | None:
        # python-markdown emits class="language-python" for fenced code.
        for cls in class_attr.split():
            if cls.startswith("language-"):
                return cls[len("language-"):]
        return None

    # ---- HTMLParser hooks ----

    _TABLE_STRUCT = {"thead", "tbody", "tr", "th", "td"}

    def handle_starttag(self, tag, attrs) -> None:
        attrs_d = dict(attrs)
        if tag == "table":
            self._flush_prose()
            self._in_table = True
            self._table_header = None
            self._table_rows = []
            self._table_aligns = []
            return
        if self._in_table:
            if tag in self._TABLE_STRUCT:
                self._handle_table_start(tag, attrs_d)
            elif self._current_cell is not None:
                # Inline tags inside a cell (<strong>, <em>, <a>, <code>, ...)
                # must be routed into the cell's PangoBuilder so inline markup
                # survives inside table cells.
                self._current_cell.handle_starttag(tag, attrs)
            return
        if tag == "pre":
            self._flush_prose()
            self._in_pre_code = True
            self._code_lang = None
            self._code_chunks = []
            return
        if self._in_pre_code:
            if tag == "code":
                self._code_lang = self._parse_lang(attrs_d.get("class", "") or "")
            return
        # Prose
        self._prose.handle_starttag(tag, attrs)

    def handle_endtag(self, tag) -> None:
        if self._in_table:
            if tag == "table" or tag in self._TABLE_STRUCT:
                self._handle_table_end(tag)
            elif self._current_cell is not None:
                self._current_cell.handle_endtag(tag)
            return
        if self._in_pre_code:
            if tag == "pre":
                self._emit_code_block()
                self._in_pre_code = False
            return
        self._prose.handle_endtag(tag)

    def handle_data(self, data) -> None:
        if self._in_table:
            if self._current_cell is not None:
                # Feed cell text through cell-mode PangoBuilder as raw text
                self._current_cell.handle_data(data)
            return
        if self._in_pre_code:
            self._code_chunks.append(data)
            return
        self._prose.handle_data(data)

    # ---- table sub-handlers ----

    def _handle_table_start(self, tag, attrs_d) -> None:
        if tag == "thead":
            self._in_thead = True
        elif tag == "tr":
            self._current_row = []
        elif tag in ("th", "td"):
            style = attrs_d.get("style", "") or ""
            self._current_cell_align = self._parse_align(style)
            self._current_cell = _PangoBuilder(dark=False, cell_mode=True)
        elif tag == "tbody":
            pass  # ignored — presence/absence handled by thead flag

    def _handle_table_end(self, tag) -> None:
        if tag == "thead":
            self._in_thead = False
        elif tag in ("th", "td"):
            assert self._current_cell is not None
            cell_markup = self._current_cell.result().strip()
            assert self._current_row is not None
            self._current_row.append(cell_markup)
            if self._in_thead:
                # Only header rows contribute to align inference
                self._table_aligns.append(self._current_cell_align)
            self._current_cell = None
        elif tag == "tr":
            assert self._current_row is not None
            if self._in_thead and self._table_header is None:
                self._table_header = self._current_row
            else:
                self._table_rows.append(self._current_row)
            self._current_row = None
        elif tag == "table":
            header = self._table_header or []
            # Normalize aligns to header width
            aligns = self._table_aligns[: len(header)]
            while len(aligns) < len(header):
                aligns.append(Align.LEFT)
            # Pad short rows so downstream can iterate without bounds checks
            width = len(header)
            rows = [row + [""] * (width - len(row)) for row in self._table_rows]
            self.blocks.append(TableBlock(header=header, rows=rows, aligns=aligns))
            self._in_table = False

    # ---- code emit ----

    def _emit_code_block(self) -> None:
        text = "".join(self._code_chunks)
        # python-markdown wraps code in <pre><code>...</code></pre> without
        # a trailing newline; some fenced blocks arrive with a leading newline.
        if text.startswith("\n"):
            text = text[1:]
        if text.endswith("\n"):
            text = text[:-1]
        self.blocks.append(CodeBlock(text=text, lang=self._code_lang))
        self._code_chunks = []
        self._code_lang = None

    # ---- finalize ----

    def finalize(self) -> list[Block]:
        self._flush_prose()
        return self.blocks
```

Also modify `_PangoBuilder.__init__` to accept `cell_mode`:

Find:
```python
    def __init__(self, dark: bool) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.list_stack: list[tuple[str, int]] = []  # (kind, counter)
        self.in_pre = False
```

Replace with:
```python
    def __init__(self, dark: bool, cell_mode: bool = False) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.list_stack: list[tuple[str, int]] = []  # (kind, counter)
        self.in_pre = False
        self.cell_mode = cell_mode
```

In `handle_endtag`, guard the `<p>` newlines when in `cell_mode` (table cells should not emit blank-line breaks):

Find:
```python
        elif tag == "p":
            self._emit("\n\n")
```
Replace with:
```python
        elif tag == "p":
            if not self.cell_mode:
                self._emit("\n\n")
```

Rewrite `render_blocks()` to use the splitter (replace the whole body):

```python
def render_blocks(text: str) -> list[Block]:
    """Pure markdown → list of block descriptors. Headless-testable."""
    if not _ensure_md():
        return [ProseBlock(_("python-markdown not installed"))]
    html = _md.Markdown(
        extensions=["fenced_code", "tables", "sane_lists"],
    ).convert(text)
    splitter = _BlockSplitter()
    splitter.feed(html)
    splitter.close()
    return splitter.finalize()
```

Also **delete** the now-unreachable `_flush_table` code path in `_PangoBuilder` — search for the `_flush_table` method and the four `_table_*` attributes in `__init__` and remove them, plus the `if tag == "table":` / `if tag == "tr":` / `if tag in ("th", "td"):` branches in `_PangoBuilder.handle_starttag` and `handle_endtag`. Tables are now the splitter's job; `_PangoBuilder` never sees them.

Specifically remove from `_PangoBuilder.__init__`:
```python
        # Table buffering
        self._table_rows: list[list[str]] | None = None
        self._table_row: list[str] | None = None
        self._table_cell: list[str] | None = None
```

Simplify `_PangoBuilder._emit()`:
```python
    def _emit(self, s: str) -> None:
        self.out.append(s)
```

And remove the `_flush_table()` method entirely. Remove table branches from `handle_starttag`/`handle_endtag`.

Also remove the legacy `render_pango()` public function since it's superseded (search for `def render_pango` — delete the whole function).

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_markdown_preview.py -v`
Expected: all PASS. Any table-related previously-passing test should keep passing via the new `TableBlock` path.

- [ ] **Step 5: Commit**

```bash
git add apedi/markdown_preview.py tests/test_markdown_preview.py
git commit -m "Split HTML into Blocks: tables become TableBlock dataclasses

Introduces _BlockSplitter which walks python-markdown's HTML and emits
ProseBlock/TableBlock. _PangoBuilder gains a cell_mode for use inside
table cells (no paragraph breaks). Legacy _flush_table mono-block path
and render_pango() public helper are removed."
```

---

## Task 5: Table alignment and inline markup in cells

Extract per-column alignment from `<th style="text-align: ...">` and verify inline markup (`**bold**`, `` `code` ``, links) survives inside cells.

**Files:**
- Modify: `tests/test_markdown_preview.py`
- (No new implementation — Task 4 already reads `style` and uses cell-mode PangoBuilder. These tests verify.)

- [ ] **Step 1: Add tests**

Append:

```python
@pytestmark_md
def test_table_alignment_from_colons() -> None:
    src = "| a | b | c |\n|:--|:-:|--:|\n| 1 | 2 | 3 |\n"
    tb = mp.render_blocks(src)[0]
    assert tb.aligns == [mp.Align.LEFT, mp.Align.CENTER, mp.Align.RIGHT]


@pytestmark_md
def test_table_cell_preserves_inline_markup() -> None:
    src = "| a | b |\n| - | - |\n| **hi** | `x` |\n"
    tb = mp.render_blocks(src)[0]
    assert "<b>hi</b>" in tb.rows[0][0]
    assert 'font_family="monospace"' in tb.rows[0][1]


@pytestmark_md
def test_table_short_row_padded() -> None:
    # Malformed table: header has 3, row has 2 — pad to header width.
    src = "| a | b | c |\n| - | - | - |\n| 1 | 2 |\n"
    tb = mp.render_blocks(src)[0]
    assert len(tb.rows[0]) == 3
    assert tb.rows[0][2] == ""
```

- [ ] **Step 2: Run tests**

Run: `python -m pytest tests/test_markdown_preview.py -v -k "align or cell_preserves or short_row"`
Expected: PASS (implementation from Task 4 already handles these).

- [ ] **Step 3: If any fail, fix**

If `test_table_alignment_from_colons` fails, python-markdown may emit alignment on both `<th>` and `<td>` — the splitter already uses only header-row aligns via the `_in_thead` flag, so this should work. If not, inspect emitted HTML via a debug print and adjust `_handle_table_end` accordingly.

If `test_table_cell_preserves_inline_markup` fails with `**hi**` verbatim, `cell_mode` may be dropping paragraph *content* not just breaks — re-verify the `handle_endtag` change from Task 4 only guards emission of `"\n\n"`.

- [ ] **Step 4: Commit**

```bash
git add tests/test_markdown_preview.py
git commit -m "Test table alignment extraction + cell inline markup"
```

---

## Task 6: Code block extraction — `CodeBlock`

Verify `<pre><code>` boundaries produce a `CodeBlock` with lang and raw text preserved.

**Files:**
- Modify: `tests/test_markdown_preview.py`
- (No new implementation — Task 4 already emits `CodeBlock`.)

- [ ] **Step 1: Add tests**

Append:

```python
@pytestmark_md
def test_render_splits_prose_and_code() -> None:
    src = "before\n\n```python\ndef f():\n    return 1\n```\n\nafter\n"
    blocks = mp.render_blocks(src)
    types = [type(b).__name__ for b in blocks]
    assert types == ["ProseBlock", "CodeBlock", "ProseBlock"]
    cb = blocks[1]
    assert cb.lang == "python"
    assert cb.text == "def f():\n    return 1"


@pytestmark_md
def test_code_block_lang_none_when_absent() -> None:
    src = "```\nplain\ntext\n```\n"
    blocks = mp.render_blocks(src)
    assert isinstance(blocks[0], mp.CodeBlock)
    assert blocks[0].lang is None
    assert blocks[0].text == "plain\ntext"


@pytestmark_md
def test_inline_code_stays_in_prose() -> None:
    # Inline `code` is not a fenced block — must remain in ProseBlock.
    blocks = mp.render_blocks("this is `inline` code")
    assert len(blocks) == 1
    assert isinstance(blocks[0], mp.ProseBlock)
    assert 'font_family="monospace"' in blocks[0].pango_markup
```

- [ ] **Step 2: Run tests**

Run: `python -m pytest tests/test_markdown_preview.py -v -k "splits_prose_and_code or lang_none or inline_code_stays"`
Expected: PASS.

- [ ] **Step 3: If any fail, fix**

If `lang` extraction fails, print `html` in `render_blocks()` for the offending fixture — python-markdown may emit `class="language-python"` or `class="python"` depending on config. Adjust `_parse_lang` accordingly (extend to also strip a bare `python` class).

- [ ] **Step 4: Commit**

```bash
git add tests/test_markdown_preview.py
git commit -m "Test CodeBlock extraction — lang + raw text preservation"
```

---

## Task 7: Heading underlines for h1 and h2

Emit a Unicode underline under h1 (`━`) and h2 (`─`) for stronger visual hierarchy. h3+ untouched.

**Files:**
- Modify: `apedi/markdown_preview.py`
- Modify: `tests/test_markdown_preview.py`

- [ ] **Step 1: Add failing tests**

Append:

```python
@pytestmark_md
def test_heading_underline_h1() -> None:
    m = mp.render_blocks("# Title")[0].pango_markup
    assert "━" in m


@pytestmark_md
def test_heading_underline_h2() -> None:
    m = mp.render_blocks("## Sub")[0].pango_markup
    assert "─" in m


@pytestmark_md
def test_heading_no_underline_h3() -> None:
    m = mp.render_blocks("### Small")[0].pango_markup
    assert "━" not in m
    # The hr uses '─' × 60 — but h3 alone (no hr) must not have '─'.
    assert "─" not in m
```

- [ ] **Step 2: Run tests**

Expected: FAIL — no underlines yet.

- [ ] **Step 3: Implement heading underlines**

In `_PangoBuilder`, track the current heading's text length so the underline matches. Modify `__init__` to add:

```python
        self._heading_char_count: int | None = None  # non-None while inside h1/h2
        self._heading_underline_char: str | None = None
```

In `handle_starttag`, set the counter when entering h1/h2:

Find:
```python
        if tag in _HEADING_SPANS:
            self._emit(_HEADING_SPANS[tag])
```
Replace with:
```python
        if tag in _HEADING_SPANS:
            self._emit(_HEADING_SPANS[tag])
            if tag == "h1":
                self._heading_char_count = 0
                self._heading_underline_char = "━"
            elif tag == "h2":
                self._heading_char_count = 0
                self._heading_underline_char = "─"
```

In `handle_data`, count characters when inside a tracked heading:

Find:
```python
    def handle_data(self, data) -> None:
        if not data:
            return
        if self.in_pre:
            # Preserve whitespace including leading indent
            self._emit(_html_escape(data, quote=False))
        else:
            self._emit_text(data)
```
Replace with:
```python
    def handle_data(self, data) -> None:
        if not data:
            return
        if self._heading_char_count is not None:
            self._heading_char_count += len(data)
        if self.in_pre:
            # Preserve whitespace including leading indent
            self._emit(_html_escape(data, quote=False))
        else:
            self._emit_text(data)
```

In `handle_endtag`, emit the underline after closing h1/h2:

Find:
```python
        if tag in _HEADING_SPANS:
            self._emit("</span>\n\n")
```
Replace with:
```python
        if tag in _HEADING_SPANS:
            self._emit("</span>\n")
            if tag in ("h1", "h2") and self._heading_char_count is not None:
                width = self._heading_char_count + 4
                self._emit(self._heading_underline_char * width + "\n")
                self._heading_char_count = None
                self._heading_underline_char = None
            self._emit("\n")
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_markdown_preview.py -v -k "heading"`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apedi/markdown_preview.py tests/test_markdown_preview.py
git commit -m "Underline h1/h2 headings for visual hierarchy"
```

---

## Task 8: Task list checkboxes

Render `- [x] foo` as `☑ foo` and `- [ ] foo` as `☐ foo`. Read-only.

**Files:**
- Modify: `apedi/markdown_preview.py`
- Modify: `tests/test_markdown_preview.py`

- [ ] **Step 1: Add failing tests**

Append:

```python
@pytestmark_md
def test_task_list_checked() -> None:
    m = mp.render_blocks("- [x] done\n")[0].pango_markup
    assert "☑ done" in m


@pytestmark_md
def test_task_list_unchecked() -> None:
    m = mp.render_blocks("- [ ] todo\n")[0].pango_markup
    assert "☐ todo" in m


@pytestmark_md
def test_task_list_mixed() -> None:
    m = mp.render_blocks("- [x] a\n- [ ] b\n")[0].pango_markup
    assert "☑ a" in m
    assert "☐ b" in m


@pytestmark_md
def test_bullet_list_unchanged_by_task_extension() -> None:
    m = mp.render_blocks("- a\n- b\n- c\n")[0].pango_markup
    assert m.count("• ") == 3
    assert "☐" not in m
    assert "☑" not in m
```

- [ ] **Step 2: Run tests**

Expected: FAIL (the `[x]` / `[ ]` prefix is emitted as literal text today).

- [ ] **Step 3: Implement task list detection**

python-markdown doesn't have a built-in tasklist extension, so we post-process in `_PangoBuilder`. The trick: after emitting the `• ` bullet, the next `handle_data` call in a `<li>` receives the raw text starting with `[x] ` or `[ ] `. Detect and substitute.

Add a `re` import at the top of `apedi/markdown_preview.py`:
```python
import re
```

Add a class-level pattern to `_PangoBuilder`:

Find (in `_PangoBuilder`):
```python
    def __init__(self, dark: bool, cell_mode: bool = False) -> None:
        super().__init__(convert_charrefs=True)
```
Replace with:
```python
    _TASK_RE = re.compile(r"^\[( |x|X)\]\s+")

    def __init__(self, dark: bool, cell_mode: bool = False) -> None:
        super().__init__(convert_charrefs=True)
```

Add a flag `self._li_just_opened: int` that tracks nested `<li>` depth of "just opened":

Add to `__init__`:
```python
        self._li_pending_task: bool = False
```

In `handle_starttag` for `<li>`, set the flag:

Find:
```python
        elif tag == "li":
            kind, count = self.list_stack[-1] if self.list_stack else ("ul", 0)
            indent = "  " * max(0, len(self.list_stack) - 1)
            if kind == "ol":
                count += 1
                self.list_stack[-1] = (kind, count)
                self._emit(f"\n{indent}{count}. ")
            else:
                self._emit(f"\n{indent}• ")
```
Replace with:
```python
        elif tag == "li":
            kind, count = self.list_stack[-1] if self.list_stack else ("ul", 0)
            indent = "  " * max(0, len(self.list_stack) - 1)
            if kind == "ol":
                count += 1
                self.list_stack[-1] = (kind, count)
                self._emit(f"\n{indent}{count}. ")
            else:
                self._emit(f"\n{indent}")  # bullet chosen after peeking at content
                self._li_pending_task = True
```

Modify `handle_data` to peek for task syntax:

Find the block:
```python
    def handle_data(self, data) -> None:
        if not data:
            return
        if self._heading_char_count is not None:
            self._heading_char_count += len(data)
        if self.in_pre:
            self._emit(_html_escape(data, quote=False))
        else:
            self._emit_text(data)
```
Replace with:
```python
    def handle_data(self, data) -> None:
        if not data:
            return
        if self._li_pending_task:
            self._li_pending_task = False
            match = self._TASK_RE.match(data)
            if match:
                marker = "☑ " if match.group(1) in ("x", "X") else "☐ "
                self._emit(marker)
                data = data[match.end():]
                if not data:
                    return
            else:
                self._emit("• ")
        if self._heading_char_count is not None:
            self._heading_char_count += len(data)
        if self.in_pre:
            self._emit(_html_escape(data, quote=False))
        else:
            self._emit_text(data)
```

Also clear the pending flag on any tag boundary (empty `<li>` case). Add at the top of both `handle_starttag` and `handle_endtag`:

At the top of `handle_starttag(self, tag, attrs)`:
```python
        if self._li_pending_task and tag != "li":
            self._emit("• ")
            self._li_pending_task = False
```

At the top of `handle_endtag(self, tag)`:
```python
        if self._li_pending_task:
            self._emit("• ")
            self._li_pending_task = False
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_markdown_preview.py -v -k "task or bullet_list_unchanged"`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apedi/markdown_preview.py tests/test_markdown_preview.py
git commit -m "Render task lists: [x] → ☑, [ ] → ☐

Post-processes the first text token in each <li> — bullet is only
emitted after peeking for the task-list marker."
```

---

## Task 9: Nested blockquotes

Render `> > x` as `│ │ x` (two prefix bars) instead of the single `│ ` that today's implementation emits regardless of depth.

**Files:**
- Modify: `apedi/markdown_preview.py`
- Modify: `tests/test_markdown_preview.py`

- [ ] **Step 1: Add failing test**

Append:

```python
@pytestmark_md
def test_nested_blockquote_double_bar() -> None:
    m = mp.render_blocks("> > deep\n")[0].pango_markup
    assert "│ │ " in m


@pytestmark_md
def test_single_blockquote_still_single_bar() -> None:
    m = mp.render_blocks("> shallow\n")[0].pango_markup
    assert "│ " in m
    assert "│ │ " not in m
```

- [ ] **Step 2: Run test**

Expected: `test_nested_blockquote_double_bar` FAILs (current impl emits single `│` regardless).

- [ ] **Step 3: Track blockquote depth**

In `_PangoBuilder.__init__`, add:
```python
        self._quote_depth: int = 0
```

Modify the `blockquote` branch in `handle_starttag`:

Find:
```python
        elif tag == "blockquote":
            self._emit(f'\n<i><span foreground="{self._quote_fg}">│ ')
```
Replace with:
```python
        elif tag == "blockquote":
            self._quote_depth += 1
            prefix = "│ " * self._quote_depth
            self._emit(f'\n<i><span foreground="{self._quote_fg}">{prefix}')
```

Modify `handle_endtag` for `blockquote`:

Find:
```python
        elif tag == "blockquote":
            self._emit("</span></i>\n")
```
Replace with:
```python
        elif tag == "blockquote":
            self._emit("</span></i>\n")
            self._quote_depth = max(0, self._quote_depth - 1)
```

- [ ] **Step 4: Run tests**

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apedi/markdown_preview.py tests/test_markdown_preview.py
git commit -m "Nested blockquotes: prefix bar per depth level"
```

---

## Task 10: Nested list indent per depth

Verify that nested lists produce distinct indentation levels. The existing `_PangoBuilder` already indents by `list_stack` depth × 2 spaces, so this is likely already working — but the test locks in the behavior.

**Files:**
- Modify: `tests/test_markdown_preview.py`

- [ ] **Step 1: Add test**

Append:

```python
@pytestmark_md
def test_nested_lists_indent() -> None:
    src = "- a\n    - b\n        - c\n"
    m = mp.render_blocks(src)[0].pango_markup
    # Level 0 has no indent prefix; level 1 has "  "; level 2 has "    ".
    assert "\n• a" in m or m.startswith("• a")
    assert "\n  • b" in m
    assert "\n    • c" in m
```

- [ ] **Step 2: Run test**

Expected: possibly PASS immediately (existing indent logic). If FAIL, python-markdown may emit different nesting HTML than expected.

- [ ] **Step 3: If fail — inspect HTML and adjust indent formula**

Add a temporary print in `render_blocks()`:
```python
print(html)  # DEBUG
```
Run the test, read the emitted HTML, remove the print. If HTML nests correctly (`<ul><li>a<ul><li>b<ul><li>c</li></ul></li></ul></li></ul>`), the current indent formula works. If python-markdown emits `<p>` wrappers around nested list content, task list changes from Task 8 already handle that.

- [ ] **Step 4: Commit**

```bash
git add tests/test_markdown_preview.py
git commit -m "Lock in nested-list indent depth in tests"
```

---

## Task 11: CSS additions in `apedi/style.py`

Add selectors for `.apedi-md-table` and `.apedi-md-code`.

**Files:**
- Modify: `apedi/style.py`
- Modify: `tests/test_markdown_preview.py`

- [ ] **Step 1: Add failing test**

Append to `tests/test_markdown_preview.py`:

```python
def test_style_contains_new_selectors() -> None:
    # Style module must expose the CSS bytes for the preview to consume.
    from apedi import style
    css = style._CSS.decode("utf-8")
    assert ".apedi-md-table" in css
    assert ".apedi-md-code" in css
```

- [ ] **Step 2: Run test**

Expected: FAIL — selectors not yet in `_CSS`.

- [ ] **Step 3: Append CSS**

Open `apedi/style.py`. Find the closing `"""` of `_CSS` (line ~48):

```python
aboutdialog button.link:focus { text-decoration: none; }
"""
```

Insert the new rules **before** the closing `"""`:

```css

/* Markdown preview — tables */
frame.apedi-md-table {
    border: 1px solid alpha(currentColor, 0.15);
    border-radius: 6px;
    margin: 8px 0;
}
.apedi-md-table > grid > label {
    padding: 6px 12px;
    background: transparent;
}
.apedi-md-table > grid > label.header {
    font-weight: bold;
    background: alpha(currentColor, 0.06);
    border-bottom: 1px solid alpha(currentColor, 0.15);
}
.apedi-md-table > grid > label.odd {
    background: alpha(currentColor, 0.03);
}

/* Markdown preview — code blocks */
frame.apedi-md-code {
    background: alpha(currentColor, 0.06);
    border: 1px solid alpha(currentColor, 0.10);
    border-radius: 6px;
    margin: 8px 0;
}
.apedi-md-code > * {
    padding: 10px 14px;
}
.apedi-md-code label {
    font-family: monospace;
}
```

- [ ] **Step 4: Run test**

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apedi/style.py tests/test_markdown_preview.py
git commit -m "Style: add .apedi-md-table and .apedi-md-code selectors"
```

---

## Task 12: `_BlockRenderer` — build widgets from Blocks

Introduce the dispatcher that turns each `Block` into a GTK widget. Kept as a separate task from the widget rewrite (Task 13) so the diff of each is contained.

**Files:**
- Modify: `apedi/markdown_preview.py`

- [ ] **Step 1: Add `_BlockRenderer` class**

Inside `if GTK_AVAILABLE:` block, **before** the `class MarkdownPreview(...)` definition, insert:

```python
    class _BlockRenderer:
        """Maps Block dataclasses to fresh GTK widgets."""

        def __init__(
            self,
            on_activate_link: Callable[["Gtk.Label", str], bool],
        ) -> None:
            self._on_activate_link = on_activate_link

        def build(self, block: Block) -> "Gtk.Widget":
            if isinstance(block, ProseBlock):
                return self._build_prose(block)
            if isinstance(block, TableBlock):
                return self._build_table(block)
            if isinstance(block, CodeBlock):
                return self._build_code(block)
            raise TypeError(f"Unknown block type: {type(block).__name__}")

        def _build_prose(self, block: ProseBlock) -> "Gtk.Label":
            label = Gtk.Label()
            label.set_use_markup(True)
            label.set_selectable(True)
            label.set_wrap(True)
            label.set_wrap_mode(2)  # PANGO_WRAP_WORD_CHAR
            label.set_xalign(0.0)
            label.set_yalign(0.0)
            label.set_valign(Gtk.Align.START)
            label.set_halign(Gtk.Align.FILL)
            label.set_markup(block.pango_markup)
            label.connect("activate-link", self._on_activate_link)
            return label

        def _build_table(self, block: TableBlock) -> "Gtk.Widget":
            frame = Gtk.Frame()
            frame.add_css_class("apedi-md-table")
            grid = Gtk.Grid()
            grid.set_column_homogeneous(False)

            xalign_for = {
                Align.LEFT: 0.0,
                Align.CENTER: 0.5,
                Align.RIGHT: 1.0,
            }

            for col, cell_markup in enumerate(block.header):
                lbl = self._cell_label(cell_markup, xalign_for[block.aligns[col]])
                lbl.add_css_class("header")
                grid.attach(lbl, col, 0, 1, 1)

            for row_idx, row in enumerate(block.rows):
                zebra = "odd" if row_idx % 2 else "even"
                for col, cell_markup in enumerate(row):
                    align = block.aligns[col] if col < len(block.aligns) else Align.LEFT
                    lbl = self._cell_label(cell_markup, xalign_for[align])
                    lbl.add_css_class(zebra)
                    grid.attach(lbl, col, row_idx + 1, 1, 1)

            frame.set_child(grid)
            return frame

        def _cell_label(self, markup: str, xalign: float) -> "Gtk.Label":
            lbl = Gtk.Label()
            lbl.set_use_markup(True)
            lbl.set_selectable(True)
            lbl.set_wrap(True)
            lbl.set_wrap_mode(2)
            lbl.set_xalign(xalign)
            lbl.set_yalign(0.0)
            lbl.set_valign(Gtk.Align.START)
            lbl.set_hexpand(True)
            lbl.set_markup(markup)
            lbl.connect("activate-link", self._on_activate_link)
            return lbl

        def _build_code(self, block: CodeBlock) -> "Gtk.Widget":
            frame = Gtk.Frame()
            frame.add_css_class("apedi-md-code")
            scroller = Gtk.ScrolledWindow()
            scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER)
            scroller.set_hexpand(True)
            label = Gtk.Label()
            label.set_text(block.text)
            label.set_xalign(0.0)
            label.set_yalign(0.0)
            label.set_valign(Gtk.Align.START)
            label.set_halign(Gtk.Align.START)
            label.set_selectable(True)
            label.set_wrap(False)
            scroller.set_child(label)
            frame.set_child(scroller)
            return frame
```

- [ ] **Step 2: No test yet** — dispatcher lives inside the `if GTK_AVAILABLE:` block and can't be tested headless without GTK on the system.

Run: `python -m pytest tests/test_markdown_preview.py -v`
Expected: all previous tests still PASS (no behavior change to the pure layer).

- [ ] **Step 3: Commit**

```bash
git add apedi/markdown_preview.py
git commit -m "Add _BlockRenderer: dispatch Block -> GTK widget

Prose -> Label. Table -> Frame + Grid with header/zebra CSS classes and
per-column xalign. Code -> Frame + horizontal ScrolledWindow + monospace
Label. Not yet wired into MarkdownPreview."
```

---

## Task 13: Rewire `MarkdownPreview` to use `GtkBox` + `_BlockRenderer`

Replace the single `GtkLabel` with a `GtkBox(vertical)` populated per-block by `_BlockRenderer`.

**Files:**
- Modify: `apedi/markdown_preview.py`

- [ ] **Step 1: Rewrite the `MarkdownPreview` widget**

Locate the existing `class MarkdownPreview(Gtk.ScrolledWindow):` block. Replace **the entire class body** (keep the class declaration and `__gtype_name__`) with:

```python
    class MarkdownPreview(Gtk.ScrolledWindow):
        """A pane that renders markdown as a vertical stack of per-block widgets.

        Updates are debounced (~250 ms) so live typing stays responsive.
        Prose blocks are Pango-rendered GtkLabels; tables are GtkGrids with
        CSS borders/header/zebra; code blocks are bordered rectangles.
        """

        __gtype_name__ = "ApediMarkdownPreview"

        def __init__(self) -> None:
            super().__init__()
            self.set_hexpand(True)
            self.set_vexpand(True)
            self.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
            self._dark: bool = False  # kept for API compatibility; unused
            self._pending_text: str = ""
            self._pending_base: Path | None = None
            self._timer_id: int | None = None
            self._last_rendered_text: str | None = None
            self.on_open_path: Callable[[Path], None] | None = None

            self._box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
            self._box.set_hexpand(True)
            self._box.set_vexpand(False)
            self._box.set_valign(Gtk.Align.START)
            self._box.set_halign(Gtk.Align.FILL)
            self._box.set_margin_start(20)
            self._box.set_margin_end(20)
            self._box.set_margin_top(16)
            self._box.set_margin_bottom(16)

            self._renderer = _BlockRenderer(on_activate_link=self._on_activate_link)

            if not AVAILABLE:
                fallback = Gtk.Label()
                fallback.set_text(_("Markdown preview unavailable (python-markdown missing)"))
                fallback.set_xalign(0.0)
                self._box.append(fallback)

            self.set_child(self._box)

        def set_dark(self, is_dark: bool) -> None:
            # Colors use alpha(currentColor,...) so no per-mode render needed.
            self._dark = is_dark

        def update(self, text: str, base_path: Path | None) -> None:
            """Schedule a debounced render of `text`."""
            if not AVAILABLE:
                return
            self._pending_text = text
            self._pending_base = base_path
            if self._timer_id is not None:
                GLib.source_remove(self._timer_id)
            self._timer_id = GLib.timeout_add(DEBOUNCE_MS, self._fire)

        def flush(self) -> None:
            """Render any pending update synchronously."""
            if not AVAILABLE:
                return
            if self._timer_id is not None:
                GLib.source_remove(self._timer_id)
                self._timer_id = None
            self._render_now(self._pending_text, self._pending_base)

        def _fire(self) -> bool:
            self._timer_id = None
            self._render_now(self._pending_text, self._pending_base)
            return False

        def _render_now(self, text: str, base_path: Path | None) -> None:
            # First-render path: python-markdown hasn't been imported yet
            # (~50 ms cost). Show a placeholder, defer real render to idle.
            if MARKDOWN_AVAILABLE and _md is None:
                self._show_placeholder(_("Loading preview…"))
                GLib.idle_add(self._render_after_load, text, base_path)
                return
            self._render_blocks(text)
            self._last_rendered_text = text

        def _render_after_load(self, text: str, base_path: Path | None) -> bool:
            self._render_blocks(text)
            self._last_rendered_text = text
            return False

        def _render_blocks(self, text: str) -> None:
            self._clear_box()
            for block in render_blocks(text):
                self._box.append(self._renderer.build(block))

        def _clear_box(self) -> None:
            child = self._box.get_first_child()
            while child is not None:
                nxt = child.get_next_sibling()
                self._box.remove(child)
                child = nxt

        def _show_placeholder(self, msg: str) -> None:
            self._clear_box()
            label = Gtk.Label()
            label.set_markup(f"<i>{_html_escape(msg, quote=False)}</i>")
            label.set_xalign(0.0)
            self._box.append(label)

        def _on_activate_link(self, _label: "Gtk.Label", uri: str) -> bool:
            if not uri:
                return True
            if uri.startswith(("http://", "https://")):
                try:
                    launcher = Gtk.UriLauncher.new(uri)
                    launcher.launch(self.get_root(), None, lambda *_: None)
                except Exception:
                    log.exception("UriLauncher failed for %s", uri)
                return True
            if uri.startswith("mailto:"):
                try:
                    Gio.AppInfo.launch_default_for_uri(uri, None)
                except GLib.Error:
                    log.debug("mailto launch failed for %s", uri)
                return True
            if uri.startswith("file://"):
                local = Path(uri[len("file://"):].split("#", 1)[0])
            else:
                base = self._pending_base or Path.home()
                if not base.is_dir():
                    base = base.parent
                local = (base / uri).resolve()
            if self.on_open_path is not None and local.is_file():
                self.on_open_path(local)
            return True
```

- [ ] **Step 2: Run existing tests**

Run: `python -m pytest tests/test_markdown_preview.py -v`
Expected: all PASS (pure layer unchanged).

- [ ] **Step 3: Static import check**

Run: `python -c "import apedi.markdown_preview; print('ok')"`
Expected: prints `ok` (module imports without GTK errors).

- [ ] **Step 4: Commit**

```bash
git add apedi/markdown_preview.py
git commit -m "MarkdownPreview: swap single Label for GtkBox + _BlockRenderer

Each markdown block becomes its own widget. Tables render as real
GtkGrid with borders/header/zebra; code blocks as full-width bordered
rectangles. set_dark() becomes a no-op — colors use alpha(currentColor)
via CSS so themes swap automatically."
```

---

## Task 14: Manual smoke test

There is no display in CI, so no automated GTK test. This step is a manual verification.

**Files:** none (runtime check).

- [ ] **Step 1: Launch apedi with a rich markdown file**

Run: `cd /home/aprus/www/editor && python -m apedi CHANGELOG.md`

- [ ] **Step 2: Verify visually**

Toggle the preview pane. Check:

- Headings show with underline for h1/h2
- Bullet and numbered lists render
- Code blocks appear as a full-width bordered rectangle with monospace text; long lines scroll horizontally
- Any tables render with visible borders, bold header, alternating row background
- Inline code has the subtle background
- Toggle to dark theme in system settings — visuals adapt automatically (no need to close/reopen)

- [ ] **Step 3: Open a markdown file with a table**

Create a test file `/tmp/table-test.md`:

```markdown
# Test table

| Feature | Status | Notes |
|:--------|:------:|------:|
| **Tables** | ✓ | with `code` |
| Nested lists | ✓ | up to 3 levels |
| Task lists | ✓ | `☑` / `☐` |

## Task list

- [x] one
- [ ] two
- [x] three

## Nested quote

> outer
> > inner

## Code

```python
def hello():
    return "world"
```
```

Then: `python -m apedi /tmp/table-test.md`

Verify:
- Table shows with borders, `Feature` left-aligned, `Status` centered, `Notes` right-aligned; **bold** and `code` inside cells work
- Task list shows `☑` and `☐`
- Nested blockquote shows `│ │` prefix
- Code block is monospace in a bordered rectangle

- [ ] **Step 4: If any visual issue — file a follow-up**

If something looks off but the tests pass, note the issue for a follow-up commit. Do not fake success.

- [ ] **Step 5: No commit needed** — this is a runtime check only.

---

## Task 15: Version bump + CHANGELOG + snap manifest

Following the project's rule: bump PATCH even for multi-feature releases.

**Files:**
- Modify: `apedi/__init__.py`
- Modify: `pyproject.toml`
- Modify: `snap/snapcraft.yaml`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Bump version in `apedi/__init__.py`**

Change:
```python
__version__ = "0.7.9"
```
to:
```python
__version__ = "0.7.10"
```

- [ ] **Step 2: Bump version in `pyproject.toml`**

Find the `version = "0.7.9"` line under `[project]` and change to `version = "0.7.10"`.

- [ ] **Step 3: Bump version in `snap/snapcraft.yaml`**

Find `version: '0.7.9'` (or unquoted) and change to `0.7.10`.

- [ ] **Step 4: Add CHANGELOG entry**

Prepend a new section under the top header of `CHANGELOG.md`:

```markdown
## 0.7.10 — 2026-07-01

### Improved

- Markdown preview: real tables (bordered `GtkGrid` with header/zebra/alignment)
- Markdown preview: code blocks render as full-width bordered rectangles
- Markdown preview: task lists render as `☑` / `☐`
- Markdown preview: `h1` / `h2` headings get an underline for visual hierarchy
- Markdown preview: nested blockquotes show one prefix bar per depth level
- Markdown preview: refactored to a block-level renderer — HTML → dataclass Blocks → per-block widgets
```

- [ ] **Step 5: Confirm test suite still passes**

Run: `python -m pytest tests/ -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add apedi/__init__.py pyproject.toml snap/snapcraft.yaml CHANGELOG.md
git commit -m "Release 0.7.10 — block-level markdown preview

Tables, code blocks, task lists, heading underlines, nested
blockquotes."
```

---

## Notes for the implementer

- Every task builds on the previous — do NOT skip ahead. Tests from earlier tasks must keep passing.
- If a python-markdown emitted HTML shape surprises a test, add a temporary `print(html)` in `render_blocks()` to inspect, then remove before committing.
- `_PangoBuilder` is stateful and gets several small extensions across tasks — make sure new attributes are initialized in `__init__`, not lazily.
- The GTK layer (`_BlockRenderer` + `MarkdownPreview`) is not covered by automated tests. Task 14 (manual smoke) is the only verification. Do not skip it.
- Do NOT introduce a new external library. If you find yourself reaching for `pygments`, `markdown-it-py`, `bleach`, etc. — stop and re-read the constraint in the spec.
