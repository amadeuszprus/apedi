"""EditorWindow + EditorTab — main UI."""

from __future__ import annotations

import builtins
import logging
import os
from pathlib import Path
from typing import Callable

# Fallback so files imported before app.py runs i18n.install still resolve _().
if not hasattr(builtins, "_"):
    builtins._ = lambda s: s  # type: ignore[attr-defined]

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("GtkSource", "5")
from gi.repository import Gdk, Gio, GLib, GObject, Gtk, GtkSource  # noqa: E402

from . import file_io, recent, theming
from .buffer import EditorBuffer
from .settings import Settings, clamp_split_ratio

log = logging.getLogger(__name__)

# Debounce for persisting a dragged markdown split — the handle emits a
# position change per pixel, and each save rewrites config.toml.
SPLIT_SAVE_DELAY_MS = 500


def _likely_snap_confinement_block(path: Path) -> bool:
    """Heuristic: are we running under strict snap confinement and pointed
    at a file the sandbox is denied? Used to turn an opaque
    `FileNotFoundError` into a clear error message."""
    if not os.environ.get("SNAP"):
        return False
    home = Path.home()
    try:
        path.resolve().relative_to(home)
        return False  # inside home — allowed by `home` plug
    except (OSError, ValueError):
        pass
    s = str(path)
    if s.startswith(("/media/", "/mnt/", "/run/media/")):
        return False  # removable-media plug
    return True


class EditorTab(Gtk.Paned):
    """One editor tab — source view on the left, optional markdown preview
    on the right (lazy)."""

    __gtype_name__ = "ApediEditorTab"

    def __init__(self, buffer: EditorBuffer, settings: Settings) -> None:
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL)
        self.set_hexpand(True)
        self.set_vexpand(True)
        self.set_wide_handle(True)
        self.buffer = buffer
        self.view = GtkSource.View.new_with_buffer(buffer)
        self._wire_selection_menu()
        self._editor_scroll = Gtk.ScrolledWindow()
        self._editor_scroll.set_hexpand(True)
        self._editor_scroll.set_vexpand(True)
        self._editor_scroll.set_child(self.view)
        # Minimap sits to the right of the source view inside the paned's
        # start child; visibility is driven by settings.show_minimap.
        self._minimap = GtkSource.Map()
        self._minimap.set_view(self.view)
        self._minimap.set_vexpand(True)
        editor_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        editor_box.append(self._editor_scroll)
        editor_box.append(self._minimap)
        self.set_start_child(editor_box)
        self.set_resize_start_child(True)
        self.set_shrink_start_child(False)
        self.set_resize_end_child(True)
        self.set_shrink_end_child(False)
        self.preview: "Gtk.Widget | None" = None  # MarkdownPreview when created
        self.preview_visible: bool = False
        self.on_open_path: Callable[[Path], None] | None = None
        self._sync_guard: bool = False  # re-entrancy guard for scroll sync
        self._split_ratio: float = clamp_split_ratio(settings.markdown_split_ratio)
        self._split_pending: bool = False  # waiting for a real allocation
        self._split_applied_width: int = 0  # width the position was computed for
        self._allocating: bool = False  # inside do_size_allocate
        self.on_split_ratio_changed: Callable[[float], None] | None = None
        self.connect("notify::position", self._on_split_position_changed)
        self._apply_settings(settings)
        self.search_settings = GtkSource.SearchSettings()
        self.search_settings.set_wrap_around(True)
        self.search_context = GtkSource.SearchContext.new(buffer, self.search_settings)
        self._monitor: Gio.FileMonitor | None = None
        self.on_external_change: Callable[[Path], None] | None = None
        buffer.connect("notify::path-str", lambda *_: self._rewire_monitor())
        self._rewire_monitor()

    def _wire_selection_menu(self) -> None:
        """Offer Normalize Whitespace in the right-click menu, but only while
        something is selected — that is the scope the command acts on."""
        menu = Gio.Menu()
        menu.append(_("Normalize Whitespace"), "win.normalize")
        self._selection_menu = menu

        def sync(*_args: object) -> None:
            has_selection = self.buffer.get_has_selection()
            self.view.set_extra_menu(menu if has_selection else None)

        self.buffer.connect("notify::has-selection", sync)
        sync()

    def _rewire_monitor(self) -> None:
        if self._monitor is not None:
            self._monitor.cancel()
            self._monitor = None
        if not self.buffer.path:
            return
        gfile = Gio.File.new_for_path(str(self.buffer.path))
        try:
            self._monitor = gfile.monitor_file(Gio.FileMonitorFlags.NONE, None)
        except GLib.GError as e:
            log.debug("file monitor failed for %s: %s", self.buffer.path, e)
            return
        self._monitor.connect("changed", self._on_file_changed)

    def _on_file_changed(self, _monitor, _file, _other, event) -> None:
        if event != Gio.FileMonitorEvent.CHANGES_DONE_HINT:
            return
        if self.buffer.path is None or self.on_external_change is None:
            return
        try:
            mtime = self.buffer.path.stat().st_mtime
        except OSError:
            return
        if self.buffer.mtime_at_load is None:
            return
        if mtime <= self.buffer.mtime_at_load + 0.5:
            return
        self.on_external_change(self.buffer.path)

    def _apply_settings(self, s: Settings) -> None:
        self.view.set_show_line_numbers(s.show_line_numbers)
        self.view.set_highlight_current_line(True)
        self.view.set_auto_indent(s.auto_indent)
        self.view.set_indent_on_tab(True)
        self.view.set_tab_width(s.tab_width)
        self.view.set_indent_width(s.tab_width)
        self.view.set_insert_spaces_instead_of_tabs(s.use_spaces)
        self.view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR if s.wrap_lines else Gtk.WrapMode.NONE)
        # Wrapped text never overflows, so pin the horizontal scrollbar off
        # rather than leaving it to the scrolled window's automatic policy.
        self._editor_scroll.set_policy(
            Gtk.PolicyType.NEVER if s.wrap_lines else Gtk.PolicyType.AUTOMATIC,
            Gtk.PolicyType.AUTOMATIC,
        )
        self.view.set_monospace(True)
        if hasattr(self, "_minimap"):
            self._minimap.set_visible(s.show_minimap)
        css = Gtk.CssProvider()
        css.load_from_string(
            f"textview {{ font-family: '{s.font}'; font-size: {s.font_size}pt; }}"
        )
        self.view.get_style_context().add_provider(
            css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
        scheme = GtkSource.StyleSchemeManager.get_default().get_scheme(s.color_scheme)
        if scheme:
            self.buffer.set_style_scheme(scheme)
        self._preview_dark = theming.is_dark_scheme(s.color_scheme or "", self._scheme_variants())
        if self.preview is not None and hasattr(self.preview, "set_dark"):
            self.preview.set_dark(self._preview_dark)
        ratio = clamp_split_ratio(s.markdown_split_ratio)
        if ratio != self._split_ratio:
            self._split_ratio = ratio
            if self.preview_visible:
                self._request_split_ratio()

    @staticmethod
    def _scheme_variants() -> dict[str, theming.SchemeVariants]:
        # Cached on the class: the manager's metadata doesn't change at runtime.
        cached = getattr(EditorTab, "_scheme_variants_cache", None)
        if cached is None:
            cached, _ids = theming.collect_scheme_variants()
            EditorTab._scheme_variants_cache = cached
        return cached

    # ---------- markdown split ----------

    def _request_split_ratio(self) -> None:
        """Put the divider at the remembered fraction of the tab's width.

        Auto-preview fires while the tab is still being built, before GTK
        has given it a size — `get_width()` is 0 there, so the request is
        parked until `do_size_allocate` reports a real width.
        """
        width = self.get_width()
        if width <= 0:
            self._split_pending = True
            return
        self._split_pending = False
        self._split_applied_width = width
        self.set_position(int(width * self._split_ratio))

    def do_size_allocate(self, width: int, height: int, baseline: int) -> None:
        self._allocating = True
        try:
            Gtk.Paned.do_size_allocate(self, width, height, baseline)
        finally:
            self._allocating = False
        if width <= 0:
            return
        # GtkPaned carries the divider's *position* across a resize, so a tab
        # first laid out at the window's full width keeps that pixel offset
        # once the sidebar claims its 240px — landing at ~2/3 instead of half.
        # The stored fraction is what's authoritative, so re-derive from it
        # whenever the width we computed against is no longer current.
        stale = self.preview_visible and width != self._split_applied_width
        if self._split_pending or stale:
            self._request_split_ratio()

    def _on_split_position_changed(self, *_args: object) -> None:
        """Remember a split the user dragged.

        Position changes GTK makes itself while re-laying out (a window
        resize keeps the ratio anyway) arrive during allocation — only the
        ones outside it are the user moving the handle.
        """
        if self._allocating or not self.preview_visible:
            return
        width = self.get_width()
        if width <= 0:
            return
        ratio = clamp_split_ratio(self.get_position() / width)
        if abs(ratio - self._split_ratio) < 0.005:
            return
        self._split_ratio = ratio
        if self.on_split_ratio_changed is not None:
            self.on_split_ratio_changed(ratio)

    def _ensure_preview(self) -> "Gtk.Widget | None":
        if self.preview is not None:
            return self.preview
        from .markdown_preview import AVAILABLE, MarkdownPreview

        if not AVAILABLE:
            return None
        self.preview = MarkdownPreview()
        self.preview.set_dark(getattr(self, "_preview_dark", False))
        if self.on_open_path is not None:
            self.preview.on_open_path = self.on_open_path
        self.set_end_child(self.preview)
        self.preview.set_visible(False)
        self._wire_scroll_sync()
        return self.preview

    def _wire_scroll_sync(self) -> None:
        """Keep the source view and the preview scrolled to the same fraction."""
        if self.preview is None:
            return
        src_adj = self._editor_scroll.get_vadjustment()
        prev_adj = self.preview.get_vadjustment()
        if src_adj is None or prev_adj is None:
            return
        src_adj.connect("value-changed", self._sync_from_source)
        prev_adj.connect("value-changed", self._sync_from_preview)

    @staticmethod
    def _adj_fraction(adj: "Gtk.Adjustment") -> float:
        span = adj.get_upper() - adj.get_page_size()
        return adj.get_value() / span if span > 0 else 0.0

    @staticmethod
    def _adj_apply_fraction(adj: "Gtk.Adjustment", frac: float) -> None:
        span = adj.get_upper() - adj.get_page_size()
        adj.set_value(frac * span if span > 0 else 0.0)

    def _sync_from_source(self, src_adj: "Gtk.Adjustment") -> None:
        if self._sync_guard or not self.preview_visible or self.preview is None:
            return
        self._sync_guard = True
        self._adj_apply_fraction(self.preview.get_vadjustment(), self._adj_fraction(src_adj))
        self._sync_guard = False

    def _sync_from_preview(self, prev_adj: "Gtk.Adjustment") -> None:
        if self._sync_guard or not self.preview_visible or self.preview is None:
            return
        # Ignore the churn a re-render emits while rebuilding its widgets —
        # otherwise typing would yank the source view back to the top.
        if getattr(self.preview, "is_rendering", False):
            return
        self._sync_guard = True
        self._adj_apply_fraction(self._editor_scroll.get_vadjustment(), self._adj_fraction(prev_adj))
        self._sync_guard = False

    def set_preview_visible(self, visible: bool) -> bool:
        """Show/hide the markdown preview pane. Returns True on success."""
        if visible:
            preview = self._ensure_preview()
            if preview is None:
                return False
            preview.set_visible(True)
            self.preview_visible = True
            text = self.buffer.get_full_text()
            base = self.buffer.path.parent if self.buffer.path else None
            preview.update(text, base)
            preview.flush()
            self._request_split_ratio()
            return True
        if self.preview is not None:
            self.preview.set_visible(False)
        self.preview_visible = False
        return True

    def bump_preview(self) -> None:
        if not self.preview_visible or self.preview is None:
            return
        text = self.buffer.get_full_text()
        base = self.buffer.path.parent if self.buffer.path else None
        self.preview.update(text, base)


class EditorWindow(Gtk.ApplicationWindow):
    __gtype_name__ = "ApediEditorWindow"

    def __init__(self, app: Gtk.Application, settings: Settings) -> None:
        super().__init__(application=app, default_width=960, default_height=640)
        self.settings = settings
        self._deferred_init_done = False
        self.set_title("Apedi")
        self._build_ui()
        self._setup_actions()
        self._setup_drop_target()
        self.connect("close-request", self._on_close_request)

    # ---------- UI construction ----------

    @staticmethod
    def _support_menu_item(label: str, uri: str) -> Gio.MenuItem:
        item = Gio.MenuItem.new(label, None)
        item.set_action_and_target_value("app.support", GLib.Variant.new_string(uri))
        return item

    def _build_ui(self) -> None:
        header = Gtk.HeaderBar()

        # Far-left: hamburger menu
        menu_btn = Gtk.MenuButton()
        menu_btn.set_icon_name("open-menu-symbolic")
        menu_btn.set_tooltip_text(_("Menu"))
        header.pack_start(menu_btn)

        sidebar_btn = Gtk.Button.new_from_icon_name("sidebar-show-symbolic")
        sidebar_btn.set_action_name("win.toggle-sidebar")
        sidebar_btn.set_tooltip_text(_("Toggle sidebar (F9)"))
        header.pack_start(sidebar_btn)

        # Standard editor toolbar buttons
        new_btn = Gtk.Button.new_from_icon_name("document-new-symbolic")
        new_btn.set_action_name("win.new-tab")
        new_btn.set_tooltip_text(_("New tab (Ctrl+T)"))
        header.pack_start(new_btn)

        open_btn = Gtk.Button.new_from_icon_name("document-open-symbolic")
        open_btn.set_action_name("win.open")
        open_btn.set_tooltip_text(_("Open (Ctrl+O)"))
        header.pack_start(open_btn)

        save_btn = Gtk.Button.new_from_icon_name("document-save-symbolic")
        save_btn.set_action_name("win.save")
        save_btn.set_tooltip_text(_("Save (Ctrl+S)"))
        header.pack_start(save_btn)

        format_btn = Gtk.Button.new_from_icon_name("format-indent-more-symbolic")
        format_btn.set_action_name("win.format")
        format_btn.set_tooltip_text(_("Format (Ctrl+Shift+I)"))
        header.pack_start(format_btn)

        # Far-right: Support menu (Ko-fi / Buy me a coffee)
        coffee_menu = Gio.Menu()
        coffee_menu.append_item(self._support_menu_item(_("Ko-fi"), "https://ko-fi.com/aprus"))
        coffee_menu.append_item(self._support_menu_item(_("buycoffee.to"), "https://buycoffee.to/aprus"))
        coffee_btn = Gtk.MenuButton(label="☕")
        coffee_btn.set_tooltip_text(_("Support the author"))
        coffee_btn.set_menu_model(coffee_menu)
        coffee_btn.add_css_class("flat")
        header.pack_end(coffee_btn)

        menu = Gio.Menu()

        # Top level: the most-used file actions only.
        file_section = Gio.Menu()
        file_section.append(_("New Tab"), "win.new-tab")
        file_section.append(_("New Window"), "win.new-window")
        file_section.append(_("Open…"), "win.open")
        file_section.append(_("Open Project…"), "win.open-project")
        recent_menu = self.get_application().recent_menu  # type: ignore[attr-defined]
        file_section.append_submenu(_("Open Recent"), recent_menu)
        file_section.append(_("Save"), "win.save")
        file_section.append(_("Save As…"), "win.save-as")
        menu.append_section(None, file_section)

        # The two large command groups fold into submenus so the hamburger
        # menu stays short instead of scrolling through ~30 flat entries.
        edit_menu = Gio.Menu()
        edit_menu.append(_("Command Palette…"), "win.command-palette")
        edit_menu.append(_("Quick Open…"), "win.quick-open")
        edit_menu.append(_("Find…"), "win.find")
        edit_menu.append(_("Find in Files…"), "win.find-in-files")
        edit_menu.append(_("Replace…"), "win.replace")
        edit_menu.append(_("Go to Line…"), "win.goto-line")
        edit_menu.append(_("Go to Symbol…"), "win.symbols")
        edit_menu.append(_("Format Code"), "win.format")
        edit_menu.append(_("Normalize Whitespace"), "win.normalize")

        view_menu = Gio.Menu()
        view_menu.append(_("Toggle Sidebar"), "win.toggle-sidebar")
        view_menu.append(_("Toggle Terminal"), "win.toggle-terminal")
        view_menu.append(_("New Terminal"), "win.new-terminal")
        view_menu.append(_("Toggle Markdown Preview"), "win.toggle-preview")
        view_menu.append(_("Toggle Word Wrap"), "win.toggle-wrap")
        view_menu.append(_("Toggle Line Numbers"), "win.toggle-line-numbers")
        view_menu.append(_("Toggle Minimap"), "win.toggle-minimap")
        view_menu.append(_("Toggle Dark Mode"), "win.toggle-dark")

        groups_section = Gio.Menu()
        groups_section.append_submenu(_("Edit"), edit_menu)
        groups_section.append_submenu(_("View"), view_menu)
        menu.append_section(None, groups_section)

        prefs_section = Gio.Menu()
        prefs_section.append(_("Preferences…"), "win.preferences")
        menu.append_section(None, prefs_section)

        # Help collapses into a single submenu (shortcuts / what's new /
        # support / about).
        help_menu = Gio.Menu()
        help_menu.append(_("Keyboard Shortcuts"), "win.shortcuts")
        help_menu.append(_("What's New"), "app.whats-new")
        help_menu.append(_("About Apedi"), "app.about")

        support_submenu = Gio.Menu()
        support_submenu.append_item(self._support_menu_item(_("Ko-fi"), "https://ko-fi.com/aprus"))
        support_submenu.append_item(self._support_menu_item(_("buycoffee.to"), "https://buycoffee.to/aprus"))

        # Support the author stays at the top level, alongside Help.
        help_section = Gio.Menu()
        help_section.append_submenu(_("Help"), help_menu)
        help_section.append_submenu(_("☕ Support the author"), support_submenu)
        menu.append_section(None, help_section)

        app_section = Gio.Menu()
        app_section.append(_("Close Tab"), "win.close-tab")
        app_section.append(_("Close Window"), "win.close-window")
        app_section.append(_("Quit"), "app.quit")
        menu.append_section(None, app_section)

        # Menu created above; assign it to the far-left menu button.
        menu_btn.set_menu_model(menu)
        self.set_titlebar(header)

        from .sidebar import ProjectSidebar

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        vbox.append(self._build_search_bar())

        self.notebook = Gtk.Notebook()
        self.notebook.set_scrollable(True)
        self.notebook.set_hexpand(True)
        self.notebook.set_vexpand(True)
        self.notebook.connect("switch-page", self._on_switch_page)

        self.sidebar = ProjectSidebar(self._sidebar_open_file)
        self.sidebar.on_close_project = self._sidebar_close_project
        self.sidebar.on_context_action = self._dispatch_sidebar_action
        self.paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        self.paned.set_position(240)
        self.paned.set_shrink_start_child(False)
        self.paned.set_resize_start_child(False)
        self.paned.set_start_child(self.sidebar)
        self.paned.set_end_child(self.notebook)
        self.paned.set_hexpand(True)
        self.paned.set_vexpand(True)

        self.terminal_panel: "Gtk.Widget | None" = None
        self.vpaned = Gtk.Paned(orientation=Gtk.Orientation.VERTICAL)
        self.vpaned.set_wide_handle(True)
        self.vpaned.set_resize_start_child(True)
        self.vpaned.set_resize_end_child(False)
        self.vpaned.set_shrink_end_child(False)
        self.vpaned.set_start_child(self.paned)
        self.vpaned.set_hexpand(True)
        self.vpaned.set_vexpand(True)
        vbox.append(self.vpaned)

        self.status_bar = Gtk.Statusbar()
        self.status_ctx = self.status_bar.get_context_id("main")
        vbox.append(self.status_bar)

        self.set_child(vbox)
        self._apply_sidebar_visibility()

        self._autosave_timer_id: int | None = None
        self._split_save_timer_id: int | None = None
        self.connect("notify::is-active", self._on_active_changed)

        GLib.idle_add(self._init_deferred, priority=GLib.PRIORITY_LOW)

    def _init_deferred(self) -> bool:
        """Phase 2: heavy I/O and Vte startup, after first frame is on screen.
        Idempotent — also force-called sync by terminal actions if user
        triggers them before idle fires."""
        if self._deferred_init_done:
            return False
        self._deferred_init_done = True
        try:
            self.terminal_panel = self._build_terminal_panel()
            if self.terminal_panel is not None:
                self.vpaned.set_end_child(self.terminal_panel)
                self._apply_terminal_visibility()
            self._restore_last_project()
        except Exception:
            log.exception("deferred window init failed")
        return False

    def _build_terminal_panel(self) -> "Gtk.Widget | None":
        try:
            from .terminal import TerminalPanel
        except (ImportError, ValueError) as e:
            log.warning("terminal disabled — Vte unavailable: %s", e)
            return None
        return TerminalPanel()

    def _apply_terminal_visibility(self) -> None:
        if self.terminal_panel is None:
            return
        visible = bool(self.settings.show_terminal)
        self.terminal_panel.set_visible(visible)
        if visible:
            self.terminal_panel.ensure_started(
                self.settings.last_project or None
            )

    def _sidebar_open_file(self, path: Path) -> None:
        self.open_path(path)

    def _sidebar_close_project(self, path: Path) -> None:
        self.sidebar.remove_project(path)
        self.settings.projects = [str(p) for p in self.sidebar.projects()]
        if self.sidebar.projects():
            self.settings.last_project = str(self.sidebar.projects()[-1])
        else:
            self.settings.last_project = ""
        self.settings.save()

    def _apply_sidebar_visibility(self) -> None:
        self.sidebar.set_visible(self.settings.show_sidebar)
        self.sidebar.set_compact(self.settings.sidebar_compact)
        self.sidebar.update_extra_patterns(list(self.settings.ignore_patterns))

    def _restore_last_project(self) -> None:
        paths_str = list(self.settings.projects)
        if not paths_str and self.settings.last_project:
            paths_str = [self.settings.last_project]
        valid = [Path(p) for p in paths_str if Path(p).is_dir()]
        self.sidebar.set_projects(valid, list(self.settings.ignore_patterns))

    def _build_search_bar(self) -> Gtk.SearchBar:
        self.search_bar = Gtk.SearchBar()
        self.search_bar.set_show_close_button(True)

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)

        self.search_entry = Gtk.SearchEntry()
        self.search_entry.set_placeholder_text("Find")
        self.search_entry.set_hexpand(True)
        self.search_entry.connect("search-changed", self._on_search_changed)
        self.search_entry.connect("activate", lambda *_: self._search_jump(forward=True))
        box.append(self.search_entry)

        prev_btn = Gtk.Button.new_from_icon_name("go-up-symbolic")
        prev_btn.set_tooltip_text("Previous match")
        prev_btn.connect("clicked", lambda *_: self._search_jump(forward=False))
        box.append(prev_btn)

        next_btn = Gtk.Button.new_from_icon_name("go-down-symbolic")
        next_btn.set_tooltip_text("Next match")
        next_btn.connect("clicked", lambda *_: self._search_jump(forward=True))
        box.append(next_btn)

        self.replace_entry = Gtk.Entry()
        self.replace_entry.set_placeholder_text("Replace with")
        self.replace_entry.set_hexpand(True)
        box.append(self.replace_entry)

        replace_btn = Gtk.Button(label="Replace")
        replace_btn.connect("clicked", lambda *_: self._replace_one())
        box.append(replace_btn)

        replace_all_btn = Gtk.Button(label="All")
        replace_all_btn.connect("clicked", lambda *_: self._replace_all())
        box.append(replace_all_btn)

        self.search_bar.connect_entry(self.search_entry)
        self.search_bar.set_child(box)
        self._replace_widgets = (self.replace_entry, replace_btn, replace_all_btn)
        self._set_replace_visible(False)
        return self.search_bar

    def _set_replace_visible(self, visible: bool) -> None:
        for w in self._replace_widgets:
            w.set_visible(visible)

    # ---------- Actions ----------

    def _setup_actions(self) -> None:
        defs = [
            ("new-tab", self.action_new_tab),
            ("new-window", self.action_new_window),
            ("open", self.action_open),
            ("save", self.action_save),
            ("save-as", self.action_save_as),
            ("close-tab", self.action_close_tab),
            ("close-window", self.action_close_window),
            ("next-tab", self.action_next_tab),
            ("prev-tab", self.action_prev_tab),
            ("find", self.action_find),
            ("replace", self.action_replace),
            ("goto-line", self.action_goto_line),
            ("format", self.action_format),
            ("normalize", self.action_normalize),
            ("open-backups", self.action_open_backups),
            ("toggle-wrap", self.action_toggle_wrap),
            ("toggle-line-numbers", self.action_toggle_line_numbers),
            ("toggle-minimap", self.action_toggle_minimap),
            ("toggle-dark", self.action_toggle_dark),
            ("command-palette", self.action_command_palette),
            ("preferences", self.action_preferences),
            ("open-project", self.action_open_project),
            ("toggle-sidebar", self.action_toggle_sidebar),
            ("toggle-terminal", self.action_toggle_terminal),
            ("new-terminal", self.action_new_terminal),
            ("toggle-preview", self.action_toggle_preview),
            ("sidebar-new-file", self.action_sidebar_new_file),
            ("sidebar-new-folder", self.action_sidebar_new_folder),
            ("sidebar-rename", self.action_sidebar_rename),
            ("sidebar-find", self.action_sidebar_find),
            ("sidebar-replace", self.action_sidebar_replace),
            ("sidebar-replace-with", self.action_sidebar_replace_with),
            ("symbols", self.action_symbols),
            ("quick-open", self.action_quick_open),
            ("find-in-files", self.action_find_in_files),
            ("shortcuts", self.action_shortcuts),
        ]
        for name, cb in defs:
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", cb)
            self.add_action(action)

    # ---------- Tab management ----------

    def current_tab(self) -> EditorTab | None:
        page = self.notebook.get_current_page()
        if page < 0:
            return None
        return self.notebook.get_nth_page(page)  # type: ignore[return-value]

    def all_tabs(self) -> list[EditorTab]:
        n = self.notebook.get_n_pages()
        return [self.notebook.get_nth_page(i) for i in range(n)]  # type: ignore[misc]

    def add_tab(self, buffer: EditorBuffer | None = None) -> EditorTab:
        if buffer is None:
            buffer = EditorBuffer()
        tab = EditorTab(buffer, self.settings)
        label = self._make_tab_label(tab)
        idx = self.notebook.append_page(tab, label)
        self.notebook.set_tab_reorderable(tab, True)
        self.notebook.set_current_page(idx)
        buffer.connect("modified-changed", lambda *_: self._update_status())
        buffer.connect("notify::language", lambda *_: self._update_status())
        buffer.connect("notify::cursor-position", lambda *_: self._update_status())
        buffer.connect("changed", lambda *_: self._autosave_bump())
        buffer.connect("changed", lambda *_: self._draft_bump(tab))
        buffer.connect("changed", lambda *_: tab.bump_preview())
        buffer.connect("notify::path-str", lambda *_: self._maybe_auto_preview(tab))
        tab.on_external_change = self._on_buffer_external_change
        tab.on_open_path = self.open_path
        tab.on_split_ratio_changed = self._on_split_ratio_changed
        tab.view.grab_focus()
        self._maybe_auto_preview(tab)
        return tab

    def _on_split_ratio_changed(self, ratio: float) -> None:
        """A markdown split was dragged — remember it for the next preview."""
        if self.settings.markdown_split_ratio == ratio:
            return
        self.settings.markdown_split_ratio = ratio
        if self._split_save_timer_id is not None:
            GLib.source_remove(self._split_save_timer_id)
        self._split_save_timer_id = GLib.timeout_add(
            SPLIT_SAVE_DELAY_MS, self._split_ratio_save_fire
        )

    def _split_ratio_save_fire(self) -> bool:
        self._split_save_timer_id = None
        self.settings.save()
        return False  # one-shot

    def _make_tab_label(self, tab: EditorTab) -> Gtk.Box:
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        label = Gtk.Label()
        box.append(label)
        close_btn = Gtk.Button.new_from_icon_name("window-close-symbolic")
        close_btn.add_css_class("flat")
        close_btn.set_has_frame(False)
        close_btn.connect("clicked", lambda *_: self._close_specific_tab(tab))
        box.append(close_btn)

        middle_click = Gtk.GestureClick.new()
        middle_click.set_button(2)
        middle_click.connect("released", lambda *_: self._close_specific_tab(tab))
        box.add_controller(middle_click)

        def update(*_args: object) -> None:
            name = tab.buffer.display_name()
            if tab.buffer.get_modified():
                name = "• " + name
            label.set_text(name)
            tooltip = str(tab.buffer.path) if tab.buffer.path else "Untitled"
            label.set_tooltip_text(tooltip)

        tab.buffer.connect("notify::path-str", update)
        tab.buffer.connect("modified-changed", update)
        update()
        return box

    def open_path(self, path: Path, *, allow_binary: bool = False, allow_large: bool = False) -> bool:
        # Already open?
        for tab in self.all_tabs():
            if tab.buffer.path and tab.buffer.path.resolve() == path.resolve():
                self.notebook.set_current_page(self.notebook.page_num(tab))
                return True

        try:
            loaded = file_io.load_file(path, allow_binary=allow_binary, allow_large=allow_large)
        except FileNotFoundError:
            if _likely_snap_confinement_block(path):
                self._alert(
                    _("Cannot read file (snap confinement)"),
                    _(
                        "Apedi installed from the snap store can only read "
                        "files inside your home folder or on removable media.\n\n"
                        "Tried to open:\n{path}\n\n"
                        "Move the file under your home folder, or install "
                        "Apedi outside snap to access system paths."
                    ).format(path=path),
                )
                return False
            # Treat as new file with that path
            buffer = EditorBuffer()
            buffer.path = path
            buffer.detect_language()
            self.add_tab(buffer)
            self._set_status(f"New file: {path.name}")
            return True
        except file_io.FileTooLargeError as e:
            self._confirm_async(
                "Open large file?",
                f"{e.path.name} is {e.size // (1024 * 1024)} MB. Open anyway?",
                lambda yes: self.open_path(path, allow_binary=allow_binary, allow_large=True) if yes else None,
            )
            return False
        except file_io.BinaryFileError:
            self._confirm_async(
                "Open binary file?",
                f"{path.name} appears to be binary. Open as text?",
                lambda yes: self.open_path(path, allow_binary=True, allow_large=allow_large) if yes else None,
            )
            return False
        except (OSError, PermissionError) as e:
            self._alert("Cannot open file", f"{path}: {e}")
            return False

        # Re-use empty unmodified initial tab if present
        tab = self.current_tab()
        if tab and tab.buffer.path is None and not tab.buffer.get_modified() and tab.buffer.get_char_count() == 0:
            tab.buffer.load(loaded.text, path, loaded.encoding, loaded.mtime)
        else:
            buffer = EditorBuffer()
            buffer.load(loaded.text, path, loaded.encoding, loaded.mtime)
            self.add_tab(buffer)

        recent.save(recent.add(path))
        self.get_application().notify_recent_changed()
        self._set_status(f"Opened {path.name} ({loaded.encoding})")
        self._maybe_switch_project(path)
        return True

    def _maybe_switch_project(self, file_path: Path) -> None:
        """If file is outside every open project, add a new project rooted at
        its git root or parent directory and reveal it. In-project opens just
        reveal."""
        try:
            resolved = file_path.resolve()
        except OSError:
            return
        if self.sidebar.project_for(resolved) is not None:
            self.sidebar.reveal_file(resolved)
            return
        new_root = self._find_project_root(resolved)
        if new_root is None:
            return
        if self.sidebar.add_project(new_root):
            self._persist_projects()
            if not self.settings.show_sidebar:
                self.settings.show_sidebar = True
                self._apply_sidebar_visibility()
            self.settings.save()
        self.sidebar.reveal_file(resolved)

    @staticmethod
    def _find_project_root(file_path: Path) -> Path | None:
        parent = file_path.parent
        try:
            parent = parent.resolve()
        except OSError:
            return None
        current = parent
        for _ in range(20):
            if (current / ".git").exists():
                return current
            if current.parent == current:
                break
            current = current.parent
        return parent

    # ---------- Action implementations ----------

    def action_new_tab(self, *_args: object) -> None:
        self.add_tab()

    def action_new_window(self, *_args: object) -> None:
        app = self.get_application()
        win = app.new_window()  # type: ignore[attr-defined]
        win.add_tab()
        win.present()

    def action_open(self, *_args: object) -> None:
        dialog = Gtk.FileDialog()
        dialog.set_title("Open File")
        dialog.open(self, None, self._on_open_response)

    def _on_open_response(self, dialog: Gtk.FileDialog, result: Gio.AsyncResult) -> None:
        try:
            file = dialog.open_finish(result)
        except GLib.Error as e:
            if "Dismissed" not in e.message:
                log.warning("Open dialog: %s", e.message)
            return
        if file:
            self.open_path(Path(file.get_path()))

    def action_save(self, *_args: object) -> None:
        tab = self.current_tab()
        if tab is None:
            return
        if tab.buffer.path is None:
            self.action_save_as()
            return
        self._save_to(tab, tab.buffer.path)

    def action_save_as(self, *_args: object) -> None:
        tab = self.current_tab()
        if tab is None:
            return
        dialog = Gtk.FileDialog()
        dialog.set_title("Save As")
        if tab.buffer.path:
            dialog.set_initial_file(Gio.File.new_for_path(str(tab.buffer.path)))
        dialog.save(self, None, lambda d, r: self._on_save_as_response(tab, d, r))

    def _on_save_as_response(self, tab: EditorTab, dialog: Gtk.FileDialog, result: Gio.AsyncResult) -> None:
        try:
            file = dialog.save_finish(result)
        except GLib.Error as e:
            if "Dismissed" not in e.message:
                log.warning("Save As dialog: %s", e.message)
            return
        if file:
            path = Path(file.get_path())

            def after(success: bool) -> None:
                if success:
                    tab.buffer.path = path
                    tab.buffer.detect_language()

            self._save_to(tab, path, after)

    def _save_to(self, tab: EditorTab, path: Path, on_done: callable | None = None) -> None:
        if path.exists() and tab.buffer.mtime_at_load is not None:
            current_mtime = path.stat().st_mtime
            if current_mtime > tab.buffer.mtime_at_load + 0.5:
                def cont(yes: bool) -> None:
                    if yes:
                        ok = self._do_save(tab, path)
                        if on_done:
                            on_done(ok)
                    elif on_done:
                        on_done(False)

                self._confirm_async(
                    "File changed on disk",
                    f"{path.name} was modified outside the editor. Overwrite?",
                    cont,
                )
                return
        ok = self._do_save(tab, path)
        if on_done:
            on_done(ok)

    def _do_save(self, tab: EditorTab, path: Path) -> bool:
        text = tab.buffer.get_full_text()
        if self.settings.trim_trailing_whitespace:
            text = "\n".join(line.rstrip() for line in text.split("\n"))
        try:
            mtime = file_io.save_file(path, text, tab.buffer.encoding)
        except (OSError, PermissionError) as e:
            self._alert("Cannot save file", f"{path}: {e}")
            return False
        tab.buffer.mtime_at_load = mtime
        tab.buffer.set_modified(False)
        from . import recovery
        recovery.discard(path)
        recent.save(recent.add(path))
        self.get_application().notify_recent_changed()
        self._set_status(f"Saved {path.name}")
        return True

    def action_close_tab(self, *_args: object) -> None:
        tab = self.current_tab()
        if tab is not None:
            self._close_specific_tab(tab)

    def _close_specific_tab(self, tab: EditorTab) -> None:
        def really_close() -> None:
            idx = self.notebook.page_num(tab)
            if idx >= 0:
                self.notebook.remove_page(idx)
            if self.notebook.get_n_pages() == 0:
                self.add_tab()

        if tab.buffer.get_modified():
            self._confirm_save_async(tab, really_close)
        else:
            really_close()

    def action_close_window(self, *_args: object) -> None:
        self.close()

    def action_next_tab(self, *_args: object) -> None:
        n = self.notebook.get_n_pages()
        if n > 1:
            self.notebook.set_current_page((self.notebook.get_current_page() + 1) % n)

    def action_prev_tab(self, *_args: object) -> None:
        n = self.notebook.get_n_pages()
        if n > 1:
            self.notebook.set_current_page((self.notebook.get_current_page() - 1) % n)

    def action_find(self, *_args: object) -> None:
        self._set_replace_visible(False)
        self._prefill_search_from_selection()
        self.search_bar.set_search_mode(True)
        self.search_entry.grab_focus()
        self.search_entry.select_region(0, -1)

    def action_replace(self, *_args: object) -> None:
        self._set_replace_visible(True)
        self._prefill_search_from_selection()
        self.search_bar.set_search_mode(True)
        self.search_entry.grab_focus()
        self.search_entry.select_region(0, -1)

    def _selected_text(self) -> str:
        tab = self.current_tab()
        if tab is None:
            return ""
        bounds = tab.buffer.get_selection_bounds()
        if not bounds:
            return ""
        start, end = bounds
        text = tab.buffer.get_text(start, end, False)
        if "\n" in text or len(text) > 256:
            return ""
        return text

    def _prefill_search_from_selection(self) -> None:
        sel = self._selected_text()
        if sel:
            self.search_entry.set_text(sel)

    def action_goto_line(self, *_args: object) -> None:
        tab = self.current_tab()
        if tab is None:
            return
        dialog = Gtk.Window(transient_for=self, modal=True, title="Go to Line")
        dialog.set_default_size(280, -1)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin_top=12,
                      margin_bottom=12, margin_start=12, margin_end=12)
        entry = Gtk.Entry()
        entry.set_input_purpose(Gtk.InputPurpose.DIGITS)
        entry.set_placeholder_text("Line number")
        box.append(entry)
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6, halign=Gtk.Align.END)
        cancel = Gtk.Button(label="Cancel")
        ok = Gtk.Button(label="Go")
        ok.add_css_class("suggested-action")
        btn_box.append(cancel)
        btn_box.append(ok)
        box.append(btn_box)
        dialog.set_child(box)

        def go(*_args: object) -> None:
            try:
                line = int(entry.get_text()) - 1
            except ValueError:
                dialog.close()
                return
            line = max(0, min(line, tab.buffer.get_line_count() - 1))
            ok_iter, it = tab.buffer.get_iter_at_line(line)
            tab.buffer.place_cursor(it)
            tab.view.scroll_to_iter(it, 0.1, True, 0.5, 0.5)
            tab.view.grab_focus()
            dialog.close()

        ok.connect("clicked", go)
        entry.connect("activate", go)
        cancel.connect("clicked", lambda *_: dialog.close())
        dialog.present()

    def action_format(self, *_args: object) -> None:
        from . import formatters

        tab = self.current_tab()
        if tab is None:
            return
        lang = tab.buffer.get_language()
        lang_id = lang.get_id() if lang is not None else None
        if not formatters.supports(lang_id):
            # Nothing owns this file type, so fall back to the whitespace pass
            # rather than leaving Ctrl+Shift+I doing nothing at all. Formatting
            # must stay predictable, so this route never re-joins wrapped lines.
            self._normalize_scope(unwrap_selection=False)
            return
        text = tab.buffer.get_full_text()
        filename = str(tab.buffer.path) if tab.buffer.path else f"buffer.{lang_id}"
        work_dir = None
        if tab.buffer.path is not None and tab.buffer.path.parent.is_dir():
            work_dir = str(tab.buffer.path.parent)
        try:
            formatted = formatters.format_text(lang_id, text, filename=filename, cwd=work_dir)
        except formatters.FormatError as e:
            self._set_status(str(e))
            return
        if formatted == text:
            self._set_status("Already formatted")
            return
        tab.buffer.replace_text_preserving_cursor(formatted)
        self._set_status(f"Formatted ({lang_id})")

    def action_normalize(self, *_args: object) -> None:
        """Clean up whitespace — on the selection if there is one, else on the
        whole file. Re-joining hard-wrapped lines is the one lossy step, so it
        happens only on a selection, where the user picked the scope."""
        self._normalize_scope(unwrap_selection=True)

    def _normalize_scope(self, *, unwrap_selection: bool) -> None:
        from . import normalize

        tab = self.current_tab()
        if tab is None:
            return
        bounds = tab.buffer.get_selection_bounds()
        if bounds:
            start, end = bounds
            text = tab.buffer.get_text(start, end, False)
            # Re-joining lines is only safe where a line break is decoration.
            # In source code a long statement would be glued to the next one.
            lang = tab.buffer.get_language()
            unwrap = unwrap_selection and normalize.may_unwrap(
                lang.get_id() if lang is not None else None
            )
            cleaned = normalize.normalize_text(
                text,
                tab_width=self.settings.tab_width,
                use_spaces=self.settings.use_spaces,
                unwrap=unwrap,
                ensure_final_newline=False,
            )
            if cleaned == text:
                self._set_status(_("Whitespace already normalized"))
                return
            tab.buffer.replace_selection(cleaned)
            self._set_status(_("Normalized selection"))
            return

        text = tab.buffer.get_full_text()
        cleaned = normalize.normalize_text(
            text,
            tab_width=self.settings.tab_width,
            use_spaces=self.settings.use_spaces,
        )
        if cleaned == text:
            self._set_status(_("Whitespace already normalized"))
            return
        tab.buffer.replace_text_preserving_cursor(cleaned)
        self._set_status(_("Normalized whitespace"))

    def action_open_backups(self, *_args: object) -> None:
        from . import backups

        directory = backups.backups_dir()
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            self._alert(_("Cannot open backups"), f"{directory}: {e}")
            return
        launcher = Gtk.FileLauncher.new(Gio.File.new_for_path(str(directory)))
        launcher.launch(self, None, lambda *_: None)

    def action_toggle_wrap(self, *_args: object) -> None:
        self.settings.wrap_lines = not self.settings.wrap_lines
        self.settings.save()
        app = self.get_application()
        if app is not None and hasattr(app, "broadcast_settings"):
            app.broadcast_settings(self.settings)
        else:
            for tab in self.all_tabs():
                tab._apply_settings(self.settings)

    def action_toggle_line_numbers(self, *_args: object) -> None:
        tab = self.current_tab()
        if tab is None:
            return
        tab.view.set_show_line_numbers(not tab.view.get_show_line_numbers())

    def action_toggle_minimap(self, *_args: object) -> None:
        self.settings.show_minimap = not self.settings.show_minimap
        self.settings.save()
        app = self.get_application()
        if app is not None and hasattr(app, "broadcast_settings"):
            app.broadcast_settings(self.settings)
        else:
            for tab in self.all_tabs():
                tab._apply_settings(self.settings)

    def _effective_dark(self) -> bool:
        """Is the UI dark right now? Resolves `auto` to what's actually applied."""
        mode = self.settings.dark_ui if isinstance(self.settings.dark_ui, str) else "auto"
        if mode in ("light", "dark"):
            return mode == "dark"
        gtk_settings = Gtk.Settings.get_default()
        if gtk_settings is not None:
            return bool(gtk_settings.get_property("gtk-application-prefer-dark-theme"))
        return theming.is_dark_scheme(self.settings.color_scheme, {})

    def action_toggle_dark(self, *_args: object) -> None:
        """Flip the whole app between light and dark in one step.

        Two states, not a three-way cycle: `auto` remains a Preferences
        choice, but toggling from it lands on the opposite of what is on
        screen instead of costing a second press. The UI theme and the
        editor colour scheme always move together.
        """
        variants, available = theming.collect_scheme_variants()
        dark_ui, scheme = theming.next_theme(
            self.settings.color_scheme,
            currently_dark=self._effective_dark(),
            variants=variants,
            available=available,
        )
        self.settings.dark_ui = dark_ui
        self.settings.color_scheme = scheme
        self.settings.save()
        app = self.get_application()
        if app and hasattr(app, "broadcast_settings"):
            app.broadcast_settings(self.settings)
        else:
            self.apply_settings(self.settings)
        self._set_status(_("Theme: dark") if dark_ui == "dark" else _("Theme: light"))

    def action_open_project(self, *_args: object) -> None:
        dialog = Gtk.FileDialog.new()
        dialog.set_title("Open Project")
        if self.settings.last_project:
            initial = Gio.File.new_for_path(self.settings.last_project)
            if initial.query_exists(None):
                dialog.set_initial_folder(initial)
        dialog.select_folder(self, None, self._on_open_project_response)

    def _on_open_project_response(self, dialog: Gtk.FileDialog, result) -> None:
        try:
            folder = dialog.select_folder_finish(result)
        except GLib.GError:
            return
        if not folder:
            return
        path = Path(folder.get_path())
        self.sidebar.add_project(path)
        self._persist_projects()
        if not self.settings.show_sidebar:
            self.settings.show_sidebar = True
            self._apply_sidebar_visibility()
        self.settings.save()
        app = self.get_application()
        if app and hasattr(app, "broadcast_settings"):
            app.broadcast_settings(self.settings)

    def _persist_projects(self) -> None:
        self.settings.projects = [str(p) for p in self.sidebar.projects()]
        if self.settings.projects:
            self.settings.last_project = self.settings.projects[-1]

    def action_toggle_sidebar(self, *_args: object) -> None:
        self.settings.show_sidebar = not self.settings.show_sidebar
        self.settings.save()
        app = self.get_application()
        if app and hasattr(app, "broadcast_settings"):
            app.broadcast_settings(self.settings)
        else:
            self._apply_sidebar_visibility()

    def action_toggle_terminal(self, *_args: object) -> None:
        self._init_deferred()
        if self.terminal_panel is None:
            self._set_status("Terminal unavailable in this build")
            return
        self.settings.show_terminal = not self.settings.show_terminal
        self.settings.save()
        app = self.get_application()
        if app and hasattr(app, "broadcast_settings"):
            app.broadcast_settings(self.settings)
        else:
            self._apply_terminal_visibility()

    def action_new_terminal(self, *_args: object) -> None:
        self._init_deferred()
        if self.terminal_panel is None:
            self._set_status("Terminal unavailable in this build")
            return
        if not self.settings.show_terminal:
            self.settings.show_terminal = True
            self.settings.save()
            self._apply_terminal_visibility()
        self.terminal_panel.add_terminal(self.settings.last_project or None)

    def action_toggle_preview(self, *_args: object) -> None:
        tab = self.current_tab()
        if tab is None:
            return
        from .markdown_preview import AVAILABLE

        if not AVAILABLE:
            self._set_status(_("Markdown preview unavailable in this build"))
            return
        tab.set_preview_visible(not tab.preview_visible)

    def _is_markdown_tab(self, tab: "EditorTab") -> bool:
        from .markdown_preview import is_markdown_path

        if is_markdown_path(tab.buffer.path):
            return True
        lang = tab.buffer.get_language()
        return lang is not None and lang.get_id() == "markdown"

    def _maybe_auto_preview(self, tab: "EditorTab") -> None:
        if not self.settings.markdown_preview_auto:
            return
        if tab.preview_visible:
            return
        from .markdown_preview import AVAILABLE

        if not AVAILABLE:
            return
        if self._is_markdown_tab(tab):
            tab.set_preview_visible(True)

    # ---------- Sidebar context actions ----------

    def _dispatch_sidebar_action(self, action_id: str, path: Path) -> None:
        handlers = {
            "new-file": self.action_sidebar_new_file,
            "new-folder": self.action_sidebar_new_folder,
            "rename": self.action_sidebar_rename,
            "find": self.action_sidebar_find,
            "replace": self.action_sidebar_replace,
            "replace-with": self.action_sidebar_replace_with,
        }
        handler = handlers.get(action_id)
        if handler is not None:
            handler()

    def _sidebar_target_dir(self) -> Path | None:
        path = self.sidebar.get_context_path()
        if path is None:
            tab = self.current_tab()
            if tab is not None and tab.buffer.path is not None:
                return tab.buffer.path.parent
            return None
        if path.is_dir():
            return path
        return path.parent

    def _sidebar_target_path(self) -> Path | None:
        path = self.sidebar.get_context_path()
        if path is not None:
            return path
        tab = self.current_tab()
        if tab is not None and tab.buffer.path is not None:
            return tab.buffer.path
        projects = self.sidebar.projects()
        return projects[-1] if projects else None

    def action_sidebar_new_file(self, *_args: object) -> None:
        target_dir = self._sidebar_target_dir()
        if target_dir is None:
            self._set_status(_("Open a project first to create files"))
            return
        self._prompt_string(
            _("New File"),
            _("File name in {dir}:").format(dir=target_dir.name or str(target_dir)),
            "",
            lambda name: self._create_file_in(target_dir, name),
        )
        self.sidebar.clear_context_path()

    def action_sidebar_new_folder(self, *_args: object) -> None:
        target_dir = self._sidebar_target_dir()
        if target_dir is None:
            self._set_status(_("Open a project first to create folders"))
            return
        self._prompt_string(
            _("New Folder"),
            _("Folder name in {dir}:").format(dir=target_dir.name or str(target_dir)),
            "",
            lambda name: self._create_folder_in(target_dir, name),
        )
        self.sidebar.clear_context_path()

    def action_sidebar_rename(self, *_args: object) -> None:
        target = self._sidebar_target_path()
        if target is None:
            self._set_status(_("Select a file or folder to rename"))
            return
        if not target.exists():
            self._alert(_("Cannot rename"), _("{path} no longer exists.").format(path=target))
            return
        self._prompt_string(
            _("Rename"),
            _("New name for {name}:").format(name=target.name),
            target.name,
            lambda new_name: self._rename_path(target, new_name),
        )
        self.sidebar.clear_context_path()

    def _rename_path(self, source: Path, new_name: str) -> None:
        new_name = new_name.strip()
        if not new_name or new_name == source.name:
            return
        if file_io.invalid_name_reason(new_name) is not None:
            self._alert(_("Invalid name"), _("Name cannot contain '/'."))
            return
        target = source.parent / new_name
        if target.exists() and not self._same_file(source, target):
            self._alert(_("Already exists"), str(target))
            return
        try:
            source.rename(target)
        except OSError as e:
            self._alert(_("Cannot rename"), f"{source} → {target}: {e}")
            return
        self._retarget_open_buffers(source, target)
        self._retarget_projects(source, target)
        self._set_status(
            _("Renamed {old} to {new}").format(old=source.name, new=new_name)
        )

    @staticmethod
    def _same_file(source: Path, target: Path) -> bool:
        """Same inode? On a case-insensitive mount README.md and readme.md
        are one file, and renaming between them must not be refused as a
        collision with itself."""
        try:
            return source.samefile(target)
        except OSError:
            return False

    def _retarget_open_buffers(self, source: Path, target: Path) -> None:
        """Point every open tab at the renamed file — in all windows."""
        app = self.get_application()
        windows = list(app.get_windows()) if app is not None else [self]
        for window in windows:
            if not hasattr(window, "all_tabs"):
                continue
            for tab in window.all_tabs():
                path = tab.buffer.path
                if path is None:
                    continue
                moved = file_io.rewritten_path(path, source, target)
                if moved is None:
                    continue
                tab.buffer.path = moved
                # An extension change means a different language, and the
                # markdown auto-preview hangs off the same path notify.
                tab.buffer.detect_language()

    def _retarget_projects(self, source: Path, target: Path) -> None:
        """Rebuild the tree, following any project root that just moved."""
        projects = self.sidebar.projects()
        moved = [file_io.rewritten_path(p, source, target) or p for p in projects]
        if moved == projects:
            # Same parent folder for both ends of a rename, so one re-list of
            # it is enough — and it leaves every other folder expanded.
            self._refresh_sidebar(source.parent)
            return
        self.sidebar.set_projects(moved, list(self.settings.ignore_patterns))
        self._persist_projects()
        self.settings.save()
        app = self.get_application()
        if app and hasattr(app, "broadcast_settings"):
            app.broadcast_settings(self.settings)

    def _create_file_in(self, parent: Path, name: str) -> None:
        name = name.strip()
        if not name:
            return
        if "/" in name or name in (".", ".."):
            self._alert(_("Invalid name"), _("File name cannot contain '/'."))
            return
        target = parent / name
        try:
            if target.exists():
                self._alert(_("Already exists"), str(target))
                return
            target.parent.mkdir(parents=True, exist_ok=True)
            target.touch()
        except OSError as e:
            self._alert(_("Cannot create file"), f"{target}: {e}")
            return
        self._refresh_sidebar(parent)
        self.open_path(target)
        self._set_status(_("Created {name}").format(name=name))

    def _create_folder_in(self, parent: Path, name: str) -> None:
        name = name.strip()
        if not name:
            return
        if name in (".", ".."):
            self._alert(_("Invalid name"), name)
            return
        target = parent / name
        try:
            if target.exists():
                self._alert(_("Already exists"), str(target))
                return
            target.mkdir(parents=True)
        except OSError as e:
            self._alert(_("Cannot create folder"), f"{target}: {e}")
            return
        self._refresh_sidebar(parent)
        self._set_status(_("Created {name}/").format(name=name))

    def _refresh_sidebar(self, directory: Path | None = None) -> None:
        """Re-read the tree. With `directory`, only that folder is re-listed,
        in place, so the rest of the tree keeps the expansion the user set up.
        Without it, every project is rebuilt — which does collapse the tree,
        so pass a directory whenever you know which one changed."""
        if directory is not None:
            self.sidebar.refresh_dir(directory)
            return
        self.sidebar.set_projects(
            self.sidebar.projects(), list(self.settings.ignore_patterns),
        )

    def action_sidebar_find(self, *_args: object) -> None:
        self._open_find_at_path(with_replace=False)

    def action_sidebar_replace(self, *_args: object) -> None:
        self._open_find_at_path(with_replace=True)

    def action_sidebar_replace_with(self, *_args: object) -> None:
        self._open_find_at_path(with_replace=True, focus_replace=True)

    def _open_find_at_path(
        self, *, with_replace: bool, focus_replace: bool = False,
    ) -> None:
        from .find_in_files import FindInFilesDialog

        path = self._sidebar_target_path()
        if path is None:
            self._set_status(_("Find/Replace needs an open project or file"))
            return
        scope = path.name or str(path)
        if path.is_dir():
            scope = f"{scope}/"

        def on_chosen(file_path: Path, line: int) -> None:
            self.open_path(file_path)
            tab = self.current_tab()
            if tab is not None and line > 0:
                target = tab.buffer.get_iter_at_line(max(0, line - 1))[1]
                tab.buffer.place_cursor(target)
                tab.view.scroll_to_iter(target, 0.2, True, 0.0, 0.5)
                tab.view.grab_focus()

        dialog = FindInFilesDialog(
            self, [path], list(self.settings.ignore_patterns), on_chosen,
            with_replace=with_replace, scope_label=scope,
            initial_query=self._selected_text(),
        )
        dialog.present()
        if focus_replace:
            dialog.focus_replace_entry()
        self.sidebar.clear_context_path()

    def _prompt_string(
        self, title: str, label: str, initial: str, on_ok: Callable[[str], None],
    ) -> None:
        dialog = Gtk.Window(transient_for=self, modal=True, title=title)
        dialog.set_destroy_with_parent(True)
        dialog.set_resizable(False)
        dialog.set_default_size(360, 140)
        box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=10,
            margin_top=14, margin_bottom=14, margin_start=14, margin_end=14,
        )
        lbl = Gtk.Label(label=label, xalign=0)
        lbl.set_wrap(True)
        box.append(lbl)
        entry = Gtk.Entry()
        entry.set_text(initial)
        box.append(entry)
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6, halign=Gtk.Align.END)
        cancel = Gtk.Button(label=_("Cancel"))
        ok = Gtk.Button(label=_("OK"))
        ok.add_css_class("suggested-action")
        btn_box.append(cancel)
        btn_box.append(ok)
        box.append(btn_box)
        dialog.set_child(box)

        def commit(*_args: object) -> None:
            value = entry.get_text()
            dialog.close()
            on_ok(value)

        ok.connect("clicked", commit)
        entry.connect("activate", commit)
        cancel.connect("clicked", lambda *_: dialog.close())
        dialog.present()
        entry.grab_focus()

    def action_shortcuts(self, *_args: object) -> None:
        from . import shortcuts_window

        shortcuts_window.present(self)

    # Commands surfaced in the palette: (label, detailed-action-name).
    _PALETTE_COMMANDS: list[tuple[str, str]] = [
        (_("New Tab"), "win.new-tab"),
        (_("New Window"), "win.new-window"),
        (_("Open File…"), "win.open"),
        (_("Open Project…"), "win.open-project"),
        (_("Save"), "win.save"),
        (_("Save As…"), "win.save-as"),
        (_("Close Tab"), "win.close-tab"),
        (_("Quick Open…"), "win.quick-open"),
        (_("Find…"), "win.find"),
        (_("Find in Files…"), "win.find-in-files"),
        (_("Replace…"), "win.replace"),
        (_("Go to Line…"), "win.goto-line"),
        (_("Go to Symbol…"), "win.symbols"),
        (_("Format Code"), "win.format"),
        (_("Normalize Whitespace"), "win.normalize"),
        (_("Open Backups Folder"), "win.open-backups"),
        (_("Toggle Sidebar"), "win.toggle-sidebar"),
        (_("Toggle Terminal"), "win.toggle-terminal"),
        (_("New Terminal"), "win.new-terminal"),
        (_("Toggle Markdown Preview"), "win.toggle-preview"),
        (_("Toggle Word Wrap"), "win.toggle-wrap"),
        (_("Toggle Line Numbers"), "win.toggle-line-numbers"),
        (_("Toggle Minimap"), "win.toggle-minimap"),
        (_("Toggle Dark Mode"), "win.toggle-dark"),
        (_("Preferences…"), "win.preferences"),
        (_("Keyboard Shortcuts"), "win.shortcuts"),
        (_("About Apedi"), "app.about"),
        (_("Quit"), "app.quit"),
    ]

    def _accel_label_for(self, action_name: str) -> str:
        app = self.get_application()
        if app is None:
            return ""
        accels = app.get_accels_for_action(action_name)
        if not accels:
            return ""
        ok, keyval, mods = Gtk.accelerator_parse(accels[0])
        if not ok:
            return ""
        return Gtk.accelerator_get_label(keyval, mods)

    def action_command_palette(self, *_args: object) -> None:
        from .command_palette import CommandPalette

        commands = [
            (label, action, self._accel_label_for(action))
            for label, action in self._PALETTE_COMMANDS
        ]

        def on_chosen(action_name: str) -> None:
            # activate_action resolves the win./app. prefix through the muxer.
            self.activate_action(action_name, None)

        CommandPalette(self, commands, on_chosen).present()

    def action_quick_open(self, *_args: object) -> None:
        from .quick_open import QuickOpenDialog

        self._init_deferred()
        projects = self.sidebar.projects() or self._fallback_search_roots()
        if not projects:
            self._set_status(_("Quick Open needs an open project (Ctrl+Shift+O) or an open file"))
            return

        def on_chosen(path: Path) -> None:
            self.open_path(path)

        QuickOpenDialog(self, projects, list(self.settings.ignore_patterns), on_chosen).present()

    def _fallback_search_roots(self) -> list[Path]:
        """When no project is open, derive search roots from open tabs' parents."""
        seen: list[Path] = []
        for tab in self.all_tabs():
            if not tab.buffer.path:
                continue
            parent = tab.buffer.path.parent
            if parent.is_dir() and parent not in seen:
                seen.append(parent)
        return seen

    def action_find_in_files(self, *_args: object) -> None:
        from .find_in_files import FindInFilesDialog

        self._init_deferred()
        all_projects = self.sidebar.projects() or self._fallback_search_roots()
        if not all_projects:
            self._set_status(_("Find in Files needs an open project or an open file"))
            return

        initial_projects: list[Path] = list(all_projects)
        context = self.sidebar.get_context_path()
        if context is not None:
            proj = self.sidebar.project_for(context)
            if proj is None and context in all_projects:
                proj = context
            if proj is not None:
                initial_projects = [proj]

        def on_chosen(path: Path, line: int) -> None:
            self.open_path(path)
            tab = self.current_tab()
            if tab is not None and line > 0:
                target = tab.buffer.get_iter_at_line(max(0, line - 1))[1]
                tab.buffer.place_cursor(target)
                tab.view.scroll_to_iter(target, 0.2, True, 0.0, 0.5)
                tab.view.grab_focus()

        FindInFilesDialog(
            self, initial_projects, list(self.settings.ignore_patterns), on_chosen,
            initial_query=self._selected_text(),
            all_projects=list(all_projects),
        ).present()

    def action_symbols(self, *_args: object) -> None:
        from .symbols import SymbolPaletteDialog, extract_symbols

        tab = self.current_tab()
        if tab is None:
            return
        lang = tab.buffer.get_language()
        lang_id = lang.get_id() if lang else None
        text = tab.buffer.get_full_text()
        syms = extract_symbols(lang_id, text)
        if not syms:
            self._set_status(f"No symbols extracted for {lang_id or 'plain text'}")
            return

        def on_chosen(sym) -> None:
            line_iter = tab.buffer.get_iter_at_line(max(0, sym.line - 1))[1]
            tab.buffer.place_cursor(line_iter)
            tab.view.scroll_to_iter(line_iter, 0.2, True, 0.0, 0.5)
            tab.view.grab_focus()

        SymbolPaletteDialog(self, syms, on_chosen).present()

    def action_preferences(self, *_args: object) -> None:
        from .preferences import PreferencesDialog

        app = self.get_application()

        def on_changed(s: Settings) -> None:
            if app and hasattr(app, "broadcast_settings"):
                app.broadcast_settings(s)
            else:
                self.apply_settings(s)

        dialog = PreferencesDialog(self, self.settings, on_changed)
        dialog.present()

    def apply_settings(self, settings: Settings) -> None:
        self.settings = settings
        for tab in self.all_tabs():
            tab._apply_settings(settings)
        self._apply_sidebar_visibility()
        self._apply_terminal_visibility()
        self._cancel_autosave()
        self._update_status()

    def _autosave_bump(self) -> None:
        if self.settings.autosave != "delay":
            return
        self._cancel_autosave()
        delay = max(250, int(self.settings.autosave_delay_ms))
        self._autosave_timer_id = GLib.timeout_add(delay, self._autosave_fire)

    def _cancel_autosave(self) -> None:
        if self._autosave_timer_id is not None:
            GLib.source_remove(self._autosave_timer_id)
            self._autosave_timer_id = None

    def _autosave_fire(self) -> bool:
        self._autosave_timer_id = None
        self._autosave_now()
        return False  # one-shot

    def _autosave_now(self) -> None:
        for tab in self.all_tabs():
            if tab.buffer.path and tab.buffer.get_modified():
                self._do_save(tab, tab.buffer.path)

    def _on_active_changed(self, *_args: object) -> None:
        if self.settings.autosave == "focus" and not self.is_active():
            self._autosave_now()

    def _draft_bump(self, tab: EditorTab) -> None:
        if not tab.buffer.path or not tab.buffer.get_modified():
            return
        from . import recovery
        recovery.save(
            tab.buffer.path, tab.buffer.get_full_text(),
            tab.buffer.encoding, tab.buffer.mtime_at_load,
        )

    def _on_buffer_external_change(self, path: Path) -> None:
        for tab in self.all_tabs():
            if tab.buffer.path != path:
                continue
            if tab.buffer.get_modified():
                self._prompt_conflicting_reload(tab, path)
            else:
                self._set_status(_("{name} changed on disk — reloading").format(name=path.name))
                self._reload_from_disk(tab, path)
            return

    def _prompt_conflicting_reload(self, tab: EditorTab, path: Path) -> None:
        """The file moved under a tab that still has unsaved edits.

        The backup is written before the question is even asked, so whichever
        way the user answers — and however the dialog is dismissed — the local
        version is already safe on disk.
        """
        from . import backups

        if getattr(tab, "_conflict_prompt_open", False):
            # A tool rewriting the file in a burst emits several change events;
            # one question per tab is enough until it is answered.
            return
        tab._conflict_prompt_open = True

        copy = backups.save_copy(
            path, tab.buffer.get_full_text(), tab.buffer.encoding,
        )
        where = (
            _("Your unsaved version was backed up to {copy}.").format(copy=copy)
            if copy is not None
            else _("Backing up your unsaved version failed — reloading would lose it.")
        )

        def cont(reload_it: bool) -> None:
            tab._conflict_prompt_open = False
            if reload_it:
                self._reload_from_disk(tab, path)
            elif copy is not None:
                self._set_status(_("Kept your version — backup at {copy}").format(copy=copy))
            else:
                self._set_status(_("Kept your version"))

        self._confirm_async(
            _("{name} changed on disk").format(name=path.name),
            _("You have unsaved edits in this tab. {where}").format(where=where),
            cont,
            confirm_label=_("Reload from disk"),
            cancel_label=_("Keep my version"),
        )

    def _reload_from_disk(self, tab: EditorTab, path: Path) -> None:
        try:
            loaded = file_io.load_file(path)
        except (OSError, file_io.BinaryFileError, file_io.FileTooLargeError) as e:
            self._set_status(_("Cannot reload {name}: {error}").format(
                name=path.name, error=e,
            ))
            return
        tab.buffer.load(loaded.text, path, loaded.encoding, loaded.mtime)
        from . import recovery
        recovery.discard(path)
        self._set_status(_("Reloaded {name} from disk").format(name=path.name))

    # ---------- Search ----------

    def _on_search_changed(self, entry: Gtk.SearchEntry) -> None:
        tab = self.current_tab()
        if tab is None:
            return
        tab.search_settings.set_search_text(entry.get_text())

    def _search_jump(self, forward: bool) -> None:
        tab = self.current_tab()
        if tab is None:
            return
        cursor = tab.buffer.get_iter_at_mark(tab.buffer.get_insert())
        if forward:
            tab.search_context.forward_async(cursor, None, self._on_search_done, tab)
        else:
            tab.search_context.backward_async(cursor, None, self._on_search_done, tab)

    def _on_search_done(self, ctx: GtkSource.SearchContext, result: Gio.AsyncResult, tab: EditorTab) -> None:
        try:
            found, start, end, _wrapped = ctx.forward_finish(result)
        except GLib.Error:
            try:
                found, start, end, _wrapped = ctx.backward_finish(result)
            except GLib.Error:
                return
        if found:
            tab.buffer.select_range(start, end)
            tab.view.scroll_to_iter(start, 0.1, True, 0.5, 0.5)

    def _replace_one(self) -> None:
        tab = self.current_tab()
        if tab is None:
            return
        bounds = tab.buffer.get_selection_bounds()
        if not bounds:
            self._search_jump(forward=True)
            return
        start, end = bounds
        try:
            tab.search_context.replace(start, end, self.replace_entry.get_text(), -1)
        except GLib.Error as e:
            self._set_status(f"Replace failed: {e.message}")
            return
        self._search_jump(forward=True)

    def _replace_all(self) -> None:
        tab = self.current_tab()
        if tab is None:
            return
        try:
            count = tab.search_context.replace_all(self.replace_entry.get_text(), -1)
        except GLib.Error as e:
            self._set_status(f"Replace failed: {e.message}")
            return
        self._set_status(f"Replaced {count} occurrence(s)")

    # ---------- Drag & drop ----------

    def _setup_drop_target(self) -> None:
        target = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
        target.connect("drop", self._on_drop)
        self.add_controller(target)

    def _on_drop(self, _target: Gtk.DropTarget, value: object, _x: float, _y: float) -> bool:
        if isinstance(value, Gdk.FileList):
            for f in value.get_files():
                p = Path(f.get_path())
                if p.is_file():
                    self.open_path(p)
            return True
        return False

    # ---------- Status bar ----------

    def _set_status(self, message: str) -> None:
        self.status_bar.pop(self.status_ctx)
        self.status_bar.push(self.status_ctx, message)
        # Cursor / language indicators are pushed last in _update_status
        GLib.timeout_add_seconds(3, self._update_status)

    def _update_status(self) -> bool:
        tab = self.current_tab()
        if tab is None:
            self.status_bar.pop(self.status_ctx)
            return False
        cursor = tab.buffer.get_iter_at_mark(tab.buffer.get_insert())
        line = cursor.get_line() + 1
        col = cursor.get_line_offset() + 1
        lang = tab.buffer.get_language()
        lang_name = lang.get_name() if lang else "Plain"
        indent = "Spaces" if self.settings.use_spaces else "Tabs"
        msg = f"Ln {line}, Col {col}  ·  {lang_name}  ·  {indent}: {self.settings.tab_width}  ·  {tab.buffer.encoding}"
        self.status_bar.pop(self.status_ctx)
        self.status_bar.push(self.status_ctx, msg)
        return False

    def _on_switch_page(self, _nb: Gtk.Notebook, page: Gtk.Widget, _idx: int) -> None:
        GLib.idle_add(self._update_status)
        if isinstance(page, EditorTab) and page.buffer.path:
            self.sidebar.reveal_file(page.buffer.path)

    # ---------- Close request / dirty guard ----------

    def _flush_split_ratio_save(self) -> None:
        """Write a just-dragged split now instead of losing it to the debounce."""
        if self._split_save_timer_id is None:
            return
        GLib.source_remove(self._split_save_timer_id)
        self._split_save_timer_id = None
        self.settings.save()

    def _on_close_request(self, _win: Gtk.Window) -> bool:
        self._flush_split_ratio_save()
        # Snapshot the layout before any tab is torn down by the save prompts.
        self._pending_session_state = (
            self._session_state() if self.settings.restore_session else None
        )
        dirty = [t for t in self.all_tabs() if t.buffer.get_modified()]
        if not dirty:
            self._remember_session()
            return False
        self._prompt_close_chain(dirty, 0)
        return True  # block close, will re-call destroy when done

    def _session_state(self) -> dict:
        """Serialize this window's open files + cursor for session restore."""
        tabs: list[dict] = []
        for tab in self.all_tabs():
            path = tab.buffer.path
            if path is None:
                continue  # scratch buffers are handled by recovery drafts
            ins = tab.buffer.get_iter_at_mark(tab.buffer.get_insert())
            tabs.append({"path": str(path), "cursor": ins.get_offset()})
        return {"tabs": tabs, "active": self.notebook.get_current_page()}

    def _remember_session(self) -> None:
        state = getattr(self, "_pending_session_state", None)
        if state is None:
            return
        app = self.get_application()
        if app is not None and hasattr(app, "remember_window"):
            app.remember_window(state)
        self._pending_session_state = None

    def _prompt_close_chain(self, tabs: list[EditorTab], idx: int) -> None:
        if idx >= len(tabs):
            self._remember_session()
            self.destroy()
            return
        tab = tabs[idx]
        self.notebook.set_current_page(self.notebook.page_num(tab))
        self._confirm_save_async(tab, lambda: self._prompt_close_chain(tabs, idx + 1))

    def _confirm_save_async(self, tab: EditorTab, on_done: callable) -> None:
        dialog = Gtk.AlertDialog()
        dialog.set_message(f"Save changes to {tab.buffer.display_name()}?")
        dialog.set_buttons(["Cancel", "Discard", "Save"])
        dialog.set_default_button(2)
        dialog.set_cancel_button(0)

        def on_response(dlg: Gtk.AlertDialog, result: Gio.AsyncResult) -> None:
            try:
                button = dlg.choose_finish(result)
            except GLib.Error:
                return
            if button == 0:
                return  # cancel
            if button == 1:
                tab.buffer.set_modified(False)
                on_done()
                return
            if button == 2:
                if tab.buffer.path is None:
                    self.action_save_as()
                    return
                self._save_to(tab, tab.buffer.path)
                if not tab.buffer.get_modified():
                    on_done()

        dialog.choose(self, None, on_response)

    def _confirm_async(
        self,
        title: str,
        body: str,
        callback: callable,
        confirm_label: str = "OK",
        cancel_label: str = "Cancel",
    ) -> None:
        dialog = Gtk.AlertDialog()
        dialog.set_message(title)
        dialog.set_detail(body)
        dialog.set_buttons([cancel_label, confirm_label])
        dialog.set_default_button(1)
        dialog.set_cancel_button(0)

        def on_response(dlg: Gtk.AlertDialog, result: Gio.AsyncResult) -> None:
            try:
                button = dlg.choose_finish(result)
            except GLib.Error:
                callback(False)
                return
            callback(button == 1)

        dialog.choose(self, None, on_response)

    def _alert(self, title: str, body: str) -> None:
        dialog = Gtk.AlertDialog()
        dialog.set_message(title)
        dialog.set_detail(body)
        dialog.set_buttons(["OK"])
        dialog.show(self)
