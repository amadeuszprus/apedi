"""Keyboard shortcut → action name mappings."""

from __future__ import annotations

# Each entry: (action_name, [accelerators])
SHORTCUTS: list[tuple[str, list[str]]] = [
    ("app.quit", ["<Primary>q"]),
    ("win.new-tab", ["<Primary>t"]),
    ("win.new-window", ["<Primary>n"]),
    ("win.open", ["<Primary>o"]),
    ("win.save", ["<Primary>s"]),
    ("win.save-as", ["<Primary><Shift>s"]),
    ("win.close-tab", ["<Primary>w"]),
    ("win.close-window", ["<Primary><Shift>w"]),
    ("win.next-tab", ["<Primary>Tab", "<Primary>Page_Down"]),
    ("win.prev-tab", ["<Primary><Shift>Tab", "<Primary>Page_Up"]),
    ("win.find", ["<Primary>f"]),
    ("win.replace", ["<Primary>r"]),
    ("win.goto-line", ["<Primary>g"]),
    ("win.format", ["<Primary><Shift>i"]),
    ("win.preferences", ["<Primary>comma"]),
    ("win.toggle-dark", ["<Primary><Shift>d"]),
    ("win.open-project", ["<Primary><Shift>o"]),
    ("win.toggle-sidebar", ["F9"]),
    ("win.toggle-terminal", ["<Primary>grave"]),
    ("win.new-terminal", ["<Primary><Shift>grave"]),
    ("win.toggle-preview", ["<Primary><Shift>m"]),
    ("win.symbols", ["<Primary>m"]),
    ("win.quick-open", ["<Primary>p"]),
    ("win.find-in-files", ["<Primary><Shift>f"]),
    ("win.sidebar-new-file", ["<Primary><Alt>n"]),
    ("win.sidebar-new-folder", ["<Primary><Alt><Shift>n"]),
    ("win.sidebar-find", ["<Primary><Alt>f"]),
    ("win.sidebar-replace", ["<Primary><Alt>h"]),
    ("win.shortcuts", ["<Primary>question", "F1"]),
    ("app.about", []),
    ("app.support", []),
]
