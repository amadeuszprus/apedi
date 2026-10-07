"""Project sidebar — directory tree view."""

from __future__ import annotations

import builtins
import logging
import threading
from pathlib import Path
from typing import Callable

if not hasattr(builtins, "_"):
    builtins._ = lambda s: s  # type: ignore[attr-defined]

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, GLib, GObject, Gio, Gtk  # noqa: E402

from .browser import is_html_path
from .gitstate import RepoStatus
from .ignore_filter import IgnoreFilter

log = logging.getLogger(__name__)

GitStateFn = Callable[[Path], "str | None"]


class FileNode(GObject.Object):
    __gtype_name__ = "ApediFileNode"

    name = GObject.Property(type=str, default="")
    path_str = GObject.Property(type=str, default="")
    is_dir = GObject.Property(type=bool, default=False)
    is_ignored = GObject.Property(type=bool, default=False)
    is_heavy = GObject.Property(type=bool, default=False)
    is_project = GObject.Property(type=bool, default=False)
    # "" | "added" | "modified" | "conflict" - drives the label colour.
    git_state = GObject.Property(type=str, default="")
    # Placeholder row shown while a folder is being listed in the background.
    is_loading = GObject.Property(type=bool, default=False)


def _safe_is_dir(path: Path) -> bool:
    try:
        return path.is_dir()
    except OSError:
        return False


def _sort_key(node: "FileNode") -> tuple[bool, str]:
    """Folders first, then case-insensitive by name — the order `_scan_dir`
    emits, and the order `_sync_store` relies on when merging."""
    return (not node.is_dir, node.name.lower())


def _scan_dir(
    path: Path, ignore: IgnoreFilter | None, git_state: GitStateFn | None = None,
) -> list["FileNode"]:
    try:
        entries = sorted(
            path.iterdir(),
            key=lambda p: (not _safe_is_dir(p), p.name.lower()),
        )
    except OSError as e:
        log.debug("cannot list %s: %s", path, e)
        return []
    nodes: list[FileNode] = []
    for entry in entries:
        if entry.name in (".git",):
            # always hide .git itself even when not in gitignore
            continue
        node = FileNode()
        node.name = entry.name
        node.path_str = str(entry)
        node.is_dir = _safe_is_dir(entry)
        node.is_heavy = ignore.is_heavy(entry) if ignore else False
        node.is_ignored = ignore.is_ignored(entry, is_dir=node.is_dir) if ignore else False
        node.git_state = (git_state(entry) if git_state else None) or ""
        nodes.append(node)
    return nodes


def _loading_node(path: Path) -> FileNode:
    node = FileNode()
    node.name = _("Loading…")
    node.path_str = str(path / "\0loading")
    node.is_loading = True
    return node


class DirModel(GObject.Object, Gio.ListModel):
    """A folder's children, listed on a worker thread the first time they are requested."""

    __gtype_name__ = "ApediDirModel"

    def __init__(
        self,
        path: Path,
        scan: Callable[[], list[FileNode]],
        *,
        defer: bool = True,
        start_thread: bool = True,
    ) -> None:
        super().__init__()
        self.path = path
        self._scan = scan
        self._defer = defer
        self._start_thread = start_thread
        self._items: list[FileNode] = []
        self._started = False
        self.ready = False

    # ---------- Gio.ListModel ----------

    def do_get_item_type(self) -> GObject.GType:
        return FileNode.__gtype__

    def do_get_n_items(self) -> int:
        self._ensure_started()
        return len(self._items)

    def do_get_item(self, position: int) -> FileNode | None:
        self._ensure_started()
        if 0 <= position < len(self._items):
            return self._items[position]
        return None

    # ---------- loading ----------

    def _ensure_started(self) -> None:
        if self._started:
            return
        self._started = True
        if not self._defer:
            self.finish(self._scan())
            return
        self._items = [_loading_node(self.path)]
        if self._start_thread:
            threading.Thread(target=self._scan_in_thread, name="apedi-dir-scan", daemon=True).start()

    def _scan_in_thread(self) -> None:
        try:
            nodes = self._scan()
        except Exception:  # noqa: BLE001
            log.exception("listing %s failed", self.path)
            nodes = []
        GLib.idle_add(self._finish_idle, nodes)

    def _finish_idle(self, nodes: list[FileNode]) -> bool:
        self.finish(nodes)
        return False

    def finish(self, nodes: list[FileNode]) -> None:
        """Swap the placeholder, or nothing, for `nodes`."""
        old = len(self._items)
        self._items = list(nodes)
        self.ready = True
        if old or self._items:
            self.items_changed(0, old, len(self._items))

    def loaded_items(self) -> list[FileNode]:
        """The rows, without triggering a listing that has not happened."""
        return list(self._items) if self.ready else []

    def sync(self, fresh: list[FileNode]) -> None:
        """Re-merge a fresh listing; a no-op for a folder never expanded."""
        if self.ready:
            _sync_store(self, fresh)

    # ---------- the ListStore slice _sync_store uses ----------

    def insert(self, position: int, node: FileNode) -> None:
        self._items.insert(position, node)
        self.items_changed(position, 0, 1)

    def remove(self, position: int) -> None:
        del self._items[position]
        self.items_changed(position, 1, 0)


def _sync_store(store: "Gio.ListStore | DirModel", fresh: list["FileNode"]) -> None:
    """Merge `fresh` into `store` in place, both sorted by `_sort_key`.

    In-place is the whole point: rebuilding the store would destroy the
    GtkTreeListRow attached to every folder, collapsing the tree. Surviving
    rows keep their identity, so their expansion survives too.
    """
    i = 0
    for node in fresh:
        while i < store.get_n_items():
            existing = store.get_item(i)
            if existing.path_str == node.path_str:
                break
            if _sort_key(existing) >= _sort_key(node):
                break
            # Sorts before the next wanted entry, so it is gone from disk.
            store.remove(i)
        if i < store.get_n_items() and store.get_item(i).path_str == node.path_str:
            existing = store.get_item(i)
            if existing.is_dir != node.is_dir:
                # A path that swapped between file and folder also swaps sort
                # position, so replace it rather than leave the store in an
                # order later merges no longer hold true.
                store.remove(i)
                store.insert(i, node)
            else:
                existing.is_heavy = node.is_heavy
                existing.is_ignored = node.is_ignored
                if existing.git_state != node.git_state:
                    existing.git_state = node.git_state
        else:
            store.insert(i, node)
        i += 1
    while store.get_n_items() > i:
        store.remove(i)


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
        # Child models handed to the tree model, keyed by directory path.
        # Holding them lets `refresh_dir` update a folder in place instead
        # of rebuilding the tree and collapsing everything.
        self._child_stores: dict[str, DirModel] = {}
        self._extra_ignore_patterns: list[str] = []
        # Last known `git status` per project root, keyed by path string.
        self._git_status: dict[str, RepoStatus] = {}
        self.on_close_project: Callable[[Path], None] | None = None
        # Fired after the project list changes.
        self.on_projects_changed: Callable[[], None] | None = None
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
        factory.connect("unbind", self._unbind_item)
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
        self._child_stores.clear()
        self._git_status.clear()
        for p in paths:
            self._add_project(p)
        self._projects_changed()

    def add_project(self, path: Path) -> bool:
        added = self._add_project(path)
        if added:
            self._projects_changed()
        return added

    def _projects_changed(self) -> None:
        if self.on_projects_changed is not None:
            self.on_projects_changed()

    def _add_project(self, path: Path) -> bool:
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
        node.git_state = self._git_state_for(path) or ""
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
        self._git_status.pop(str(path), None)
        prefix = str(path)
        for key in [k for k in self._child_stores if k == prefix or k.startswith(prefix + "/")]:
            del self._child_stores[key]
        if self.root_path == path:
            self.root_path = self._projects[-1] if self._projects else None
        self._projects_changed()

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

    def _ignore_for(self, path: Path) -> IgnoreFilter | None:
        proj = self.project_for(path)
        return self._ignore_filters.get(str(proj)) if proj else None

    # ---------- git state ----------

    def _git_state_for(self, path: Path) -> str | None:
        proj = self.project_for(path)
        status = self._git_status.get(str(proj)) if proj else None
        return status.state_for(path) if status else None

    def _git_state_fn_for_dir(self, directory: Path) -> GitStateFn | None:
        """State lookup bound to one folder's project, resolved once per listing."""
        proj = self.project_for(directory)
        status = self._git_status.get(str(proj)) if proj else None
        return status.state_for if status else None

    def set_git_status(self, project: Path, status: RepoStatus | None) -> None:
        """Apply a fresh `git status` to the rows already built, in place."""
        key = str(project)
        if status is None:
            self._git_status.pop(key, None)
        else:
            self._git_status[key] = status
        self._recolour(project)

    def clear_git_status(self) -> None:
        self._git_status.clear()
        for proj in self._projects:
            self._recolour(proj)

    def _recolour(self, project: Path) -> None:
        prefix = str(project)
        stores = [self._roots_store] + [
            s for k, s in self._child_stores.items()
            if k == prefix or k.startswith(prefix + "/")
        ]
        for store in stores:
            nodes = (
                [store.get_item(i) for i in range(store.get_n_items())]
                if store is self._roots_store else store.loaded_items()
            )
            for node in nodes:
                if store is self._roots_store and node.path_str != prefix:
                    continue
                state = self._git_state_for(Path(node.path_str)) or ""
                if node.git_state != state:
                    node.git_state = state

    def _expand_for_node(self, item: GObject.Object) -> DirModel | None:
        if not isinstance(item, FileNode) or not item.is_dir or item.is_loading:
            return None
        path = Path(item.path_str)
        model = DirModel(path, lambda: self._scan(path))
        self._child_stores[item.path_str] = model
        return model

    def _scan(self, path: Path) -> list[FileNode]:
        return _scan_dir(path, self._ignore_for(path), self._git_state_fn_for_dir(path))

    def refresh_dir(self, path: Path) -> None:
        """Re-read one folder, keeping the rest of the tree as the user left it.

        A no-op for a folder that has never been expanded — the tree model
        lists it fresh the first time it is opened anyway.
        """
        model = self._child_stores.get(str(path))
        if model is None or not model.ready:
            return
        model.sync(self._scan(path))
        self._prune_child_stores()

    def _prune_child_stores(self) -> None:
        """Forget stores for folders that no longer exist — a renamed or
        deleted folder leaves its subtree's entries behind otherwise."""
        for key in [k for k in self._child_stores if not _safe_is_dir(Path(k))]:
            del self._child_stores[key]

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
        spinner = Gtk.Spinner()
        spinner.set_visible(False)
        label = Gtk.Label(xalign=0, ellipsize=3)
        label.set_hexpand(True)
        close_btn = Gtk.Button.new_from_icon_name("window-close-symbolic")
        close_btn.add_css_class("flat")
        close_btn.set_tooltip_text(_("Close project"))
        close_btn.set_visible(False)
        box.append(icon)
        box.append(spinner)
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
        expander: Gtk.TreeExpander = item.get_child()
        row: Gtk.TreeListRow = item.get_item()
        expander.set_list_row(row)
        node: FileNode = row.get_item()
        box: Gtk.Box = expander.get_child()
        icon: Gtk.Image = box.get_first_child()
        spinner: Gtk.Spinner = icon.get_next_sibling()
        label: Gtk.Label = spinner.get_next_sibling()
        close_btn: Gtk.Button = label.get_next_sibling()

        box._apedi_node = node

        prev_handler = getattr(close_btn, "_apedi_handler", 0)
        if prev_handler:
            close_btn.disconnect(prev_handler)
            close_btn._apedi_handler = 0

        icon.set_visible(not node.is_loading)
        spinner.set_visible(node.is_loading)
        if node.is_loading:
            spinner.start()
        else:
            spinner.stop()

        if node.is_loading:
            close_btn.set_visible(False)
        elif node.is_project:
            icon.set_from_icon_name("folder-symbolic")
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
            close_btn.set_visible(False)
        label.set_css_classes(self._label_classes(node))
        label.set_text(node.name)
        # Git state changes on its own, so recolour the row in place.
        label._apedi_git_node = node
        label._apedi_git_handler = node.connect(
            "notify::git-state",
            lambda n, _pspec, lbl=label: lbl.set_css_classes(self._label_classes(n)),
        )

    def _unbind_item(self, _factory: Gtk.SignalListItemFactory, item: Gtk.ListItem) -> None:
        expander: Gtk.TreeExpander = item.get_child()
        box: Gtk.Box = expander.get_child()
        spinner: Gtk.Spinner = box.get_first_child().get_next_sibling()
        spinner.stop()
        label: Gtk.Label = spinner.get_next_sibling()
        node = getattr(label, "_apedi_git_node", None)
        handler = getattr(label, "_apedi_git_handler", 0)
        if node is not None and handler:
            node.disconnect(handler)
        label._apedi_git_node = None
        label._apedi_git_handler = 0

    @staticmethod
    def _label_classes(node: FileNode) -> list[str]:
        from . import style

        classes: list[str] = []
        if node.is_loading:
            return ["file-ignored"]
        if node.is_project:
            classes.append("project-root")
        elif not node.is_dir:
            classes.append(style.class_for_filename(node.name))
        if node.git_state:
            classes.append(f"git-{node.git_state}")
        if node.is_ignored:
            classes.append("file-ignored")
        if node.is_heavy:
            classes.append("file-heavy")
        return classes

    def _handle_close_project(self, path: Path) -> None:
        if self.on_close_project is not None:
            self.on_close_project(path)
        else:
            self.remove_project(path)

    def _on_right_click(self, box: Gtk.Box, x: float, y: float) -> None:
        node: FileNode | None = getattr(box, "_apedi_node", None)
        if node is None or node.is_loading:
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
        add_button(_("Rename…"), "rename")
        add_separator()
        if not is_dir and is_html_path(path):
            add_button(_("Open in Browser"), "open-in-browser")
            add_separator()
        if not is_dir:
            add_button(_("Copy File"), "copy-file")
            add_button(_("Copy File Path"), "copy-file-path")
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
        if node.is_loading:
            return
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
                self._when_listed(proj, lambda: self._reveal_step(list(rel.parts), proj))
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
                self._when_listed(target, lambda: self._reveal_step(parts[1:], target))
            else:
                self._select_position(i)
            return False
        return False

    def _when_listed(self, directory: Path, then: Callable[[], object]) -> None:
        """Run `then` once `directory`'s rows exist."""
        model = self._child_stores.get(str(directory))

        def poll() -> bool:
            current = self._child_stores.get(str(directory))
            if current is not None and not current.ready:
                return True  # keep polling
            then()
            return False

        if model is not None and model.ready:
            GLib.idle_add(lambda: (then(), False)[1])
        else:
            GLib.timeout_add(30, poll)
