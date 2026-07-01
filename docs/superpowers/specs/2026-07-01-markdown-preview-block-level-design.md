# Markdown preview — block-level rendering

**Date:** 2026-07-01
**Module:** `apedi/markdown_preview.py`
**Status:** Approved for implementation

## Problem

Current preview renders every markdown document into a single `GtkLabel`
with Pango markup. This has hard limits:

- Tables become a monospace text block with space-padded columns — no
  borders, no header emphasis, no per-column alignment.
- `<span background=...>` in Pango colors the run **behind glyphs**, not
  a full-width rectangle → code blocks look like "highlighted text",
  not a code block.
- Multi-line list items wrap back to column 0 (no hanging indent).
- No task list rendering, no nested-blockquote visualization, no
  visual hierarchy break for h1/h2.

User feedback: "preview jest bardzo słabe, nie obsługuje tabel".

## Constraints

- **No new external libraries.** `python-markdown` (already a dep) stays
  the only markdown parser. GTK4 already available.
- **Snap must stay lean** — no WebKit, no Pygments, no HTML rendering
  engine.
- **Public API compatibility** — `is_markdown_path`, `MARKDOWN_AVAILABLE`,
  `AVAILABLE`, `MD_EXTENSIONS`, and the `MarkdownPreview` widget methods
  (`update`, `flush`, `set_dark`, `on_open_path`) keep their signatures.
- **Headless testability** — the parsing layer must be testable without
  GTK, as today.

## Architecture

`MarkdownPreview` changes from `ScrolledWindow → GtkLabel` to
`ScrolledWindow → GtkBox(vertical)`, where each top-level markdown block
becomes its own widget:

```
GtkScrolledWindow
└── GtkBox (vertical)
    ├── GtkLabel                  # ProseBlock: headings, paragraphs, lists, quotes
    ├── GtkFrame.apedi-md-table   # TableBlock
    │   └── GtkGrid
    │       ├── row 0: header cells (GtkLabel.header)
    │       └── rows 1..N: body cells (GtkLabel.even / .odd)
    ├── GtkFrame.apedi-md-code    # CodeBlock
    │   └── GtkScrolledWindow (horizontal)
    │       └── GtkLabel (monospace)
    └── ... (more blocks)
```

### Data model

Rendering is split into two layers:

**1. Pure function (headless-testable):**

```python
def render_blocks(text: str) -> list[Block]
```

**2. Widget dispatcher:**

Private `_BlockRenderer` maps each `Block` type to a GTK widget and
attaches the link-activation handler.

### Block union

```python
from dataclasses import dataclass
from enum import Enum

class Align(Enum):
    LEFT = "left"
    CENTER = "center"
    RIGHT = "right"

@dataclass(frozen=True)
class ProseBlock:
    pango_markup: str

@dataclass(frozen=True)
class TableBlock:
    header: list[str]           # each cell already Pango markup
    rows: list[list[str]]       # rectangular; short rows padded with ""
    aligns: list[Align]         # len == len(header)

@dataclass(frozen=True)
class CodeBlock:
    text: str                   # raw text, no markup
    lang: str | None            # from ```lang; preserved for future syntax highlighting

Block = ProseBlock | TableBlock | CodeBlock
```

### Pipeline

1. `markdown.Markdown(extensions=["fenced_code", "tables", "sane_lists"]).convert(text)` → HTML.
   **`nl2br` removed** — its per-newline `<br>` was breaking list-item wrapping.
2. `_BlockSplitter(HTMLParser)` walks the HTML:
   - `<table>...</table>` → `TableBlock` (each cell processed by
     `_PangoBuilder` in "cell mode" — no outer `<p>` wrapping)
   - `<pre><code>...</code></pre>` → `CodeBlock` (raw text preserved,
     lang extracted from `class="language-..."`)
   - Everything else → accumulated into a running `ProseBlock`. A
     `TableBlock` or `CodeBlock` boundary flushes the accumulator.
3. `render_blocks()` returns the list, dropping any `ProseBlock` whose
   markup is empty after strip.

## Per-block rendering rules

### ProseBlock — Pango markup in `GtkLabel`

`_PangoBuilder` (today's HTML → Pango converter) is refactored to be
reusable per cell and gets these new behaviors:

| Feature | How |
|---|---|
| **h1 / h2 underline** | after `</h1>`: emit `\n` + `━` × (text_len + 4); same for h2 with `─`. h3+ unchanged. |
| **Task lists** | on `<li>` start, peek next text data; if matches `^\[([ xX])\]\s+`, replace with `☑ ` or `☐ `. |
| **Nested blockquotes** | track `blockquote` depth; per-line prefix is `│ ` × depth (not just `│ `). |
| **Nested list indent** | `"  " × depth` (up to any depth; Pango can't do hanging indent in a Label, so wrapped lines still return to column 0 — documented limit). |
| **hr** | `─` × 60 (unchanged) |
| **img** | `[🖼 name]` clickable placeholder (unchanged) |
| **Inline code, bold, italic, links** | unchanged |

Cell mode (`_PangoBuilder(cell_mode=True)`): does NOT emit paragraph
breaks or heading underlines; used for `TableBlock` cells so inline
markup (`**bold**`, `` `code` ``, links) works inside cells.

### TableBlock — `GtkGrid` inside `GtkFrame`

- `GtkFrame` with CSS class `apedi-md-table`
- `GtkGrid` inside, `column_homogeneous=False`
- Header row (row 0): each `GtkLabel` gets CSS class `header`
- Body rows: `GtkLabel` with CSS class `even` / `odd` (zebra)
- Each label: `set_use_markup(True)`, `set_wrap(True)`,
  `set_wrap_mode(WORD_CHAR)`, `set_xalign(0.0 | 0.5 | 1.0)` per `Align`
- Column alignment extracted from python-markdown's `style="text-align: ..."`
  emitted on `<th>` / `<td>`

### CodeBlock — `GtkFrame` + `GtkScrolledWindow` + monospace `GtkLabel`

- `GtkFrame` with CSS class `apedi-md-code`
- Inner `GtkScrolledWindow` with horizontal-only scrolling (long lines
  scroll, do not wrap — standard code behavior)
- `GtkLabel` monospace, `xalign=0`, selectable, `wrap=False`
- `lang` is stored on the block for future syntax highlighting but
  not used yet

## CSS (new — added to `apedi/style.py`)

```css
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

All colors use `alpha(currentColor, ...)` so light and dark themes need
no per-mode swaps — same technique as today's Pango `background_alpha`.

## Widget lifecycle

Re-render on update:

```python
def _render_now(self, text, base_path):
    blocks = render_blocks(text)
    child = self._box.get_first_child()
    while child is not None:
        nxt = child.get_next_sibling()
        self._box.remove(child)
        child = nxt
    for block in blocks:
        widget = self._renderer.build(block)
        self._box.append(widget)
```

`_BlockRenderer.build(block)` dispatches on type and returns a fresh
widget with the link-activation handler attached where needed
(prose labels + every cell in table labels).

**No widget recycling** in v1. Debounce is 250 ms, typical documents are
small; if perf ever hurts, recycle per block type — YAGNI on start.

### `set_dark()`

Becomes effectively a no-op for rendering (all colors are alpha-based).
Kept in the API for compatibility; still records `self._dark` for any
future need. No re-render is triggered by a theme change because the
markup is theme-agnostic.

### Link activation

Every `GtkLabel` that carries markup (prose + table cells) gets the same
`activate-link` handler (`_on_activate_link`). Behavior unchanged:

- `http(s)://` → `Gtk.UriLauncher`
- `mailto:` → `Gio.AppInfo.launch_default_for_uri`
- Relative / `file://` → resolve against `base_path`, invoke
  `on_open_path` callback if it points at an existing file

## Testing

All tests are headless — they call `render_blocks(text)` and assert on
the returned `list[Block]`. No GTK required.

### Retained tests

- `test_is_markdown_path_none / _yes / _no`
- `test_module_import_does_not_load_markdown`

### New / rewritten tests

| Test | Assertion |
|---|---|
| `test_render_blocks_returns_list` | `render_blocks("hi")` returns `[ProseBlock]` with markup containing `"hi"` |
| `test_render_blocks_splits_prose_and_table` | prose + table + prose → `[ProseBlock, TableBlock, ProseBlock]` |
| `test_render_blocks_splits_prose_and_code` | prose + fenced code + prose → `[ProseBlock, CodeBlock, ProseBlock]` |
| `test_table_header_and_rows` | header list matches, body rows match, count correct |
| `test_table_alignment_from_colons` | `\|:--\|:-:\|--:\|` → `[LEFT, CENTER, RIGHT]` |
| `test_table_cell_preserves_inline_markup` | `**bold**` in cell → `<b>bold</b>` in cell markup |
| `test_code_block_is_isolated` | `` ```python\n... ``` `` → `CodeBlock` with `lang="python"`, raw text preserved (including newlines) |
| `test_code_block_lang_none_when_absent` | fenced with no lang → `lang is None` |
| `test_heading_underline_h1` | `# T` → prose markup contains `━` |
| `test_heading_underline_h2` | `## S` → prose markup contains `─` |
| `test_heading_no_underline_h3` | `### X` → prose markup has neither |
| `test_task_list_checked` | `- [x] foo` → prose markup contains `☑ foo` |
| `test_task_list_unchecked` | `- [ ] foo` → prose markup contains `☐ foo` |
| `test_bullet_list_unchanged` | `- a\n- b` → 2 bullets, no `☐` |
| `test_nested_blockquote_double_bar` | `> > x` → prose markup contains `│ │ ` |
| `test_nested_lists_indent` | `- a\n  - b\n    - c` → 3 distinct indent levels present |
| `test_link_still_works` | `[here](https://example.com)` → `<a href=...>here</a>` in prose markup |
| `test_mailto_link` | `mailto:` link renders |
| `test_image_placeholder` | `![alt](path.png)` → `[🖼 path.png]` clickable |
| `test_hr` | `---` → `─` × 60 |
| `test_empty_prose_blocks_dropped` | leading / trailing whitespace only → no empty `ProseBlock` in output |
| `test_style_contains_new_selectors` | `apedi.style` CSS string contains `.apedi-md-table` and `.apedi-md-code` |

### Removed tests

- `test_render_pango` (function no longer exists as public helper)
- `test_render_table_as_mono_block` (superseded by `test_render_blocks_splits_prose_and_table`)
- `test_render_uses_alpha_so_works_on_both_themes` (behavior moved to CSS; covered by `test_style_contains_new_selectors`)

## Migration plan

1. Add dataclasses (`Align`, `ProseBlock`, `TableBlock`, `CodeBlock`)
2. Refactor `_PangoBuilder` — extract cell mode, add heading underlines, task lists, nested-blockquote depth, deeper list indent
3. Write `_BlockSplitter` (HTMLParser subclass, dispatches to per-type buffers)
4. Write `render_blocks(text) -> list[Block]`
5. Rewrite `MarkdownPreview.__init__` to build a `GtkBox` instead of a single `GtkLabel`
6. Write `_BlockRenderer` (dispatch on block type → widget)
7. Rewire `_render_now` and `_render_after_load` to build blocks, clear box, append widgets
8. Attach `activate-link` handler via helper on every prose label + table cell label
9. Add new CSS selectors to `apedi/style.py`
10. Rewrite `tests/test_markdown_preview.py` around `render_blocks`
11. Manual smoke test: open `CHANGELOG.md` and `README.md` in apedi, verify light + dark
12. Bump version 0.7.9 → 0.7.10 (`snap/snapcraft.yaml` + `pyproject.toml` + `apedi/__init__.py` + `CHANGELOG.md` entry)

## Out of scope (explicitly)

- Syntax highlighting inside code blocks (Pygments would be a new dep)
- Real image thumbnails (would need async loading + cache)
- Clickable / toggleable task lists (preview stays read-only)
- Internal `#heading` anchors within the same document
- Diff-based widget recycling on re-render (YAGNI until perf hurts)

## Risks

- **More widget allocations per update.** Debounced to 250 ms; typical
  docs are small. If a real doc regresses, recycle per block type.
- **Nested list wrapping still returns to column 0.** Pango markup on a
  Label can't do hanging indent. Documented limit; would need per-item
  widgets to fix (not worth the complexity now).
- **Table cell rendering uses full `_PangoBuilder` in cell mode.** Weird
  MD like a `<pre>` inside a table cell would render oddly. Realistic
  markdown doesn't nest this way; acceptable.
