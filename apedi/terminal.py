"""Integrated VTE terminal panel with multi-tab support."""

from __future__ import annotations

import builtins
import logging
import os
from pathlib import Path
from typing import Callable
from urllib.parse import unquote, urlparse

if not hasattr(builtins, "_"):
    builtins._ = lambda s: s  # type: ignore[attr-defined]

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Vte", "3.91")
from gi.repository import Gdk, Gio, GLib, Gtk, Pango, Vte  # noqa: E402

from . import locations, terminal_keys
from .shell import resolve_shell, spawn_env

log = logging.getLogger(__name__)

# PCRE2_MULTILINE, which Vte requires for match regexes.
_PCRE2_MULTILINE = 0x00000400


def _match_regexes() -> list["Vte.Regex"]:
    out = []
    for pattern in (locations.PYTHON_TRACE_PATTERN, locations.PATH_PATTERN):
        try:
            out.append(Vte.Regex.new_for_match(pattern, -1, _PCRE2_MULTILINE))
        except GLib.Error as e:
            log.warning("terminal link regex rejected: %s", e.message)
    return out


class _TerminalTab(Gtk.ScrolledWindow):
    """One VTE terminal wrapped in a ScrolledWindow."""

    __gtype_name__ = "ApediTerminalTab"

    def __init__(self, menu: Gio.MenuModel) -> None:
        super().__init__()
        self.set_vexpand(True)
        self.set_hexpand(True)
        self.terminal = Vte.Terminal()
        self.terminal.set_font(Pango.FontDescription.from_string("Monospace 10"))
        self.terminal.set_scrollback_lines(10000)
        self.terminal.set_mouse_autohide(True)
        self.terminal.set_context_menu_model(menu)
        self.set_child(self.terminal)
        self._spawned = False
        self._pending_command: str | None = None
        self._pid: int = 0
        self.cwd: Path | None = None
        self.on_exit: "Callable[[_TerminalTab], None] | None" = None
        self.on_open_location: "Callable[[_TerminalTab, str], bool] | None" = None
        self.terminal.connect("child-exited", self._on_child_exited)
        for regex in _match_regexes():
            tag = self.terminal.match_add_regex(regex, 0)
            self.terminal.match_set_cursor_name(tag, "pointer")
        click = Gtk.GestureClick.new()
        click.set_button(Gdk.BUTTON_PRIMARY)
        click.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        click.connect("pressed", self._on_pressed)
        self.terminal.add_controller(click)

    def spawn(self, cwd: str | None = None, command: str | None = None) -> None:
        if self._spawned:
            return
        self._spawned = True
        self._pending_command = command
        self.cwd = Path(cwd) if cwd else Path.home()
        shell = resolve_shell()
        env = spawn_env(shell)
        try:
            self.terminal.spawn_async(
                Vte.PtyFlags.DEFAULT,
                str(self.cwd),
                [shell],
                env,
                GLib.SpawnFlags.DEFAULT,
                None, None,
                -1,
                None,
                self._on_spawned,
                None,
            )
        except Exception as e:  # noqa: BLE001
            log.exception("VTE spawn failed: %s", e)

    def _on_spawned(self, _term: Vte.Terminal, pid: int, error: "GLib.Error | None", *_args: object) -> None:
        if error is not None:
            log.warning("terminal spawn failed: %s", error.message)
            return
        self._pid = pid
        if self._pending_command:
            self.terminal.feed_child((self._pending_command + "\n").encode())
            self._pending_command = None

    def current_dir(self) -> Path | None:
        """Where the shell is now: its OSC 7 report, else its /proc cwd, else where it started."""
        uri = self.terminal.get_current_directory_uri()
        if uri:
            path = Path(unquote(urlparse(uri).path))
            if path.is_dir():
                return path
        if self._pid > 0:
            try:
                return Path(os.readlink(f"/proc/{self._pid}/cwd"))
            except OSError:
                pass
        return self.cwd

    def copy(self) -> None:
        if self.terminal.get_has_selection():
            self.terminal.copy_clipboard_format(Vte.Format.TEXT)

    def paste(self) -> None:
        self.terminal.paste_clipboard()

    def select_all(self) -> None:
        self.terminal.select_all()

    def _on_pressed(self, gesture: Gtk.GestureClick, _n: int, x: float, y: float) -> None:
        state = gesture.get_current_event_state()
        if not state & Gdk.ModifierType.CONTROL_MASK or self.on_open_location is None:
            return
        match, _tag = self.terminal.check_match_at(x, y)
        if match and self.on_open_location(self, match):
            gesture.set_state(Gtk.EventSequenceState.CLAIMED)

    def _on_child_exited(self, _term: Vte.Terminal, _status: int) -> None:
        if self.on_exit is not None:
            self.on_exit(self)


class TerminalPanel(Gtk.Box):
    """Panel hosting multiple terminal tabs in a Gtk.Notebook."""

    __gtype_name__ = "ApediTerminalPanel"

    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.set_size_request(-1, 180)
        self.set_vexpand(False)

        header = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL, spacing=4,
            margin_start=10, margin_end=6, margin_top=4, margin_bottom=4,
        )
        title = Gtk.Label(label=_("Terminal"), xalign=0)
        title.set_hexpand(True)
        title.add_css_class("dim-label")
        header.append(title)

        add_btn = Gtk.Button.new_from_icon_name("list-add-symbolic")
        add_btn.set_tooltip_text(_("New terminal (Ctrl+Shift+`)"))
        add_btn.set_action_name("win.new-terminal")
        add_btn.add_css_class("flat")
        header.append(add_btn)

        close_btn = Gtk.Button.new_from_icon_name("window-close-symbolic")
        close_btn.set_tooltip_text(_("Hide terminal (Ctrl+`)"))
        close_btn.set_action_name("win.toggle-terminal")
        close_btn.add_css_class("flat")
        header.append(close_btn)
        self.append(header)

        self.notebook = Gtk.Notebook()
        self.notebook.set_scrollable(True)
        self.notebook.set_vexpand(True)
        self.notebook.set_hexpand(True)
        self.notebook.set_show_border(False)
        self.append(self.notebook)

        self._next_index = 1
        self._default_cwd: str | None = None
        self.on_open_location: Callable[[str, list[Path]], bool] | None = None
        self.on_empty: Callable[[], None] | None = None
        self._menu = self._build_menu()

    # ---------- Public API ----------

    def attach_to_window(self, window: Gtk.Window) -> None:
        """Route keys to the focused terminal before the window's shortcuts see them."""
        # Added after the application's shortcut controller, so it runs first.
        key = Gtk.EventControllerKey()
        key.set_name("apedi-terminal-keys")
        key.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        key.connect("key-pressed", self._on_window_key)
        window.add_controller(key)

    def ensure_started(self, cwd: str | None = None) -> None:
        """Create the first terminal lazily on the first show."""
        self._default_cwd = cwd or self._default_cwd
        if self.notebook.get_n_pages() == 0:
            self.add_terminal(cwd)

    def add_terminal(
        self, cwd: str | None = None, *, command: str | None = None, title: str | None = None,
    ) -> _TerminalTab:
        """Append a new terminal tab, optionally running `command`, and focus it."""
        tab = _TerminalTab(self._menu)
        tab.on_exit = self._on_tab_exit
        tab.on_open_location = self._open_location
        if title is None:
            title = _("Terminal {n}").format(n=self._next_index)
            self._next_index += 1
        label_box = self._make_tab_label(tab, title)
        idx = self.notebook.append_page(tab, label_box)
        self.notebook.set_tab_reorderable(tab, True)
        tab.spawn(cwd or self._default_cwd, command)
        self.notebook.set_current_page(idx)
        tab.terminal.grab_focus()
        return tab

    def focus_current(self) -> None:
        tab = self._current_tab()
        if tab is not None:
            tab.terminal.grab_focus()

    # ---------- Internal ----------

    def _current_tab(self) -> _TerminalTab | None:
        page = self.notebook.get_current_page()
        if page < 0:
            return None
        tab = self.notebook.get_nth_page(page)
        return tab if isinstance(tab, _TerminalTab) else None

    def _focused_tab(self) -> _TerminalTab | None:
        root = self.get_root()
        focus = root.get_focus() if root is not None else None
        if not isinstance(focus, Vte.Terminal):
            return None
        tab = focus.get_parent()
        while tab is not None and not isinstance(tab, _TerminalTab):
            tab = tab.get_parent()
        if tab is None or not tab.is_ancestor(self):
            return None
        return tab

    def _on_window_key(
        self, ctrl: Gtk.EventControllerKey, keyval: int, _keycode: int, state: Gdk.ModifierType,
    ) -> bool:
        tab = self._focused_tab()
        if tab is None:
            return False
        where = terminal_keys.route(keyval, state)
        if where == terminal_keys.COPY:
            tab.copy()
            return True
        if where == terminal_keys.PASTE:
            tab.paste()
            return True
        if where == terminal_keys.APP:
            return False
        return ctrl.forward(tab.terminal)

    def _build_menu(self) -> Gio.Menu:
        group = Gio.SimpleActionGroup()
        for name, method in (("copy", "copy"), ("paste", "paste"), ("select-all", "select_all")):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", lambda *_a, m=method: self._on_menu_action(m))
            group.add_action(action)
        self.insert_action_group("term", group)

        menu = Gio.Menu()
        for label, action, accel in (
            (_("Copy"), "term.copy", "<Primary><Shift>c"),
            (_("Paste"), "term.paste", "<Primary><Shift>v"),
            (_("Select All"), "term.select-all", None),
        ):
            item = Gio.MenuItem.new(label, action)
            if accel:
                item.set_attribute_value("accel", GLib.Variant.new_string(accel))
            menu.append_item(item)
        return menu

    def _on_menu_action(self, method: str) -> None:
        tab = self._current_tab()
        if tab is not None:
            getattr(tab, method)()

    def _open_location(self, tab: _TerminalTab, text: str) -> bool:
        if self.on_open_location is None:
            return False
        bases = [p for p in (tab.current_dir(), tab.cwd) if p is not None]
        return self.on_open_location(text, bases)

    def _make_tab_label(self, tab: _TerminalTab, title: str) -> Gtk.Box:
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        label = Gtk.Label(label=title)
        box.append(label)
        close_btn = Gtk.Button.new_from_icon_name("window-close-symbolic")
        close_btn.add_css_class("flat")
        close_btn.set_has_frame(False)
        close_btn.set_tooltip_text(_("Close terminal"))
        close_btn.connect("clicked", lambda *_: self._close_tab(tab))
        box.append(close_btn)

        middle_click = Gtk.GestureClick.new()
        middle_click.set_button(2)
        middle_click.connect("released", lambda *_: self._close_tab(tab))
        box.add_controller(middle_click)
        return box

    def _close_tab(self, tab: _TerminalTab) -> None:
        idx = self.notebook.page_num(tab)
        if idx < 0:
            return
        self.notebook.remove_page(idx)
        if self.notebook.get_n_pages() == 0 and self.on_empty is not None:
            self.on_empty()

    def _on_tab_exit(self, tab: _TerminalTab) -> None:
        self._close_tab(tab)
