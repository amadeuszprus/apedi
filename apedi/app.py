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

i18n.configure_locale()
i18n.install(Settings.load().language)

log = logging.getLogger(__name__)


class EditorApp(Gtk.Application):
    def __init__(self) -> None:
        super().__init__(
            application_id=APP_ID,
            flags=Gio.ApplicationFlags.HANDLES_OPEN | Gio.ApplicationFlags.HANDLES_COMMAND_LINE,
        )
        self.settings = Settings.load()
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
        from . import desktop_integration, style as _style

        _style.install()
        self._install_snippet_path()
        desktop_integration.apply(self.settings.register_in_file_manager)
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

        support = Gio.SimpleAction.new("support", None)
        support.connect("activate", self._on_support)
        self.add_action(support)

        self.recent_menu = Gio.Menu()
        self._rebuild_recent_menu()

        for action_name, accels in SHORTCUTS:
            self.set_accels_for_action(action_name, accels)

    def _rebuild_recent_menu(self) -> None:
        self.recent_menu.remove_all()
        paths = recent.filter_existing(recent.load())
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

    def _on_support(self, *_: object) -> None:
        win = self.get_active_window()
        try:
            launcher = Gtk.UriLauncher.new("https://buycoffee.to/aprus")
            launcher.launch(win, None, None, None)
        except Exception:
            log.exception("UriLauncher failed; falling back to Gio.AppInfo")
            Gio.AppInfo.launch_default_for_uri("https://buycoffee.to/aprus", None)

    def do_command_line(self, command_line: Gio.ApplicationCommandLine) -> int:
        options = command_line.get_options_dict().end().unpack()
        files = options.get(GLib.OPTION_REMAINING, []) or []
        force_new = bool(options.get("new-window"))
        cwd = Path(command_line.get_cwd() or ".")
        paths = [self._resolve(cwd, f) for f in files]

        if force_new or not self.get_active_window():
            window = self.new_window()
        else:
            window = self.get_active_window()

        if paths:
            for p in paths:
                window.open_path(p)
        elif window.notebook.get_n_pages() == 0:
            window.add_tab()

        window.present()
        GLib.idle_add(self._maybe_show_whats_new, window)
        return 0

    def do_activate(self) -> None:
        win = self.get_active_window() or self.new_window()
        if win.notebook.get_n_pages() == 0:
            win.add_tab()
        win.present()
        GLib.idle_add(self._maybe_show_whats_new, win)
        GLib.idle_add(self._maybe_restore_drafts, win)

    def _maybe_restore_drafts(self, window: EditorWindow) -> bool:
        try:
            from . import recovery

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
            prefer_dark = _detect_system_dark()
        elif theme == "dark":
            prefer_dark = True
        else:
            prefer_dark = False
        Gtk.Settings.get_default().set_property(
            "gtk-application-prefer-dark-theme", bool(prefer_dark)
        )


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
