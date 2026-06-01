"""Project sidebar — directory tree view."""

from __future__ import annotations

import builtins
import logging
from pathlib import Path
from typing import Callable

if not hasattr(builtins, "_"):
    builtins._ = lambda s: s  # type: ignore[attr-defined]

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, GObject, Gio, Gtk  # noqa: E402

from .ignore_filter import IgnoreFilter

log = logging.getLogger(__name__)


class FileNode(GObject.Object):
    __gtype_name__ = "ApediFileNode"

    name = GObject.Property(type=str, default="")
    path_str = GObject.Property(type=str, default="")
    is_dir = GObject.Property(type=bool, default=False)
    is_ignored = GObject.Property(type=bool, default=False)
    is_heavy = GObject.Property(type=bool, default=False)
    is_project = GObject.Property(type=bool, default=False)


def _safe_is_dir(path: Path) -> bool:
    try:
        return path.is_dir()
    except OSError:
        return False


def _list_dir(path: Path, ignore: IgnoreFilter | None) -> Gio.ListStore:
    store = Gio.ListStore.new(FileNode)
    try:
        entries = sorted(
            path.iterdir(),
            key=lambda p: (not _safe_is_dir(p), p.name.lower()),
        )
    except OSError as e:
        log.debug("cannot list %s: %s", path, e)
        return store
    for entry in entries:
        if entry.name in (".git",):
            # always hide .git itself even when not in gitignore
            continue
        node = FileNode()
        node.name = entry.name
        node.path_str = str(entry)
        node.is_dir = _safe_is_dir(entry)
        node.is_heavy = ignore.is_heavy(entry) if ignore else False
        node.is_ignored = ignore.is_ignored(entry) if ignore else False
        store.append(node)
    return store


def _make_expand_func(ignore: IgnoreFilter | None):
    def _expand_node(item: GObject.Object) -> Gio.ListStore | None:
        if not isinstance(item, FileNode) or not item.is_dir:
            return None
        return _list_dir(Path(item.path_str), ignore)

    return _expand_node


def _file_icon_for(name: str) -> Gio.Icon:
    """Pick a themed symbolic icon based on freedesktop content-type guess."""
    content_type, _ = Gio.content_type_guess(name, None)
    if content_type:
        symbolic = Gio.content_type_get_symbolic_icon(content_type)
        if symbolic:
            return symbolic
    return Gio.ThemedIcon.new("text-x-generic-symbolic")


class ProjectSidebar(Gtk.Box):
    __gtype_name__ = "ApediProjectSidebar"

    def __init__(self, on_file_activate: Callable[[Path], None]) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.set_size_request(240, -1)
        self.on_file_activate = on_file_activate
        self._projects: list[Path] = []
        self._ignore_filters: dict[str, IgnoreFilter] = {}
        self._extra_ignore_patterns: list[str] = []
        self.on_close_project: Callable[[Path], None] | None = None
        self.on_context_action: Callable[[str, Path], None] | None = None
        self._context_path: Path | None = None
        self.root_path: Path | None = None  # kept for callers iterating active project

        header = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL, spacing=4,
            margin_start=10, margin_end=6, margin_top=6, margin_bottom=6,
        )
        self.title_label = Gtk.Label(label=_("Projects"), xalign=0, ellipsize=3)
        self.title_label.set_hexpand(True)
        self.title_label.add_css_class("heading")
        header.append(self.title_label)
        open_btn = Gtk.Button.new_from_icon_name("list-add-symbolic")
        open_btn.set_tooltip_text(_("Add Project (Ctrl+Shift+O)"))
        open_btn.set_action_name("win.open-project")
        open_btn.add_css_class("flat")
        header.append(open_btn)
        self.append(header)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_hexpand(True)

        self.list_view = Gtk.ListView()
        self.list_view.set_show_separators(False)
        self.list_view.set_single_click_activate(True)
        self.list_view.add_css_class("navigation-sidebar")
        self.list_view.connect("activate", self._on_row_activated)
        scrolled.set_child(self.list_view)
        self.append(scrolled)

        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", self._setup_item)
        factory.connect("bind", self._bind_item)
        self.list_view.set_factory(factory)

        self._roots_store = Gio.ListStore.new(FileNode)
        self._tree_model = Gtk.TreeListModel.new(
            self._roots_store, False, False, self._expand_for_node
        )
        self.list_view.set_model(Gtk.SingleSelection.new(self._tree_model))

    def set_projects(self, paths: list[Path], extra_patterns: list[str] | None = None) -> None:
        if extra_patterns is not None:
            self._extra_ignore_patterns = list(extra_patterns)
        self._roots_store.remove_all()
        self._projects.clear()
        self._ignore_filters.clear()
        for p in paths:
            self.add_project(p)

    def add_project(self, path: Path) -> bool:
        path = path.resolve() if path.exists() else path
        for existing in self._projects:
            if existing == path:
                return False
        self._projects.append(path)
        self._ignore_filters[str(path)] = IgnoreFilter(path, self._extra_ignore_patterns)
        node = FileNode()
        node.name = path.name or str(path)
        node.path_str = str(path)
        node.is_dir = True
        node.is_project = True
        self._roots_store.append(node)
        self.root_path = path
        return True

    def remove_project(self, path: Path) -> None:
        for i in range(self._roots_store.get_n_items()):
            n = self._roots_store.get_item(i)
            if Path(n.path_str) == path:
                self._roots_store.remove(i)
                break
        self._projects = [p for p in self._projects if p != path]
        self._ignore_filters.pop(str(path), None)
        if self.root_path == path:
            self.root_path = self._projects[-1] if self._projects else None

    def projects(self) -> list[Path]:
        return list(self._projects)

    def project_for(self, file_path: Path) -> Path | None:
        try:
            resolved = file_path.resolve()
        except OSError:
            return None
        for proj in self._projects:
            try:
                resolved.relative_to(proj.resolve())
                return proj
            except ValueError:
                continue
        return None

    def _expand_for_node(self, item: GObject.Object) -> Gio.ListStore | None:
        if not isinstance(item, FileNode) or not item.is_dir:
            return None
        path = Path(item.path_str)
        proj = self.project_for(path)
        ignore = self._ignore_filters.get(str(proj)) if proj else None
        return _list_dir(path, ignore)

    def set_compact(self, compact: bool) -> None:
        if compact:
            self.add_css_class("sidebar-compact")
        else:
            self.remove_css_class("sidebar-compact")

    def update_extra_patterns(self, patterns: list[str]) -> None:
        self._extra_ignore_patterns = list(patterns)
        for proj in self._projects:
            self._ignore_filters[str(proj)] = IgnoreFilter(proj, patterns)

    def _setup_item(self, _factory: Gtk.SignalListItemFactory, item: Gtk.ListItem) -> None:
        expander = Gtk.TreeExpander()
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        icon = Gtk.Image()
        label = Gtk.Label(xalign=0, ellipsize=3)
        label.set_hexpand(True)
        close_btn = Gtk.Button.new_from_icon_name("window-close-symbolic")
        close_btn.add_css_class("flat")
        close_btn.set_tooltip_text(_("Close project"))
        close_btn.set_visible(False)
        box.append(icon)
        box.append(label)
        box.append(close_btn)
        expander.set_child(box)
        item.set_child(expander)

        right_click = Gtk.GestureClick.new()
        right_click.set_button(3)
        right_click.connect(
            "pressed",
            lambda g, n_press, x, y: self._on_right_click(box, x, y),
        )
        box.add_controller(right_click)

        long_press = Gtk.GestureLongPress.new()
        long_press.set_touch_only(True)
        long_press.connect(
            "pressed",
            lambda g, x, y: self._on_right_click(box, x, y),
        )
        box.add_controller(long_press)

    def _bind_item(self, _factory: Gtk.SignalListItemFactory, item: Gtk.ListItem) -> None:
        from . import style

        expander: Gtk.TreeExpander = item.get_child()
        row: Gtk.TreeListRow = item.get_item()
        expander.set_list_row(row)
        node: FileNode = row.get_item()
        box: Gtk.Box = expander.get_child()
        icon: Gtk.Image = box.get_first_child()
        label: Gtk.Label = icon.get_next_sibling()
        close_btn: Gtk.Button = label.get_next_sibling()

        box._apedi_node = node

        prev_handler = getattr(close_btn, "_apedi_handler", 0)
        if prev_handler:
            close_btn.disconnect(prev_handler)
            close_btn._apedi_handler = 0

        classes: list[str] = []
        if node.is_project:
            icon.set_from_icon_name("folder-symbolic")
            classes.append("project-root")
            close_btn.set_visible(True)
            close_path = Path(node.path_str)
            close_btn._apedi_handler = close_btn.connect(
                "clicked", lambda *_, p=close_path: self._handle_close_project(p)
            )
        elif node.is_dir:
            icon.set_from_icon_name("folder-symbolic")
            close_btn.set_visible(False)
        else:
            icon.set_from_gicon(_file_icon_for(node.name))
            classes.append(style.class_for_filename(node.name))
            close_btn.set_visible(False)
        if node.is_ignored:
            classes.append("file-ignored")
        if node.is_heavy:
            classes.append("file-heavy")
        label.set_css_classes(classes)
        label.set_text(node.name)

    def _handle_close_project(self, path: Path) -> None:
        if self.on_close_project is not None:
            self.on_close_project(path)
        else:
            self.remove_project(path)

    def _on_right_click(self, box: Gtk.Box, x: float, y: float) -> None:
        node: FileNode | None = getattr(box, "_apedi_node", None)
        if node is None:
            return
        path = Path(node.path_str)
        self._context_path = path
        self._show_context_popover(box, x, y, node)

    def _show_context_popover(
        self, anchor: Gtk.Widget, x: float, y: float, node: FileNode,
    ) -> None:
        is_dir = node.is_dir
        scope_label = _("Folder") if is_dir else _("File")
        path = Path(node.path_str)

        popover = Gtk.Popover()
        popover.set_has_arrow(True)
        popover.set_autohide(True)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2,
                        margin_top=4, margin_bottom=4, margin_start=4, margin_end=4)

        def add_button(label: str, action_id: str) -> None:
            btn = Gtk.Button(label=label)
            btn.set_halign(Gtk.Align.FILL)
            inner = btn.get_first_child()
            if isinstance(inner, Gtk.Label):
                inner.set_xalign(0)
            btn.add_css_class("flat")
            btn.set_has_frame(False)
            btn.connect("clicked", lambda *_: self._dispatch_action(popover, action_id, path))
            outer.append(btn)

        def add_separator() -> None:
            outer.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        add_button(_("New File…"), "new-file")
        add_button(_("New Folder…"), "new-folder")
        add_separator()
        add_button(_("Find in {scope}…").format(scope=scope_label), "find")
        add_button(_("Replace in {scope}…").format(scope=scope_label), "replace")
        add_button(_("Replace with…"), "replace-with")

        popover.set_child(outer)
        popover.set_parent(anchor)
        rect = Gdk.Rectangle()
        rect.x = int(x)
        rect.y = int(y)
        rect.width = 1
        rect.height = 1
        popover.set_pointing_to(rect)
        popover.connect("closed", lambda p: p.unparent())
        popover.popup()

    def _dispatch_action(self, popover: Gtk.Popover, action_id: str, path: Path) -> None:
        popover.popdown()
        self._context_path = path
        if self.on_context_action is not None:
            self.on_context_action(action_id, path)

    def get_context_path(self) -> Path | None:
        """Path the user last interacted with: right-clicked > selected > root."""
        if self._context_path is not None:
            return self._context_path
        if self._tree_model is not None:
            sel = self.list_view.get_model()
            if isinstance(sel, Gtk.SingleSelection):
                pos = sel.get_selected()
                if pos != Gtk.INVALID_LIST_POSITION:
                    row = self._tree_model.get_row(pos)
                    if row is not None:
                        node: FileNode = row.get_item()
                        return Path(node.path_str)
        if self._projects:
            return self._projects[-1]
        return None

    def clear_context_path(self) -> None:
        self._context_path = None

    def _on_row_activated(self, _view: Gtk.ListView, position: int) -> None:
        if self._tree_model is None:
            return
        row = self._tree_model.get_row(position)
        if row is None:
            return
        node: FileNode = row.get_item()
        if node.is_dir:
            row.set_expanded(not row.get_expanded())
        else:
            self.on_file_activate(Path(node.path_str))

    def reveal_file(self, file_path: Path) -> None:
        """Expand parent folders and select+scroll to file_path in the tree."""
        from gi.repository import GLib

        proj = self.project_for(file_path)
        if proj is None or self._tree_model is None:
            return
        GLib.idle_add(self._reveal_into_project, proj, file_path.resolve())

    def _reveal_into_project(self, proj: Path, file_path: Path) -> bool:
        from gi.repository import GLib

        model = self._tree_model
        if model is None:
            return False
        for i in range(model.get_n_items()):
            row = model.get_row(i)
            if row is None:
                continue
            node: FileNode = row.get_item()
            if Path(node.path_str) != proj:
                continue
            if not row.get_expanded():
                row.set_expanded(True)
            try:
                rel = file_path.relative_to(proj.resolve())
            except (ValueError, OSError):
                return False
            if rel.parts:
                GLib.idle_add(self._reveal_step, list(rel.parts), proj)
            else:
                self._select_position(i)
            return False
        return False

    def _select_position(self, i: int) -> None:
        selection = self.list_view.get_model()
        if isinstance(selection, Gtk.SingleSelection):
            selection.set_selected(i)
        self.list_view.scroll_to(i, Gtk.ListScrollFlags.FOCUS, None)

    def _reveal_step(self, parts: list[str], parent_path: Path) -> bool:
        from gi.repository import GLib

        target = parent_path / parts[0]
        target_str = str(target)
        model = self._tree_model
        if model is None:
            return False
        for i in range(model.get_n_items()):
            row = model.get_row(i)
            if row is None:
                continue
            node: FileNode = row.get_item()
            if node.path_str != target_str:
                continue
            if len(parts) > 1:
                if not row.get_expanded():
                    row.set_expanded(True)
                GLib.idle_add(self._reveal_step, parts[1:], target)
            else:
                self._select_position(i)
            return False
        return False
