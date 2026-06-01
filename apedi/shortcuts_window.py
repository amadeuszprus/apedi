"""Gtk.ShortcutsWindow listing every keyboard shortcut Apedi binds."""

from __future__ import annotations

import builtins

if not hasattr(builtins, "_"):
    builtins._ = lambda s: s  # type: ignore[attr-defined]

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk  # noqa: E402


def _add(group: Gtk.ShortcutsGroup, accel: str, title: str) -> None:
    sc = Gtk.ShortcutsShortcut(accelerator=accel, title=title)
    group.add_shortcut(sc)


def present(parent: Gtk.Window) -> None:
    win = Gtk.ShortcutsWindow(transient_for=parent, modal=True)
    win.set_default_size(720, 600)

    section = Gtk.ShortcutsSection(visible=True)

    # File
    file_group = Gtk.ShortcutsGroup(title=_("File"))
    _add(file_group, "<Primary>t",            _("New tab"))
    _add(file_group, "<Primary>n",            _("New window"))
    _add(file_group, "<Primary>o",            _("Open file"))
    _add(file_group, "<Primary><Shift>o",     _("Open / add project"))
    _add(file_group, "<Primary>s",            _("Save"))
    _add(file_group, "<Primary><Shift>s",     _("Save As"))
    _add(file_group, "<Primary>w",            _("Close tab"))
    _add(file_group, "<Primary><Shift>w",     _("Close window"))
    _add(file_group, "<Primary>q",            _("Quit"))
    section.add_group(file_group)

    # Navigation
    nav_group = Gtk.ShortcutsGroup(title=_("Navigation"))
    _add(nav_group, "<Primary>Tab",           _("Next tab"))
    _add(nav_group, "<Primary><Shift>Tab",    _("Previous tab"))
    _add(nav_group, "<Primary>p",             _("Quick Open file"))
    _add(nav_group, "<Primary>m",             _("Go to symbol in file"))
    _add(nav_group, "<Primary>g",             _("Go to line"))
    section.add_group(nav_group)

    # Search & edit
    edit_group = Gtk.ShortcutsGroup(title=_("Edit & search"))
    _add(edit_group, "<Primary>f",            _("Find"))
    _add(edit_group, "<Primary>r",            _("Replace"))
    _add(edit_group, "<Primary><Shift>f",     _("Find in Files"))
    _add(edit_group, "<Primary><Shift>i",     _("Format current file"))
    section.add_group(edit_group)

    # Sidebar
    sidebar_group = Gtk.ShortcutsGroup(title=_("Sidebar"))
    _add(sidebar_group, "<Primary><Alt>n",        _("New file in selected folder"))
    _add(sidebar_group, "<Primary><Alt><Shift>n", _("New folder in selected folder"))
    _add(sidebar_group, "<Primary><Alt>f",        _("Find in selected file/folder"))
    _add(sidebar_group, "<Primary><Alt>h",        _("Replace in selected file/folder"))
    section.add_group(sidebar_group)

    # View
    view_group = Gtk.ShortcutsGroup(title=_("View"))
    _add(view_group, "F9",                    _("Toggle sidebar"))
    _add(view_group, "<Primary>grave",        _("Toggle terminal"))
    _add(view_group, "<Primary><Shift>grave", _("New terminal"))
    _add(view_group, "<Primary><Shift>m",     _("Toggle Markdown preview"))
    _add(view_group, "<Primary>comma",        _("Preferences"))
    _add(view_group, "<Primary><Shift>d",     _("Cycle theme: auto / light / dark"))
    section.add_group(view_group)

    win.add_section(section)
    win.present()
