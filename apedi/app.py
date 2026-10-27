"""EditorApp — Gtk.Application lifecycle and CLI handling."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("GtkSource", "5")
from gi.repository import Gio, GLib, Gtk  # noqa: E402

from . import APP_ID, __version__, i18n, recent
from .settings import Settings
from .shortcuts import SHORTCUTS

_INITIAL_SETTINGS = Settings.load()
i18n.configure_locale()
i18n.install(_INITIAL_SETTINGS.language)

log = logging.getLogger(__name__)


class EditorApp(Gtk.Application):
    def __init__(self) -> None:
        super().__init__(
            application_id=APP_ID,
            flags=Gio.ApplicationFlags.HANDLES_OPEN | Gio.ApplicationFlags.HANDLES_COMMAND_LINE,
        )
        self.settings = _INITIAL_SETTINGS
        self._session_windows: list[dict] = []
        self._session_restored = False
        self._auto_theme_pending = False
        self.add_main_option(
            "new-window", ord("n"), GLib.OptionFlags.NONE, GLib.OptionArg.NONE,
            "Open in a new window", None,
        )
        self.add_main_option(
            GLib.OPTION_REMAINING, 0, GLib.OptionFlags.NONE, GLib.OptionArg.STRING_ARRAY,
            "Files to open", "FILE…",
        )

    def do_startup(self) -> None:
        Gtk.Application.do_startup(self)
        from . import style as _style

        _style.install()
        self._install_snippet_path()
        self._apply_theme(self.settings.dark_ui)
        quit_action = Gio.SimpleAction.new("quit", None)
        quit_action.connect("activate", lambda *_: self.quit())
        self.add_action(quit_action)

        open_recent = Gio.SimpleAction.new("open-recent", GLib.VariantType.new("s"))
        open_recent.connect("activate", self._on_open_recent)
        self.add_action(open_recent)

        about = Gio.SimpleAction.new("about", None)
        about.connect("activate", self._on_about)
        self.add_action(about)

        whats_new = Gio.SimpleAction.new("whats-new", None)
        whats_new.connect("activate", self._on_whats_new)
        self.add_action(whats_new)

        support = Gio.SimpleAction.new("support", GLib.VariantType.new("s"))
        support.connect("activate", self._on_support)
        self.add_action(support)

        self.recent_menu = Gio.Menu()
        # Build the menu from the small JSON file now, but leave filesystem
        # existence checks until after the first frame.  Stale entries are
        # harmless for the few milliseconds before validation.
        self._rebuild_recent_menu(check_existing=False)

        for action_name, accels in SHORTCUTS:
            self.set_accels_for_action(action_name, accels)

    def _rebuild_recent_menu(self, *, check_existing: bool = True) -> None:
        self.recent_menu.remove_all()
        paths = recent.load()
        if check_existing:
            paths = recent.filter_existing(paths)
        if not paths:
            self.recent_menu.append_item(Gio.MenuItem.new("(empty)", None))
            return
        for p in paths[:15]:
            item = Gio.MenuItem.new(p.name, None)
            item.set_action_and_target_value("app.open-recent", GLib.Variant.new_string(str(p)))
            self.recent_menu.append_item(item)

    def _on_open_recent(self, _action: Gio.SimpleAction, param: GLib.Variant) -> None:
        path = Path(param.get_string())
        win = self.get_active_window() or self.new_window()
        win.open_path(path)
        win.present()

    def _on_about(self, *_: object) -> None:
        from . import about

        win = self.get_active_window()
        if win is not None:
            about.present(win)

    def _on_whats_new(self, *_: object) -> None:
        from .whatsnew import WhatsNewDialog, section_for_version

        win = self.get_active_window()
        if win is None:
            return
        content = section_for_version(__version__) or _(
            "No release notes found for this version."
        )
        WhatsNewDialog(win, __version__, content).present()

    def _on_support(self, _action: Gio.SimpleAction, param: GLib.Variant) -> None:
        uri = param.get_string() if param else "https://ko-fi.com/aprus"
        win = self.get_active_window()
        try:
            launcher = Gtk.UriLauncher.new(uri)
            launcher.launch(win, None, None, None)
        except Exception:
            log.exception("UriLauncher failed; falling back to Gio.AppInfo")
            Gio.AppInfo.launch_default_for_uri(uri, None)

    def do_command_line(self, command_line: Gio.ApplicationCommandLine) -> int:
        options = command_line.get_options_dict().end().unpack()
        files = options.get(GLib.OPTION_REMAINING, []) or []
        force_new = bool(options.get("new-window"))
        cwd = Path(command_line.get_cwd() or ".")
        paths = [self._resolve(cwd, f) for f in files]

        created = force_new or not self.get_active_window()
        if created:
            window = self.new_window()
        else:
            window = self.get_active_window()

        if created:
            window.after_first_frame(
                lambda: self._populate_initial_window(window, paths)
            )
            window.present()
        else:
            self._populate_initial_window(window, paths)
            window.present()

        return 0

    def do_activate(self) -> None:
        win = self.get_active_window()
        if win is None:
            win = self.new_window()
            win.after_first_frame(lambda: self._populate_initial_window(win, []))
        else:
            self._populate_initial_window(win, [])
        win.present()

    def _populate_initial_window(self, window: EditorWindow, paths: list[Path]) -> bool:
        """Add useful content only after a newly-created window has painted."""
        if paths:
            window.open_path(paths[0])
            for path in paths[1:]:
                GLib.idle_add(
                    self._open_path_once, window, path,
                    priority=GLib.PRIORITY_LOW,
                )
        elif not self._maybe_restore_session(window) and not window.all_tabs():
            window.add_tab()
        window.schedule_deferred_init()
        GLib.timeout_add(500, self._maybe_show_whats_new, window)
        GLib.timeout_add(750, self._maybe_restore_drafts, window)
        if self._auto_theme_pending:
            GLib.timeout_add(1000, self._refresh_auto_theme)
        GLib.timeout_add(1250, self._apply_desktop_integration_after_startup)
        if not getattr(self, "_recent_validated", False):
            self._recent_validated = True
            GLib.timeout_add(250, self._validate_recent_after_startup)
        return False

    @staticmethod
    def _open_path_once(window: EditorWindow, path: Path) -> bool:
        window.open_path(path)
        return False

    def _validate_recent_after_startup(self) -> bool:
        self._rebuild_recent_menu()
        return False

    def _apply_desktop_integration_after_startup(self) -> bool:
        from . import desktop_integration

        desktop_integration.apply(self.settings.register_in_file_manager)
        return False

    def remember_window(self, state: dict) -> None:
        """Called by a window as it closes; persists the running session."""
        from . import session

        self._session_windows.append(state)
        if self.settings.restore_session:
            session.save(self._session_windows)

    def _maybe_restore_session(self, window: EditorWindow) -> bool:
        if self._session_restored:
            return False
        self._session_restored = True
        if not self.settings.restore_session:
            return False
        from . import session

        windows = session.load()
        if not windows:
            return False
        # First saved window fills the already-created one; the rest spawn.
        self._schedule_restore(window, windows[0])
        for extra in windows[1:]:
            w = self.new_window()
            w.after_first_frame(
                lambda w=w, extra=extra: self._schedule_restore(w, extra)
            )
            w.present()
        return True

    def _schedule_restore(self, window: EditorWindow, state: dict) -> None:
        # The active file is opened first; later files are interleaved with
        # GTK redraws at low priority.
        GLib.idle_add(
            self._restore_window, window, state, priority=GLib.PRIORITY_LOW
        )

    def _restore_window(self, window: EditorWindow, state: dict) -> bool:
        from . import session

        job = {
            "pending": session.ordered_tabs(state),
            "restored": [],
            "active_tab": None,
        }
        if not job["pending"]:
            window.add_tab()
            return False
        GLib.idle_add(
            self._restore_next_tab, window, state, job,
            priority=GLib.PRIORITY_LOW,
        )
        return False

    def _restore_next_tab(self, window: EditorWindow, state: dict, job: dict) -> bool:
        try:
            pending = job["pending"]
            if not pending:
                self._finish_restore(window, state, job)
                return False

            tabinfo = pending.pop(0)
            path = Path(tabinfo.get("path", ""))
            if path.is_file():
                group = tabinfo.get("group", 0)
                group = group if isinstance(group, int) and group in (0, 1) else 0
                window.use_group(group)
                activate = job["active_tab"] is None
                if window.open_path(
                    path, here=True, add_to_recent=False, activate=activate,
                    auto_preview=False, initialize_extras=False,
                ):
                    tab = next(
                        (candidate for candidate in window._tabs_in(window.notebook)
                         if candidate.buffer.path == path),
                        None,
                    )
                    if tab is not None:
                        job["restored"].append((tabinfo, tab))
                        if job["active_tab"] is None:
                            job["active_tab"] = tab
                        cursor = tabinfo.get("cursor")
                        if isinstance(cursor, int):
                            buf = tab.buffer
                            n = buf.get_char_count()
                            it = buf.get_iter_at_offset(max(0, min(cursor, n)))
                            buf.place_cursor(it)
                if job["active_tab"] is not None:
                    window._focus_tab(job["active_tab"])

            if pending:
                GLib.idle_add(
                    self._restore_next_tab, window, state, job,
                    priority=GLib.PRIORITY_LOW,
                )
            else:
                self._finish_restore(window, state, job)
        except Exception:
            log.exception("session restore failed")
        return False

    def _finish_restore(self, window: EditorWindow, state: dict, job: dict) -> None:
        if not job["restored"]:
            window.add_tab()
            return
        # Active-first loading changes append order; put every group back in
        # the exact visual order stored in the session.
        raw_tabs = state.get("tabs", [])
        original = [tab for tab in raw_tabs if isinstance(tab, dict)] if isinstance(raw_tabs, list) else []
        per_group: dict[int, list[tuple[int, object]]] = {0: [], 1: []}
        for tabinfo, tab in job["restored"]:
            group = tabinfo.get("group", 0)
            group = group if group in (0, 1) else 0
            group_order = [item for item in original if item.get("group", 0) == group]
            per_group[group].append((group_order.index(tabinfo), tab))
        window._adding_tab = True
        try:
            for group, entries in per_group.items():
                if group >= len(window._notebooks):
                    continue
                notebook = window._notebooks[group]
                for position, tab in sorted(entries):
                    notebook.reorder_child(tab, position)

            window.tidy_groups()
            pages = state.get("group_pages") or [state.get("active", 0)]
            for group, page in enumerate(pages):
                if isinstance(page, int):
                    window.select_page(group, page)
            active_group = state.get("active_group", 0)
            window.use_group(active_group if active_group in (0, 1) else 0)
        finally:
            window._adding_tab = False
        tab = window.current_tab()
        if tab is not None:
            window._maybe_auto_preview(tab)
            window.after_first_frame(tab.init_deferred_widgets)
            GLib.idle_add(self._scroll_to_cursor, tab)

    @staticmethod
    def _scroll_to_cursor(tab) -> bool:
        try:
            mark = tab.buffer.get_insert()
            tab.view.scroll_to_mark(mark, 0.2, True, 0.0, 0.3)
        except Exception:
            log.debug("scroll to cursor failed", exc_info=True)
        return False

    def _maybe_restore_drafts(self, window: EditorWindow) -> bool:
        try:
            from . import backups, recovery

            backups.prune()

            pending = recovery.list_pending()
            if not pending:
                return False
            count = 0
            for draft in pending:
                if not draft.original_path:
                    continue
                # Compare with on-disk state — only offer if differs
                try:
                    current = draft.original_path.read_text(
                        encoding=draft.encoding, errors="replace",
                    )
                except OSError:
                    current = None
                if current is not None and current == draft.body:
                    recovery.discard(draft.original_path)
                    continue
                # Open draft as a fresh tab marked modified
                from .buffer import EditorBuffer
                buf = EditorBuffer()
                buf.load(draft.body, draft.original_path, draft.encoding, draft.base_mtime)
                buf.set_modified(True)
                window.add_tab(buf)
                count += 1
            if count:
                window._set_status(f"Restored {count} draft buffer(s) from previous session")
        except Exception:
            log.exception("draft restore failed")
        return False

    def _maybe_show_whats_new(self, window: EditorWindow) -> bool:
        try:
            if self.settings.last_seen_version == __version__:
                return False
            from .whatsnew import WhatsNewDialog, section_for_version

            content = section_for_version(__version__)
            if content:
                WhatsNewDialog(window, __version__, content).present()
            else:
                log.info("no CHANGELOG section for %s — skipping What's New", __version__)
            self.settings.last_seen_version = __version__
            self.settings.save()
        except Exception:
            log.exception("What's New failed")
        return False

    def new_window(self) -> EditorWindow:
        from .window import EditorWindow
        return EditorWindow(self, self.settings)

    @staticmethod
    def _resolve(cwd: Path, name: str) -> Path:
        # `gnome-terminal` Ctrl+click and other URI launchers pass paths as
        # `file:///abs/path`. `Path()` doesn't understand the scheme — it
        # treats the result as a relative path and joins it with cwd into
        # garbage. Strip the URI prefix and URL-decode percent escapes.
        if name.startswith("file://"):
            from urllib.parse import unquote, urlparse
            parsed = urlparse(name)
            name = unquote(parsed.path)
        p = Path(name)
        return p if p.is_absolute() else (cwd / p).resolve()

    def notify_recent_changed(self) -> None:
        self._rebuild_recent_menu()

    def broadcast_settings(self, settings: Settings) -> None:
        from . import desktop_integration

        self.settings = settings
        self._apply_theme(settings.dark_ui)
        if self._auto_theme_pending:
            GLib.idle_add(self._refresh_auto_theme)
        desktop_integration.apply(settings.register_in_file_manager)
        for window in self.get_windows():
            if hasattr(window, "apply_settings"):
                window.apply_settings(settings)

    def _install_snippet_path(self) -> None:
        try:
            from gi.repository import GtkSource

            mgr = GtkSource.SnippetManager.get_default()
            current = list(mgr.get_search_path() or [])
            extra: list[str] = []
            snap = os.environ.get("SNAP")
            if snap:
                extra.append(f"{snap}/usr/share/apedi/snippets")
            extra.append(str(Path(__file__).resolve().parent.parent / "data" / "snippets"))
            paths = current + [p for p in extra if p not in current and Path(p).is_dir()]
            mgr.set_search_path(paths)
        except Exception:
            log.debug("snippet path setup failed", exc_info=True)

    def _apply_theme(self, theme: str) -> None:
        if theme == "auto":
            # A synchronous portal call can consume its full 500 ms timeout.
            # Use the editor scheme as an immediate, usually-correct fallback
            # and ask the portal only after the first frame.
            self._auto_theme_pending = True
            prefer_dark = "dark" in self.settings.color_scheme.casefold()
        elif theme == "dark":
            self._auto_theme_pending = False
            prefer_dark = True
        else:
            self._auto_theme_pending = False
            prefer_dark = False
        Gtk.Settings.get_default().set_property(
            "gtk-application-prefer-dark-theme", bool(prefer_dark)
        )

    def _refresh_auto_theme(self) -> bool:
        if not self._auto_theme_pending or self.settings.dark_ui != "auto":
            return False
        self._auto_theme_pending = False
        Gtk.Settings.get_default().set_property(
            "gtk-application-prefer-dark-theme", _detect_system_dark()
        )
        return False


def _detect_system_dark() -> bool:
    """Ask xdg-desktop-portal for the user's color-scheme preference.

    Returns True for prefer-dark, False otherwise (including timeout/error).
    """
    try:
        proxy = Gio.DBusProxy.new_for_bus_sync(
            Gio.BusType.SESSION,
            Gio.DBusProxyFlags.NONE,
            None,
            "org.freedesktop.portal.Desktop",
            "/org/freedesktop/portal/desktop",
            "org.freedesktop.portal.Settings",
            None,
        )
        result = proxy.call_sync(
            "Read",
            GLib.Variant("(ss)", ("org.freedesktop.appearance", "color-scheme")),
            Gio.DBusCallFlags.NONE,
            500,
            None,
        )
        unpacked = result.unpack() if result else None
        if not unpacked:
            return False
        # Tuple wraps a Variant which unpacks to a uint: 1=dark, 2=light, 0=none.
        value = unpacked[0]
        if isinstance(value, int):
            return value == 1
    except Exception as e:  # noqa: BLE001
        log.debug("portal color-scheme lookup failed: %s", e)
    return False


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    app = EditorApp()
    return app.run(argv if argv is not None else sys.argv)


if __name__ == "__main__":
    sys.exit(main())
