"""Command Palette — fuzzy runner for every window/app action."""

from __future__ import annotations

import builtins
from typing import Callable

if not hasattr(builtins, "_"):
    builtins._ = lambda s: s  # type: ignore[attr-defined]

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GObject, Gio, Gtk  # noqa: E402


class _CommandEntry(GObject.Object):
    __gtype_name__ = "ApediCommandEntry"
    title = GObject.Property(type=str, default="")
    action = GObject.Property(type=str, default="")
    accel = GObject.Property(type=str, default="")


def _fuzzy_score(query: str, title: str) -> int | None:
    """Subsequence match on the command title; lower score sorts first.
    None means no match. Contiguous runs and word-start hits score better."""
    if not query:
        return 0
    q = query.lower()
    t = title.lower()
    qi = 0
    last = -2
    score = 0
    for i, ch in enumerate(t):
        if qi < len(q) and ch == q[qi]:
            score += 0 if i == last + 1 else 4
            last = i
            qi += 1
    if qi == len(q):
        return score - len(t) // 8
    return None


class CommandPalette(Gtk.Window):
    __gtype_name__ = "ApediCommandPalette"

    def __init__(
        self,
        parent: Gtk.Window,
        commands: list[tuple[str, str, str]],
        on_chosen: Callable[[str], None],
    ) -> None:
        super().__init__(
            title=_("Command Palette"),
            transient_for=parent, modal=True,
            default_width=520, default_height=420,
        )
        self.on_chosen = on_chosen
        self._all: list[_CommandEntry] = []
        for title, action, accel in commands:
            entry = _CommandEntry()
            entry.title = title
            entry.action = action
            entry.accel = accel
            self._all.append(entry)

        outer = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=8,
            margin_top=10, margin_bottom=10, margin_start=12, margin_end=12,
        )

        self.entry = Gtk.SearchEntry()
        self.entry.set_placeholder_text(_("Type a command…"))
        self.entry.connect("search-changed", self._on_search_changed)
        self.entry.connect("activate", lambda *_: self._activate_selected())
        outer.append(self.entry)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.add_css_class("frame")
        self.store = Gio.ListStore.new(_CommandEntry)
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
                      margin_start=8, margin_end=8, margin_top=3, margin_bottom=3)
        title_label = Gtk.Label(xalign=0)
        title_label.set_hexpand(True)
        title_label.set_ellipsize(3)
        box.append(title_label)
        accel_label = Gtk.Label(xalign=1)
        accel_label.add_css_class("dim-label")
        box.append(accel_label)
        item.set_child(box)

    def _bind_row(self, _factory, item: Gtk.ListItem) -> None:
        entry: _CommandEntry = item.get_item()
        box: Gtk.Box = item.get_child()
        title_label = box.get_first_child()
        accel_label = title_label.get_next_sibling()
        title_label.set_text(entry.title)
        accel_label.set_text(entry.accel)

    def _refresh(self, query: str) -> None:
        scored: list[tuple[int, int, _CommandEntry]] = []
        for order, e in enumerate(self._all):
            score = _fuzzy_score(query, e.title)
            if score is not None:
                scored.append((score, order, e))
        # Sort by score, then original order so an empty query keeps the
        # curated ordering instead of alphabetizing.
        scored.sort(key=lambda t: (t[0], t[1]))
        self.store.remove_all()
        for _, _, e in scored:
            self.store.append(e)
        if self.store.get_n_items() > 0:
            self.selection.set_selected(0)

    def _on_search_changed(self, entry: Gtk.SearchEntry) -> None:
        self._refresh(entry.get_text())

    def _on_row_activate(self, _view, position: int) -> None:
        item: _CommandEntry = self.store.get_item(position)
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
        item: _CommandEntry = self.store.get_item(idx)
        if item:
            self._invoke(item)

    def _invoke(self, entry: _CommandEntry) -> None:
        action = entry.action
        self.close()
        self.on_chosen(action)
