"""Markdown preview — Pango-rendered pane.

Renders the current buffer's markdown into a `GtkLabel` via Pango markup.
No WebKit, no HTML — keeps the snap lean and the renderer fast.

Public surface (kept stable from the WebKit-era implementation):
- `is_markdown_path(path)` — extension check, no GTK needed.
- `MARKDOWN_AVAILABLE` — True iff python-markdown is importable.
- `AVAILABLE` — True iff both GTK is available and python-markdown is too.
- `render_pango(text, dark)` — pure function, headless-testable.
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
from html import escape as _html_escape
from html.parser import HTMLParser
from pathlib import Path
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

    def __init__(self, dark: bool) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.list_stack: list[tuple[str, int]] = []  # (kind, counter)
        self.in_pre = False
        # Mid-gray with low alpha so code blocks read well on both light
        # and dark themes — no need to swap colors per theme.
        self._code_bg = "#808080"
        self._code_bg_alpha = "10000"  # ~15% of 65535
        self._quote_fg = "#999999"
        # Table buffering
        self._table_rows: list[list[str]] | None = None
        self._table_row: list[str] | None = None
        self._table_cell: list[str] | None = None

    # ---- helpers ----

    def _emit(self, s: str) -> None:
        if self._table_cell is not None:
            self._table_cell.append(s)
        else:
            self.out.append(s)

    def _emit_text(self, s: str) -> None:
        self._emit(_html_escape(s, quote=False))

    # ---- start tags ----

    def handle_starttag(self, tag, attrs) -> None:
        attrs_d = dict(attrs)
        if tag in _HEADING_SPANS:
            self._emit(_HEADING_SPANS[tag])
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
                self._emit(f"\n{indent}• ")
        elif tag == "blockquote":
            self._emit(f'\n<i><span foreground="{self._quote_fg}">│ ')
        elif tag == "img":
            src = attrs_d.get("src", "") or ""
            name = src.rsplit("/", 1)[-1] or src or "image"
            self._emit(
                f'<a href="{_html_escape(src, quote=True)}">'
                f'[🖼 {_html_escape(name, quote=False)}]</a>'
            )
        elif tag == "table":
            self._table_rows = []
        elif tag == "tr":
            if self._table_rows is not None:
                self._table_row = []
        elif tag in ("th", "td"):
            if self._table_row is not None:
                self._table_cell = []
        # p, tbody, thead, etc. — handled by data flow

    # ---- end tags ----

    def handle_endtag(self, tag) -> None:
        if tag in _HEADING_SPANS:
            self._emit("</span>\n\n")
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
        elif tag in ("th", "td"):
            if self._table_row is not None and self._table_cell is not None:
                self._table_row.append("".join(self._table_cell).strip())
                self._table_cell = None
        elif tag == "tr":
            if self._table_rows is not None and self._table_row is not None:
                self._table_rows.append(self._table_row)
                self._table_row = None
        elif tag == "table":
            self._flush_table()

    def _flush_table(self) -> None:
        rows = self._table_rows or []
        self._table_rows = None
        if not rows:
            return
        widths: list[int] = []
        for row in rows:
            for i, cell in enumerate(row):
                if i >= len(widths):
                    widths.append(0)
                widths[i] = max(widths[i], len(cell))
        lines = []
        for row in rows:
            padded = "  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row))
            lines.append(padded.rstrip())
        block = "\n".join(lines)
        self.out.append(
            f'\n<span background="{self._code_bg}" background_alpha="{self._code_bg_alpha}" font_family="monospace">'
            f'{_html_escape(block, quote=False)}</span>\n\n'
        )

    # ---- text ----

    def handle_data(self, data) -> None:
        if not data:
            return
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


def render_pango(text: str, dark: bool) -> str:
    """Pure markdown→Pango markup. Headless-testable (no GTK needed)."""
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
            markup = render_pango(text, self._dark)
            self._label.set_markup(markup)
            self._last_rendered_text = text

        def _render_after_load(self, text: str, base_path: Path | None) -> bool:
            markup = render_pango(text, self._dark)
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
