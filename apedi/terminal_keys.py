"""Key routing for the focused terminal, kept free of Vte for testing."""

from __future__ import annotations

import gi

gi.require_version("Gdk", "4.0")
from gi.repository import Gdk  # noqa: E402

COPY = "copy"
PASTE = "paste"
APP = "app"
TERMINAL = "terminal"

# Ctrl+key combinations the editor keeps even while the terminal has focus.
_APP_CTRL_KEYS = {
    Gdk.KEY_Tab,
    Gdk.KEY_ISO_Left_Tab,
    Gdk.KEY_Page_Up,
    Gdk.KEY_Page_Down,
    Gdk.KEY_KP_Page_Up,
    Gdk.KEY_KP_Page_Down,
    Gdk.KEY_grave,
    Gdk.KEY_comma,
    *range(Gdk.KEY_0, Gdk.KEY_9 + 1),
}

_MODS = Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.SHIFT_MASK | Gdk.ModifierType.ALT_MASK


def route(keyval: int, state: Gdk.ModifierType) -> str:
    """Where a key press in the terminal goes: clipboard, editor shortcut or the shell."""
    mods = state & _MODS
    ctrl = bool(mods & Gdk.ModifierType.CONTROL_MASK)
    shift = bool(mods & Gdk.ModifierType.SHIFT_MASK)
    alt = bool(mods & Gdk.ModifierType.ALT_MASK)
    lower = Gdk.keyval_to_lower(keyval)

    if ctrl and shift and not alt:
        if lower == Gdk.KEY_c:
            return COPY
        if lower == Gdk.KEY_v:
            return PASTE
    if keyval in (Gdk.KEY_Insert, Gdk.KEY_KP_Insert) and not alt:
        if ctrl and not shift:
            return COPY
        if shift and not ctrl:
            return PASTE
    if ctrl and shift:
        return APP
    if ctrl and not alt and keyval in _APP_CTRL_KEYS:
        return APP
    return TERMINAL
