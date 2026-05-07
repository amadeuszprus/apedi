"""Integrated VTE terminal panel."""

from __future__ import annotations

import logging
import os
from pathlib import Path

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


class TerminalPanel(Gtk.Box):
    __gtype_name__ = "ApediTerminalPanel"

    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.set_size_request(-1, 180)
        self.set_vexpand(False)

        header = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL, spacing=4,
            margin_start=10, margin_end=6, margin_top=4, margin_bottom=4,
        )
        title = Gtk.Label(label="Terminal", xalign=0)
        title.set_hexpand(True)
        title.add_css_class("dim-label")
        header.append(title)
        close_btn = Gtk.Button.new_from_icon_name("window-close-symbolic")
        close_btn.set_tooltip_text("Hide terminal (Ctrl+`)")
        close_btn.set_action_name("win.toggle-terminal")
        close_btn.add_css_class("flat")
        header.append(close_btn)
        self.append(header)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_hexpand(True)

        self.terminal = Vte.Terminal()
        self.terminal.set_font(Pango.FontDescription.from_string("Monospace 10"))
        self.terminal.set_scrollback_lines(10000)
        self.terminal.set_mouse_autohide(True)
        scrolled.set_child(self.terminal)
        self.append(scrolled)

        self._spawned = False

    def ensure_started(self, cwd: str | None = None) -> None:
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
