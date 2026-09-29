"""Go to Symbol across every open project, indexed in the background and cached by mtime."""

from __future__ import annotations

import builtins
import logging
import os
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

if not hasattr(builtins, "_"):
    builtins._ = lambda s: s  # type: ignore[attr-defined]

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, GLib, GObject, Gio, Gtk  # noqa: E402

from .ignore_filter import HEAVY_DIRS, IgnoreFilter
from .symbols import extract_symbols

log = logging.getLogger(__name__)

_MAX_FILES = 20000
_MAX_FILE_BYTES = 1024 * 1024
_MAX_SHOWN = 300

# File extension to the GtkSourceView language id the symbol extractor understands.
EXT_LANG = {
    ".py": "python3", ".pyi": "python3",
    ".js": "js", ".mjs": "js", ".cjs": "js", ".jsx": "js",
    ".ts": "typescript", ".tsx": "typescript", ".mts": "typescript",
    ".php": "php",
    ".rs": "rust", ".go": "go",
    ".c": "c", ".h": "c",
    ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp", ".hpp": "cpp", ".hh": "cpp",
    ".java": "java", ".rb": "ruby",
    ".sh": "sh", ".bash": "sh",
}


@dataclass(frozen=True)
class ProjectSymbol:
    name: str
    kind: str
    path: Path
    line: int


# path -> (mtime_ns, size, symbols); shared by every window, written only by the indexer thread.
_CACHE: dict[str, tuple[int, int, list[tuple[str, str, int]]]] = {}
_CACHE_LOCK = threading.Lock()


def _source_files(projects: list[Path], extra_patterns: list[str]):
    seen = 0
    for project in projects:
        if not project.is_dir():
            continue
        ignore = IgnoreFilter(project, extra_patterns)
        for root, dirs, files in os.walk(project, followlinks=False):
            dirs[:] = [
                d for d in dirs
                if d not in HEAVY_DIRS
                and not d.startswith(".")
                and not ignore.is_ignored(Path(root) / d, is_dir=True)
            ]
            for fname in files:
                lang = EXT_LANG.get(os.path.splitext(fname)[1].lower())
                if lang is None:
                    continue
                full = Path(root) / fname
                if ignore.is_ignored(full, is_dir=False):
                    continue
                yield full, lang
                seen += 1
                if seen >= _MAX_FILES:
                    return


def index_projects(
    projects: list[Path],
    extra_patterns: list[str],
    *,
    cache: dict | None = None,
    cancelled: Callable[[], bool] = lambda: False,
) -> list[ProjectSymbol]:
    """Symbols of every supported source file, re-parsing only files whose mtime or size changed."""
    store = _CACHE if cache is None else cache
    out: list[ProjectSymbol] = []
    for full, lang in _source_files(projects, extra_patterns):
        if cancelled():
            return []
        try:
            st = full.stat()
        except OSError:
            continue
        if st.st_size > _MAX_FILE_BYTES:
            continue
        key = str(full)
        with _CACHE_LOCK:
            hit = store.get(key)
        if hit is not None and hit[0] == st.st_mtime_ns and hit[1] == st.st_size:
            entries = hit[2]
        else:
            try:
                text = full.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            try:
                entries = [(s.name, s.kind, s.line) for s in extract_symbols(lang, text)]
            except Exception:  # noqa: BLE001
                log.debug("symbol extraction failed for %s", full, exc_info=True)
                entries = []
            with _CACHE_LOCK:
                store[key] = (st.st_mtime_ns, st.st_size, entries)
        out.extend(ProjectSymbol(name, kind, full, line) for name, kind, line in entries)
    return out


def filter_symbols(symbols: list[ProjectSymbol], query: str) -> list[ProjectSymbol]:
    """Fuzzy-match on the symbol name; tightest match first, the original order for an empty query."""
    if not query:
        return list(symbols)
    # Each [^c]*c step cannot backtrack, so the C regex engine stays linear per start position.
    pattern = re.compile(
        re.escape(query[0]) + "".join(f"[^{re.escape(c)}]*{re.escape(c)}" for c in query[1:]),
        re.IGNORECASE,
    )
    scored = []
    for sym in symbols:
        m = pattern.search(sym.name)
        if m is not None:
            scored.append((m.end() - m.start(), m.start(), len(sym.name), sym.name.lower(), sym))
    scored.sort(key=lambda t: t[:4])
    return [t[4] for t in scored]


class _Row(GObject.Object):
    __gtype_name__ = "ApediProjectSymbolRow"
    name = GObject.Property(type=str, default="")
    kind = GObject.Property(type=str, default="")
    where = GObject.Property(type=str, default="")
    path_str = GObject.Property(type=str, default="")
    line = GObject.Property(type=int, default=0)


class ProjectSymbolsDialog(Gtk.Window):
    __gtype_name__ = "ApediProjectSymbolsDialog"

    def __init__(
        self,
        parent: Gtk.Window,
        projects: list[Path],
        extra_patterns: list[str],
        on_chosen: Callable[[Path, int], None],
    ) -> None:
        super().__init__(
            title=_("Go to Symbol in Project"),
            transient_for=parent, modal=True,
            default_width=680, default_height=500,
        )
        self.on_chosen = on_chosen
        self._projects = projects
        self._symbols: list[ProjectSymbol] = []
        self._cancel = threading.Event()

        outer = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=8,
            margin_top=10, margin_bottom=10, margin_start=12, margin_end=12,
        )
        self.entry = Gtk.SearchEntry()
        self.entry.set_placeholder_text(_("Type a class or function name…"))
        self.entry.connect("search-changed", lambda *_: self._refresh())
        self.entry.connect("activate", lambda *_: self._activate_selected())
        outer.append(self.entry)

        self.summary = Gtk.Label(xalign=0)
        self.summary.add_css_class("dim-label")
        self.summary.set_text(_("Indexing…"))
        outer.append(self.summary)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.add_css_class("frame")
        self.store = Gio.ListStore.new(_Row)
        self.selection = Gtk.SingleSelection.new(self.store)
        self.list_view = Gtk.ListView()
        self.list_view.set_single_click_activate(True)
        self.list_view.set_model(self.selection)
        self.list_view.connect("activate", lambda _v, pos: self._invoke(self.store.get_item(pos)))
        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", self._setup_row)
        factory.connect("bind", self._bind_row)
        self.list_view.set_factory(factory)
        scrolled.set_child(self.list_view)
        outer.append(scrolled)
        self.set_child(outer)

        keys = Gtk.EventControllerKey.new()
        keys.connect("key-pressed", self._on_key_pressed)
        self.add_controller(keys)
        self.connect("close-request", lambda *_: self._cancel.set() or False)
        self.entry.grab_focus()

        worker = threading.Thread(
            target=self._index, args=(list(projects), list(extra_patterns)), daemon=True,
        )
        worker.start()

    def _index(self, projects: list[Path], patterns: list[str]) -> None:
        try:
            symbols = index_projects(projects, patterns, cancelled=self._cancel.is_set)
        except Exception:  # noqa: BLE001
            log.exception("project symbol indexing failed")
            symbols = []
        if not self._cancel.is_set():
            GLib.idle_add(self._indexed, symbols)

    def _indexed(self, symbols: list[ProjectSymbol]) -> bool:
        self._symbols = symbols
        self._refresh()
        return False

    def _relative(self, path: Path) -> str:
        for project in self._projects:
            try:
                return f"{project.name}/{path.relative_to(project)}"
            except ValueError:
                continue
        return str(path)

    def _refresh(self) -> None:
        if self._cancel.is_set():
            return
        self._shown_query = self.entry.get_text()
        matches = filter_symbols(self._symbols, self._shown_query)
        self.store.remove_all()
        for sym in matches[:_MAX_SHOWN]:
            row = _Row()
            row.name = sym.name
            row.kind = sym.kind
            row.where = f"{self._relative(sym.path)}:{sym.line}"
            row.path_str = str(sym.path)
            row.line = sym.line
            self.store.append(row)
        if self.store.get_n_items() > 0:
            self.selection.set_selected(0)
        self.summary.set_text(
            _("{shown} of {total} symbols").format(shown=len(matches), total=len(self._symbols))
        )

    def _setup_row(self, _factory, item: Gtk.ListItem) -> None:
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10,
                      margin_start=6, margin_end=6, margin_top=2, margin_bottom=2)
        kind = Gtk.Label(xalign=0)
        kind.set_size_request(72, -1)
        kind.add_css_class("dim-label")
        box.append(kind)
        name = Gtk.Label(xalign=0)
        box.append(name)
        where = Gtk.Label(xalign=1)
        where.set_hexpand(True)
        where.set_ellipsize(1)  # PANGO_ELLIPSIZE_START keeps the file name visible
        where.add_css_class("dim-label")
        box.append(where)
        item.set_child(box)

    def _bind_row(self, _factory, item: Gtk.ListItem) -> None:
        row: _Row = item.get_item()
        kind = item.get_child().get_first_child()
        name = kind.get_next_sibling()
        where = name.get_next_sibling()
        kind.set_text(row.kind)
        name.set_text(row.name)
        where.set_text(row.where)

    def _on_key_pressed(self, _ctrl, keyval, _kc, _state) -> bool:
        if keyval == Gdk.KEY_Escape:
            self.close()
            return True
        if keyval in (Gdk.KEY_Down, Gdk.KEY_Up):
            n = self.store.get_n_items()
            if n == 0:
                return True
            current = self.selection.get_selected()
            new = max(0, min(n - 1, current + (1 if keyval == Gdk.KEY_Down else -1)))
            self.selection.set_selected(new)
            self.list_view.scroll_to(new, Gtk.ListScrollFlags.FOCUS, None)
            return True
        return False

    def _activate_selected(self) -> None:
        # Enter can beat the entry's search delay; filter first so the visible pick is the right one.
        if self.entry.get_text() != getattr(self, "_shown_query", None):
            self._refresh()
        idx = self.selection.get_selected()
        if idx != Gtk.INVALID_LIST_POSITION:
            self._invoke(self.store.get_item(idx))

    def _invoke(self, row: _Row | None) -> None:
        if row is None:
            return
        path, line = Path(row.path_str), row.line
        self.close()
        self.on_chosen(path, line)
