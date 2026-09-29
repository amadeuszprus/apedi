"""Outline of the current markdown document, shown under the project tree."""

from __future__ import annotations

import builtins
import re
from dataclasses import dataclass
from typing import Callable

if not hasattr(builtins, "_"):
    builtins._ = lambda s: s  # type: ignore[attr-defined]

_ATX = re.compile(r"^ {0,3}(#{1,6})[ \t]+(.*?)(?:[ \t]+#+)?[ \t]*$")
_SETEXT = re.compile(r"^ {0,3}(=+|-+)[ \t]*$")
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_LINK = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
_EMPHASIS = re.compile(r"(\*{1,3}|(?<!\w)_{1,3}|_{1,3}(?!\w)|`+)")


@dataclass(frozen=True)
class Heading:
    level: int
    title: str
    line: int  # 1-based


def _clean(title: str) -> str:
    title = _LINK.sub(r"\1", title)
    return _EMPHASIS.sub("", title).strip()


def markdown_headings(text: str) -> list[Heading]:
    """ATX and setext headings, skipping fenced code and YAML front matter."""
    lines = text.split("\n")
    out: list[Heading] = []
    start = 0
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() in ("---", "..."):
                start = i + 1
                break
    fence: str | None = None
    prev_is_text = False
    for i in range(start, len(lines)):
        line = lines[i]
        m = _FENCE.match(line)
        if m:
            marker = m.group(1)
            if fence is None:
                fence = marker
            elif marker[0] == fence[0] and len(marker) >= len(fence):
                fence = None
            prev_is_text = False
            continue
        if fence is not None:
            continue
        m = _ATX.match(line)
        if m:
            title = _clean(m.group(2))
            if title:
                out.append(Heading(len(m.group(1)), title, i + 1))
            prev_is_text = False
            continue
        m = _SETEXT.match(line)
        if m and prev_is_text:
            level = 1 if m.group(1)[0] == "=" else 2
            out.append(Heading(level, _clean(lines[i - 1].strip()), i))
            prev_is_text = False
            continue
        prev_is_text = bool(line.strip())
    return out


def current_heading(headings: list[Heading], line: int) -> int | None:
    """Index of the heading whose section contains `line`, or None above the first one."""
    found = None
    for idx, heading in enumerate(headings):
        if heading.line > line:
            break
        found = idx
    return found


try:
    import gi

    gi.require_version("Gtk", "4.0")
    from gi.repository import GObject, Gio, Gtk  # noqa: E402
except (ImportError, ValueError):  # pragma: no cover - headless tests
    Gtk = None  # type: ignore[assignment]


if Gtk is not None:

    class _Item(GObject.Object):
        __gtype_name__ = "ApediOutlineItem"
        title = GObject.Property(type=str, default="")
        level = GObject.Property(type=int, default=1)
        line = GObject.Property(type=int, default=1)

    class OutlinePanel(Gtk.Box):
        """Clickable list of headings; `on_activate(line)` jumps the editor there."""

        __gtype_name__ = "ApediOutlinePanel"

        def __init__(self, on_activate: Callable[[int], None]) -> None:
            super().__init__(orientation=Gtk.Orientation.VERTICAL)
            self.on_activate = on_activate
            self._headings: list[Heading] = []
            self._syncing = False
            header = Gtk.Label(label=_("Outline"), xalign=0)
            header.add_css_class("heading")
            header.set_margin_start(10)
            header.set_margin_top(6)
            header.set_margin_bottom(4)
            self.append(header)

            self.store = Gio.ListStore.new(_Item)
            self.selection = Gtk.SingleSelection.new(self.store)
            self.selection.set_autoselect(False)
            self.selection.set_can_unselect(True)
            self.list_view = Gtk.ListView()
            self.list_view.set_model(self.selection)
            self.list_view.set_single_click_activate(True)
            self.list_view.add_css_class("navigation-sidebar")
            self.list_view.connect("activate", self._on_activate)
            factory = Gtk.SignalListItemFactory()
            factory.connect("setup", self._setup)
            factory.connect("bind", self._bind)
            self.list_view.set_factory(factory)
            scrolled = Gtk.ScrolledWindow()
            scrolled.set_vexpand(True)
            scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            scrolled.set_child(self.list_view)
            self.append(scrolled)

        def set_headings(self, headings: list[Heading]) -> None:
            if headings == self._headings:
                return
            self._headings = list(headings)
            items = []
            for h in headings:
                item = _Item()
                item.title = h.title
                item.level = h.level
                item.line = h.line
                items.append(item)
            self.store.splice(0, self.store.get_n_items(), items)

        def has_headings(self) -> bool:
            return bool(self._headings)

        def highlight_line(self, line: int) -> None:
            """Mark the heading the cursor is under without stealing focus."""
            idx = current_heading(self._headings, line)
            self._syncing = True
            try:
                if idx is None:
                    self.selection.unselect_all()
                else:
                    self.selection.set_selected(idx)
            finally:
                self._syncing = False

        def _setup(self, _factory, item: Gtk.ListItem) -> None:
            label = Gtk.Label(xalign=0)
            label.set_ellipsize(3)
            item.set_child(label)

        def _bind(self, _factory, item: Gtk.ListItem) -> None:
            data: _Item = item.get_item()
            label: Gtk.Label = item.get_child()
            label.set_text(data.title)
            label.set_margin_start(4 + 12 * (data.level - 1))
            if data.level == 1:
                label.add_css_class("heading")
            else:
                label.remove_css_class("heading")

        def _on_activate(self, _view, position: int) -> None:
            data = self.store.get_item(position)
            if data is not None:
                self.on_activate(data.line)
