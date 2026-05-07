"""Quick Open — fuzzy file picker across all open project roots."""

from __future__ import annotations

import builtins
import os
from pathlib import Path
from typing import Callable, Iterable

if not hasattr(builtins, "_"):
    builtins._ = lambda s: s  # type: ignore[attr-defined]

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GObject, Gio, Gtk  # noqa: E402

from .ignore_filter import HEAVY_DIRS, IgnoreFilter

_MAX_FILES = 8000


class _FileEntry(GObject.Object):
    __gtype_name__ = "ApediQuickOpenEntry"
    name = GObject.Property(type=str, default="")
    path_str = GObject.Property(type=str, default="")
    rel_dir = GObject.Property(type=str, default="")


def _index(projects: list[Path], extra_patterns: list[str]) -> list[_FileEntry]:
    out: list[_FileEntry] = []
    for project in projects:
        if not project.is_dir():
            continue
        ignore = IgnoreFilter(project, extra_patterns)
        for root, dirs, files in os.walk(project, followlinks=False):
            dirs[:] = [
                d for d in dirs
                if d not in HEAVY_DIRS
                and not d.startswith(".")
                and not ignore.is_ignored(Path(root) / d)
            ]
            for fname in files:
                if fname.startswith("."):
                    continue
                full = Path(root) / fname
                if ignore.is_ignored(full):
                    continue
                entry = _FileEntry()
                entry.name = fname
                entry.path_str = str(full)
                try:
                    entry.rel_dir = str(full.parent.relative_to(project))
                    if entry.rel_dir == ".":
                        entry.rel_dir = project.name
                    else:
                        entry.rel_dir = f"{project.name}/{entry.rel_dir}"
                except ValueError:
                    entry.rel_dir = str(full.parent)
                out.append(entry)
                if len(out) >= _MAX_FILES:
                    return out
    return out


def _fuzzy_score(query: str, name: str, full: str) -> int | None:
    """Returns positive score when query subsequence matches; lower is better.
    None means no match. Boosts contiguous runs and basename hits."""
    if not query:
        return 0
    q = query.lower()
    n = name.lower()
    f = full.lower()
    qi = 0
    last = -2
    score = 0
    for i, ch in enumerate(n):
        if qi < len(q) and ch == q[qi]:
            score += 0 if i == last + 1 else 4
            last = i
            qi += 1
    if qi == len(q):
        return score - len(n) // 8  # reward shorter names mildly
    qi = 0
    last = -2
    score = 0
    for i, ch in enumerate(f):
        if qi < len(q) and ch == q[qi]:
            score += 0 if i == last + 1 else 4
            last = i
            qi += 1
    if qi == len(q):
        return 200 + score - len(f) // 16
    return None


class QuickOpenDialog(Gtk.Window):
    __gtype_name__ = "ApediQuickOpenDialog"

    def __init__(
        self,
        parent: Gtk.Window,
        projects: list[Path],
        extra_patterns: list[str],
        on_chosen: Callable[[Path], None],
    ) -> None:
        super().__init__(
            title=_("Quick Open"),
            transient_for=parent, modal=True,
            default_width=560, default_height=480,
        )
        self.on_chosen = on_chosen
        self._all = _index(projects, extra_patterns)

        outer = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=8,
            margin_top=10, margin_bottom=10, margin_start=12, margin_end=12,
        )

        self.entry = Gtk.SearchEntry()
        self.entry.set_placeholder_text(_("Type to search files…"))
        self.entry.connect("search-changed", self._on_search_changed)
        self.entry.connect("activate", lambda *_: self._activate_selected())
        outer.append(self.entry)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.add_css_class("frame")
        self.store = Gio.ListStore.new(_FileEntry)
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

        kc = Gtk.EventControllerKey.new()
        kc.connect("key-pressed", self._on_key_pressed)
        self.add_controller(kc)
        self.entry.grab_focus()

        self._refresh("")

    def _setup_row(self, _factory, item: Gtk.ListItem) -> None:
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10,
                      margin_start=8, margin_end=8, margin_top=2, margin_bottom=2)
        name_label = Gtk.Label(xalign=0)
        box.append(name_label)
        dir_label = Gtk.Label(xalign=0)
        dir_label.set_hexpand(True)
        dir_label.add_css_class("dim-label")
        dir_label.set_ellipsize(3)
        box.append(dir_label)
        item.set_child(box)

    def _bind_row(self, _factory, item: Gtk.ListItem) -> None:
        entry: _FileEntry = item.get_item()
        box: Gtk.Box = item.get_child()
        name_label = box.get_first_child()
        dir_label = name_label.get_next_sibling()
        name_label.set_text(entry.name)
        dir_label.set_text(entry.rel_dir)

    def _refresh(self, query: str) -> None:
        scored: list[tuple[int, _FileEntry]] = []
        for e in self._all:
            score = _fuzzy_score(query, e.name, e.path_str)
            if score is not None:
                scored.append((score, e))
        scored.sort(key=lambda t: (t[0], t[1].name.lower()))
        self.store.remove_all()
        for _, e in scored[:200]:
            self.store.append(e)
        if self.store.get_n_items() > 0:
            self.selection.set_selected(0)

    def _on_search_changed(self, entry: Gtk.SearchEntry) -> None:
        self._refresh(entry.get_text())

    def _on_row_activate(self, _view, position: int) -> None:
        item: _FileEntry = self.store.get_item(position)
        if item:
            self._invoke(item)

    def _on_key_pressed(self, _ctrl, keyval, _kc, _state) -> bool:
        from gi.repository import Gdk

        if keyval == Gdk.KEY_Escape:
            self.close()
            return True
        if keyval in (Gdk.KEY_Down, Gdk.KEY_Up):
            n = self.store.get_n_items()
            if n == 0:
                return True
            current = self.selection.get_selected()
            new = (current + (1 if keyval == Gdk.KEY_Down else -1)) % n
            self.selection.set_selected(new)
            self.list_view.scroll_to(new, Gtk.ListScrollFlags.FOCUS, None)
            return True
        return False

    def _activate_selected(self) -> None:
        idx = self.selection.get_selected()
        if idx == Gtk.INVALID_LIST_POSITION:
            return
        item: _FileEntry = self.store.get_item(idx)
        if item:
            self._invoke(item)

    def _invoke(self, entry: _FileEntry) -> None:
        path = Path(entry.path_str)
        self.close()
        self.on_chosen(path)
