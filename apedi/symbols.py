"""Go-to-symbol palette — list classes/functions in the current buffer."""

from __future__ import annotations

import ast
import logging
import re
from dataclasses import dataclass
from typing import Callable

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GObject, Gio, Gtk  # noqa: E402

log = logging.getLogger(__name__)


@dataclass
class Symbol:
    name: str
    kind: str  # "class" | "function" | "method"
    line: int  # 1-based


def extract_symbols(language_id: str | None, text: str) -> list[Symbol]:
    if language_id in ("python", "python3"):
        return _python_symbols(text)
    pattern = _LANG_REGEX.get(language_id or "")
    if pattern is None:
        return []
    return _regex_symbols(text, pattern)


def _python_symbols(text: str) -> list[Symbol]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        # Fall back to regex on malformed source
        return _regex_symbols(text, _LANG_REGEX["python"])
    out: list[Symbol] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            out.append(Symbol(node.name, "class", node.lineno))
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    out.append(Symbol(f"{node.name}.{item.name}", "method", item.lineno))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # Skip methods (already handled inside ClassDef walk)
            if isinstance(getattr(node, "_apedi_parent", None), ast.ClassDef):
                continue
            out.append(Symbol(node.name, "function", node.lineno))
    out.sort(key=lambda s: s.line)
    return out


_LANG_REGEX: dict[str, re.Pattern[str]] = {
    "python": re.compile(r"^\s*(?:async\s+)?(class|def)\s+(\w+)", re.MULTILINE),
    "javascript": re.compile(
        r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?(class|function)\s+(\w+)", re.MULTILINE
    ),
    "js": re.compile(
        r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?(class|function)\s+(\w+)", re.MULTILINE
    ),
    "typescript": re.compile(
        r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?(class|function|interface|type)\s+(\w+)",
        re.MULTILINE,
    ),
    "rust": re.compile(
        r"^\s*(?:pub\s+(?:\(\w+\)\s+)?)?(fn|struct|enum|trait|impl|mod)\s+(\w+)", re.MULTILINE
    ),
    "go": re.compile(
        r"^\s*func\s+(?:\(\s*\w+\s+\*?\w+\s*\)\s+)?(\w+)|^\s*type\s+(\w+)\s+(struct|interface)",
        re.MULTILINE,
    ),
    "c": re.compile(r"^\s*[A-Za-z_][\w\s\*]*\b(\w+)\s*\([^;]*\)\s*\{", re.MULTILINE),
    "cpp": re.compile(
        r"^\s*(?:template\s*<[^>]+>\s*)?(class|struct|namespace)\s+(\w+)", re.MULTILINE
    ),
    "java": re.compile(
        r"^\s*(?:public|protected|private)?\s*(?:static\s+)?(?:final\s+)?(class|interface|enum)\s+(\w+)",
        re.MULTILINE,
    ),
    "ruby": re.compile(r"^\s*(class|def|module)\s+([A-Za-z_][\w?!]*)", re.MULTILINE),
    "sh": re.compile(r"^\s*(?:function\s+)?(\w+)\s*\(\)\s*\{", re.MULTILINE),
    "bash": re.compile(r"^\s*(?:function\s+)?(\w+)\s*\(\)\s*\{", re.MULTILINE),
}


def _regex_symbols(text: str, pattern: re.Pattern[str]) -> list[Symbol]:
    out: list[Symbol] = []
    for m in pattern.finditer(text):
        groups = [g for g in m.groups() if g]
        if not groups:
            continue
        if len(groups) == 1:
            kind = "function"
            name = groups[0]
        else:
            kind = groups[0]
            name = groups[-1]
        line = text.count("\n", 0, m.start()) + 1
        out.append(Symbol(name, kind, line))
    return out


class _SymbolItem(GObject.Object):
    __gtype_name__ = "ApediSymbolItem"
    name = GObject.Property(type=str, default="")
    kind = GObject.Property(type=str, default="")
    line = GObject.Property(type=int, default=0)


class SymbolPaletteDialog(Gtk.Window):
    __gtype_name__ = "ApediSymbolPalette"

    def __init__(
        self,
        parent: Gtk.Window,
        symbols: list[Symbol],
        on_chosen: Callable[[Symbol], None],
    ) -> None:
        super().__init__(
            title="Go to Symbol",
            transient_for=parent,
            modal=True,
            default_width=480,
            default_height=420,
        )
        self.on_chosen = on_chosen
        self._all_symbols = symbols

        outer = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=8,
            margin_top=10, margin_bottom=10, margin_start=12, margin_end=12,
        )

        self.entry = Gtk.SearchEntry()
        self.entry.set_placeholder_text("Filter symbols…")
        self.entry.connect("search-changed", self._on_search_changed)
        self.entry.connect("activate", self._on_entry_activate)
        outer.append(self.entry)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.add_css_class("frame")

        self.store = Gio.ListStore.new(_SymbolItem)
        self.selection = Gtk.SingleSelection.new(self.store)
        self.list_view = Gtk.ListView()
        self.list_view.set_single_click_activate(True)
        self.list_view.set_model(self.selection)
        self.list_view.connect("activate", self._on_row_activate)

        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", self._setup_row)
        factory.connect("bind", self._bind_row)
        self.list_view.set_factory(factory)
        scrolled.set_child(self.list_view)
        outer.append(scrolled)

        self.set_child(outer)
        self._refresh("")

        key_ctrl = Gtk.EventControllerKey.new()
        key_ctrl.connect("key-pressed", self._on_key_pressed)
        self.add_controller(key_ctrl)
        self.entry.grab_focus()

    def _setup_row(self, _factory, item: Gtk.ListItem) -> None:
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6,
                      margin_start=6, margin_end=6, margin_top=2, margin_bottom=2)
        kind_label = Gtk.Label(xalign=0)
        kind_label.set_size_request(72, -1)
        kind_label.add_css_class("dim-label")
        box.append(kind_label)
        name_label = Gtk.Label(xalign=0)
        name_label.set_hexpand(True)
        box.append(name_label)
        line_label = Gtk.Label(xalign=1)
        line_label.add_css_class("dim-label")
        box.append(line_label)
        item.set_child(box)

    def _bind_row(self, _factory, item: Gtk.ListItem) -> None:
        sym: _SymbolItem = item.get_item()
        box: Gtk.Box = item.get_child()
        kind_label = box.get_first_child()
        name_label = kind_label.get_next_sibling()
        line_label = name_label.get_next_sibling()
        kind_label.set_text(sym.kind)
        name_label.set_text(sym.name)
        line_label.set_text(f"{sym.line}")

    def _refresh(self, query: str) -> None:
        q = query.lower()
        self.store.remove_all()
        for sym in self._all_symbols:
            if not q or q in sym.name.lower():
                item = _SymbolItem()
                item.name = sym.name
                item.kind = sym.kind
                item.line = sym.line
                self.store.append(item)
        if self.store.get_n_items() > 0:
            self.selection.set_selected(0)

    def _on_search_changed(self, entry: Gtk.SearchEntry) -> None:
        self._refresh(entry.get_text())

    def _on_entry_activate(self, _entry: Gtk.SearchEntry) -> None:
        self._activate_selected()

    def _on_row_activate(self, _view: Gtk.ListView, position: int) -> None:
        item: _SymbolItem = self.store.get_item(position)
        if item is None:
            return
        self._invoke(item)

    def _on_key_pressed(self, _ctrl, keyval, _kc, _state) -> bool:
        from gi.repository import Gdk

        if keyval == Gdk.KEY_Escape:
            self.close()
            return True
        if keyval == Gdk.KEY_Return:
            self._activate_selected()
            return True
        if keyval in (Gdk.KEY_Down, Gdk.KEY_Up):
            n = self.store.get_n_items()
            if n == 0:
                return True
            current = self.selection.get_selected()
            delta = 1 if keyval == Gdk.KEY_Down else -1
            new = max(0, min(n - 1, current + delta))
            self.selection.set_selected(new)
            self.list_view.scroll_to(new, Gtk.ListScrollFlags.FOCUS, None)
            return True
        return False

    def _activate_selected(self) -> None:
        idx = self.selection.get_selected()
        if idx == Gtk.INVALID_LIST_POSITION:
            return
        item: _SymbolItem = self.store.get_item(idx)
        if item is None:
            return
        self._invoke(item)

    def _invoke(self, item: _SymbolItem) -> None:
        sym = Symbol(item.name, item.kind, item.line)
        self.close()
        self.on_chosen(sym)
