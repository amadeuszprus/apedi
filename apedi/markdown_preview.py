"""Markdown preview — Pango-rendered pane.

Renders the current buffer's markdown into a `GtkLabel` via Pango markup.
No WebKit, no HTML — keeps the snap lean and the renderer fast.

Public surface (kept stable from the WebKit-era implementation):
- `is_markdown_path(path)` — extension check, no GTK needed.
- `MARKDOWN_AVAILABLE` — True iff python-markdown is importable.
- `AVAILABLE` — True iff both GTK is available and python-markdown is too.
- `render_blocks(text)` — pure function, headless-testable.
- `MarkdownPreview` widget (Gtk.ScrolledWindow):
    `update(text, base_path)`, `flush()`, `set_dark(is_dark)`,
    `on_open_path: Callable[[Path], None] | None`.

The python-markdown library is imported lazily on first render so the
module's import is cheap even when the user never opens a markdown file.
"""

from __future__ import annotations

import builtins
import importlib.util as _importlib_util
import logging
import re
from html import escape as _html_escape
from html.parser import HTMLParser
from pathlib import Path
from dataclasses import dataclass
from enum import Enum
from typing import Callable

if not hasattr(builtins, "_"):
    builtins._ = lambda s: s  # type: ignore[attr-defined]

log = logging.getLogger(__name__)

try:
    import gi

    gi.require_version("Gtk", "4.0")
    from gi.repository import Gio, GLib, Gtk  # noqa: E402
    GTK_AVAILABLE = True
except (ImportError, ValueError) as _e:
    GTK_AVAILABLE = False
    log.info("Gtk not available — markdown preview disabled: %s", _e)
    Gio = GLib = Gtk = None  # type: ignore[assignment]


MARKDOWN_AVAILABLE = _importlib_util.find_spec("markdown") is not None
_md = None  # populated by _ensure_md() on first render

if not MARKDOWN_AVAILABLE:
    log.info("python-markdown not available — markdown preview disabled")


def _ensure_md() -> bool:
    global _md
    if _md is not None:
        return True
    if not MARKDOWN_AVAILABLE:
        return False
    import markdown
    _md = markdown
    return True


AVAILABLE = GTK_AVAILABLE and MARKDOWN_AVAILABLE

MD_EXTENSIONS = {".md", ".markdown", ".mdown", ".mkd", ".mkdn"}

DEBOUNCE_MS = 250


def is_markdown_path(path: Path | None) -> bool:
    if path is None:
        return False
    return path.suffix.lower() in MD_EXTENSIONS


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


# ---------- HTML → Pango converter ----------

_HEADING_SPANS = {
    "h1": '<span size="xx-large" weight="bold">',
    "h2": '<span size="x-large" weight="bold">',
    "h3": '<span size="large" weight="bold">',
    "h4": '<span weight="bold">',
    "h5": '<span size="small" weight="bold">',
    "h6": '<span size="small" weight="bold">',
}

_HR = "─" * 60


class _PangoBuilder(HTMLParser):
    """Walks markdown's HTML output and emits Pango markup.

    Tables are buffered and rendered as a monospace block with columns
    aligned by widest cell. Images become clickable text placeholders.
    """

    _TASK_RE = re.compile(r"^\[( |x|X)\]\s+")

    def __init__(self, dark: bool, cell_mode: bool = False) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.list_stack: list[tuple[str, int]] = []  # (kind, counter)
        self.in_pre = False
        self.cell_mode = cell_mode
        # Mid-gray with low alpha so code blocks read well on both light
        # and dark themes — no need to swap colors per theme.
        self._code_bg = "#808080"
        self._code_bg_alpha = "10000"  # ~15% of 65535
        self._quote_fg = "#999999"
        self._heading_char_count: int | None = None  # non-None while inside h1/h2
        self._heading_underline_char: str | None = None
        self._li_pending_task: bool = False
        self._quote_depth: int = 0

    # ---- helpers ----

    def _emit(self, s: str) -> None:
        self.out.append(s)

    def _emit_text(self, s: str) -> None:
        self._emit(_html_escape(s, quote=False))

    # ---- start tags ----

    def handle_starttag(self, tag, attrs) -> None:
        if self._li_pending_task and tag != "li":
            self._emit("• ")
            self._li_pending_task = False
        attrs_d = dict(attrs)
        if tag in _HEADING_SPANS:
            self._emit(_HEADING_SPANS[tag])
            if tag == "h1":
                self._heading_char_count = 0
                self._heading_underline_char = "━"
            elif tag == "h2":
                self._heading_char_count = 0
                self._heading_underline_char = "─"
        elif tag in ("strong", "b"):
            self._emit("<b>")
        elif tag in ("em", "i"):
            self._emit("<i>")
        elif tag == "code":
            if not self.in_pre:
                self._emit(f'<span background="{self._code_bg}" background_alpha="{self._code_bg_alpha}" font_family="monospace">')
        elif tag == "pre":
            self.in_pre = True
            self._emit(f'<span background="{self._code_bg}" background_alpha="{self._code_bg_alpha}" font_family="monospace">')
        elif tag == "br":
            self._emit("\n")
        elif tag == "hr":
            self._emit(f"\n{_HR}\n")
        elif tag == "a":
            href = attrs_d.get("href", "") or ""
            self._emit(f'<a href="{_html_escape(href, quote=True)}">')
        elif tag == "ul":
            self.list_stack.append(("ul", 0))
        elif tag == "ol":
            self.list_stack.append(("ol", 0))
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
        elif tag == "blockquote":
            self._quote_depth += 1
            prefix = "│ " * self._quote_depth
            self._emit(f'\n<i><span foreground="{self._quote_fg}">{prefix}')
        elif tag == "img":
            src = attrs_d.get("src", "") or ""
            name = src.rsplit("/", 1)[-1] or src or "image"
            self._emit(
                f'<a href="{_html_escape(src, quote=True)}">'
                f'[🖼 {_html_escape(name, quote=False)}]</a>'
            )
        # p, table, tbody, thead, etc. — handled by data flow or _BlockSplitter

    # ---- end tags ----

    def handle_endtag(self, tag) -> None:
        if self._li_pending_task:
            self._emit("• ")
            self._li_pending_task = False
        if tag in _HEADING_SPANS:
            self._emit("</span>\n")
            if tag in ("h1", "h2") and self._heading_char_count is not None:
                width = self._heading_char_count + 4
                self._emit(self._heading_underline_char * width + "\n")
                self._heading_char_count = None
                self._heading_underline_char = None
            self._emit("\n")
        elif tag in ("strong", "b"):
            self._emit("</b>")
        elif tag in ("em", "i"):
            self._emit("</i>")
        elif tag == "code":
            if not self.in_pre:
                self._emit("</span>")
        elif tag == "pre":
            self.in_pre = False
            self._emit("</span>\n")
        elif tag == "p":
            if not self.cell_mode:
                self._emit("\n\n")
        elif tag == "a":
            self._emit("</a>")
        elif tag in ("ul", "ol"):
            if self.list_stack:
                self.list_stack.pop()
            if not self.list_stack:
                self._emit("\n")
        elif tag == "blockquote":
            self._emit("</span></i>\n")
            self._quote_depth = max(0, self._quote_depth - 1)

    # ---- text ----

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
            # Preserve whitespace including leading indent
            self._emit(_html_escape(data, quote=False))
        else:
            self._emit_text(data)

    # ---- final ----

    def result(self) -> str:
        # Collapse multiple blank lines down to two at most
        text = "".join(self.out).strip()
        while "\n\n\n" in text:
            text = text.replace("\n\n\n", "\n\n")
        return text


class _BlockSplitter(HTMLParser):
    """Walks markdown's HTML output, splitting into Blocks.

    Prose accumulates into a running _PangoBuilder; a <table> or
    <pre><code> boundary flushes it and emits a dedicated Block.
    """

    _TABLE_STRUCT = {"thead", "tbody", "tr", "th", "td"}

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
            if self._current_cell is None or self._current_row is None:
                return
            cell_markup = self._current_cell.result().strip()
            self._current_row.append(cell_markup)
            if self._in_thead:
                # Only header rows contribute to align inference
                self._table_aligns.append(self._current_cell_align)
            self._current_cell = None
        elif tag == "tr":
            if self._current_row is None:
                return
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


def _render_pango(text: str, dark: bool) -> str:
    """Internal: markdown → Pango markup string, used by MarkdownPreview widget."""
    if not _ensure_md():
        return _("python-markdown not installed")
    html = _md.Markdown(
        extensions=["fenced_code", "tables", "nl2br", "sane_lists"],
    ).convert(text)
    builder = _PangoBuilder(dark=dark)
    builder.feed(html)
    builder.close()
    return builder.result()


if GTK_AVAILABLE:

    class MarkdownPreview(Gtk.ScrolledWindow):
        """A pane that renders markdown into a Pango-formatted GtkLabel.

        Updates are debounced (~250 ms) so live typing stays responsive.
        Links use Pango's `<a href>` and the label's `activate-link` signal
        for navigation.
        """

        __gtype_name__ = "ApediMarkdownPreview"

        def __init__(self) -> None:
            super().__init__()
            self.set_hexpand(True)
            self.set_vexpand(True)
            self.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
            self._dark: bool = False
            self._pending_text: str = ""
            self._pending_base: Path | None = None
            self._timer_id: int | None = None
            self._last_rendered_text: str | None = None
            self.on_open_path: Callable[[Path], None] | None = None

            self._label = Gtk.Label()
            self._label.set_use_markup(True)
            self._label.set_selectable(True)
            self._label.set_wrap(True)
            self._label.set_wrap_mode(2)  # PANGO_WRAP_WORD_CHAR (= 2)
            self._label.set_xalign(0.0)
            self._label.set_yalign(0.0)
            self._label.set_valign(Gtk.Align.START)
            self._label.set_halign(Gtk.Align.FILL)
            self._label.set_margin_start(20)
            self._label.set_margin_end(20)
            self._label.set_margin_top(16)
            self._label.set_margin_bottom(16)
            self._label.connect("activate-link", self._on_activate_link)

            if not AVAILABLE:
                self._label.set_text(
                    _("Markdown preview unavailable (python-markdown missing)")
                )
            self.set_child(self._label)

        def set_dark(self, is_dark: bool) -> None:
            if self._dark == is_dark:
                return
            self._dark = is_dark
            if self._last_rendered_text is not None:
                self._render_now(self._last_rendered_text, self._pending_base)

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
            # First-render path: python-markdown hasn't been imported yet,
            # which costs ~50 ms. Show a placeholder, defer the actual
            # render to the next idle tick so the pane appears instantly.
            if MARKDOWN_AVAILABLE and _md is None:
                self._label.set_markup(f"<i>{_html_escape(_('Loading preview…'), quote=False)}</i>")
                GLib.idle_add(self._render_after_load, text, base_path)
                return
            markup = _render_pango(text, self._dark)
            self._label.set_markup(markup)
            self._last_rendered_text = text

        def _render_after_load(self, text: str, base_path: Path | None) -> bool:
            markup = _render_pango(text, self._dark)
            self._label.set_markup(markup)
            self._last_rendered_text = text
            return False

        def _on_activate_link(self, _label: Gtk.Label, uri: str) -> bool:
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
            # Relative or file:// — resolve against base_path and open in editor
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
else:

    class MarkdownPreview:  # type: ignore[no-redef]
        """Stub used when Gtk is unavailable (e.g. headless tests)."""

        def __init__(self, *_: object, **__: object) -> None:
            raise RuntimeError("MarkdownPreview requires GTK")
