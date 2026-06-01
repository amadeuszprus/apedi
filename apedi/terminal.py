"""Integrated VTE terminal panel with multi-tab support."""

from __future__ import annotations

import builtins
import logging
import os
from pathlib import Path

if not hasattr(builtins, "_"):
    builtins._ = lambda s: s  # type: ignore[attr-defined]

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Vte", "3.91")
from gi.repository import GLib, Gtk, Pango, Vte  # noqa: E402

log = logging.getLogger(__name__)


def _user_shell_name() -> str:
    """Determine user's preferred shell — $SHELL first, then /etc/passwd."""
    shell_env = os.environ.get("SHELL", "")
    if shell_env:
        return Path(shell_env).name
    try:
        import pwd

        return Path(pwd.getpwuid(os.getuid()).pw_shell).name
    except (KeyError, OSError):
        return ""


def _resolve_shell() -> str:
    """Pick a shell binary. Prefer the user's shell by basename, look in
    $SNAP/bin and $SNAP/usr/bin first (apt's `zsh` lands at $SNAP/bin/zsh
    while bash sits at $SNAP/usr/bin/bash), then /bin and /usr/bin."""
    snap = os.environ.get("SNAP", "")
    name = _user_shell_name()

    candidates: list[str] = []
    if name:
        candidates += [
            f"{snap}/bin/{name}",
            f"{snap}/usr/bin/{name}",
            f"/bin/{name}",
            f"/usr/bin/{name}",
        ]
    # Fallback chain when the requested shell is not packaged
    candidates += [
        f"{snap}/bin/zsh",
        f"{snap}/usr/bin/zsh",
        f"{snap}/bin/bash",
        f"{snap}/usr/bin/bash",
        "/bin/zsh", "/usr/bin/zsh",
        "/bin/bash", "/usr/bin/bash",
        "/bin/sh",
    ]
    for path in candidates:
        if path and Path(path).exists():
            log.info("terminal shell: %s (preferred basename: %r)", path, name)
            return path
    return "/bin/sh"


class _TerminalTab(Gtk.ScrolledWindow):
    """One VTE terminal wrapped in a ScrolledWindow."""

    __gtype_name__ = "ApediTerminalTab"

    def __init__(self) -> None:
        super().__init__()
        self.set_vexpand(True)
        self.set_hexpand(True)
        self.terminal = Vte.Terminal()
        self.terminal.set_font(Pango.FontDescription.from_string("Monospace 10"))
        self.terminal.set_scrollback_lines(10000)
        self.terminal.set_mouse_autohide(True)
        self.set_child(self.terminal)
        self._spawned = False
        self.on_exit: "callable | None" = None
        self.terminal.connect("child-exited", self._on_child_exited)

    def spawn(self, cwd: str | None = None) -> None:
        if self._spawned:
            return
        self._spawned = True
        shell = _resolve_shell()
        env = [f"{k}={v}" for k, v in os.environ.items()]
        try:
            self.terminal.spawn_async(
                Vte.PtyFlags.DEFAULT,
                cwd or str(Path.home()),
                [shell],
                env,
                GLib.SpawnFlags.DEFAULT,
                None, None,
                -1,
                None,
                None,
            )
        except Exception as e:  # noqa: BLE001
            log.exception("VTE spawn failed: %s", e)

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

    # ---------- Public API ----------

    def ensure_started(self, cwd: str | None = None) -> None:
        """Create the first terminal lazily on the first show."""
        self._default_cwd = cwd or self._default_cwd
        if self.notebook.get_n_pages() == 0:
            self.add_terminal(cwd)

    def add_terminal(self, cwd: str | None = None) -> _TerminalTab:
        """Append a new terminal tab and focus it."""
        tab = _TerminalTab()
        tab.on_exit = self._on_tab_exit
        label_box = self._make_tab_label(tab, self._next_index)
        self._next_index += 1
        idx = self.notebook.append_page(tab, label_box)
        self.notebook.set_tab_reorderable(tab, True)
        tab.spawn(cwd or self._default_cwd)
        self.notebook.set_current_page(idx)
        tab.terminal.grab_focus()
        return tab

    def focus_current(self) -> None:
        page = self.notebook.get_current_page()
        if page < 0:
            return
        tab = self.notebook.get_nth_page(page)
        if isinstance(tab, _TerminalTab):
            tab.terminal.grab_focus()

    # ---------- Internal ----------

    def _make_tab_label(self, tab: _TerminalTab, index: int) -> Gtk.Box:
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        label = Gtk.Label(label=_("Terminal {n}").format(n=index))
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

    def _on_tab_exit(self, tab: _TerminalTab) -> None:
        self._close_tab(tab)
