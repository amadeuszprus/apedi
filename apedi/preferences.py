"""Preferences dialog — live-applies settings as they change."""

from __future__ import annotations

import builtins
from typing import Callable

if not hasattr(builtins, "_"):
    builtins._ = lambda s: s  # type: ignore[attr-defined]

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("GtkSource", "5")
from gi.repository import Gtk, GtkSource, Pango  # noqa: E402

from .settings import Settings


class _Page:
    """Helper holding the current Gtk.Grid being filled and its row counter."""

    def __init__(self) -> None:
        self.grid = Gtk.Grid(
            column_spacing=14, row_spacing=10,
            margin_top=18, margin_bottom=18, margin_start=20, margin_end=20,
        )
        self.row = 0

    def add(self, label: str, widget: Gtk.Widget) -> None:
        lbl = Gtk.Label(label=label, xalign=0)
        lbl.set_hexpand(True)
        self.grid.attach(lbl, 0, self.row, 1, 1)
        self.grid.attach(widget, 1, self.row, 1, 1)
        self.row += 1


class PreferencesDialog(Gtk.Window):
    __gtype_name__ = "ApediPreferencesDialog"

    def __init__(
        self,
        parent: Gtk.Window,
        settings: Settings,
        on_changed: Callable[[Settings], None],
    ) -> None:
        super().__init__(
            title=_("Preferences"),
            transient_for=parent,
            modal=True,
            default_width=520,
            default_height=520,
        )
        self.settings = settings
        self.on_changed = on_changed
        self._suspend = True  # don't fire _sync during initial widget setup

        notebook = Gtk.Notebook()
        notebook.set_scrollable(True)
        notebook.set_margin_top(8)
        notebook.set_margin_bottom(8)
        notebook.set_margin_start(8)
        notebook.set_margin_end(8)

        notebook.append_page(self._build_appearance_page(), Gtk.Label(label=_("Appearance")))
        notebook.append_page(self._build_editor_page(),     Gtk.Label(label=_("Editor")))
        notebook.append_page(self._build_files_page(),      Gtk.Label(label=_("Files")))
        notebook.append_page(self._build_sidebar_page(),    Gtk.Label(label=_("Sidebar")))
        notebook.append_page(self._build_system_page(),     Gtk.Label(label=_("System")))

        self.set_child(notebook)
        self._suspend = False

    # ---------- pages ----------

    def _build_appearance_page(self) -> Gtk.Widget:
        page = _Page()
        self.scheme_combo = self._build_scheme_combo()
        page.add(_("Editor color scheme"), self.scheme_combo)
        self.theme_combo = self._build_theme_combo()
        page.add(_("Window theme"), self.theme_combo)
        self.font_btn = self._build_font_button()
        page.add(_("Font"), self.font_btn)
        return page.grid

    def _build_editor_page(self) -> Gtk.Widget:
        page = _Page()
        self.tab_spin = Gtk.SpinButton.new_with_range(1, 16, 1)
        self.tab_spin.set_value(self.settings.tab_width)
        self.tab_spin.connect("value-changed", self._sync)
        page.add(_("Tab width"), self.tab_spin)

        self.spaces_switch = self._switch(self.settings.use_spaces)
        page.add(_("Indent with spaces"), self.spaces_switch)

        self.wrap_switch = self._switch(self.settings.wrap_lines)
        page.add(_("Wrap long lines"), self.wrap_switch)

        self.lineno_switch = self._switch(self.settings.show_line_numbers)
        page.add(_("Show line numbers"), self.lineno_switch)

        self.autoindent_switch = self._switch(self.settings.auto_indent)
        page.add(_("Auto indent"), self.autoindent_switch)

        self.trim_switch = self._switch(self.settings.trim_trailing_whitespace)
        page.add(_("Trim trailing whitespace on save"), self.trim_switch)

        self.md_preview_switch = self._switch(self.settings.markdown_preview_auto)
        page.add(_("Markdown preview (auto-open for .md)"), self.md_preview_switch)
        return page.grid

    def _build_files_page(self) -> Gtk.Widget:
        page = _Page()
        self.autosave_combo = self._build_autosave_combo()
        page.add(_("Autosave"), self.autosave_combo)

        self.autosave_delay = Gtk.SpinButton.new_with_range(250, 60000, 250)
        self.autosave_delay.set_value(self.settings.autosave_delay_ms)
        self.autosave_delay.connect("value-changed", self._sync)
        page.add(_("Autosave delay (ms)"), self.autosave_delay)
        return page.grid

    def _build_sidebar_page(self) -> Gtk.Widget:
        page = _Page()
        self.sidebar_switch = self._switch(self.settings.show_sidebar)
        page.add(_("Show project sidebar"), self.sidebar_switch)

        self.compact_switch = self._switch(self.settings.sidebar_compact)
        page.add(_("Compact sidebar"), self.compact_switch)

        self.ignore_entry = Gtk.Entry()
        self.ignore_entry.set_placeholder_text(_("e.g. *.log, build/, secrets.txt"))
        self.ignore_entry.set_text(", ".join(self.settings.ignore_patterns))
        self.ignore_entry.set_hexpand(True)
        self.ignore_entry.connect("changed", self._sync)
        page.add(_("Extra ignore patterns"), self.ignore_entry)
        return page.grid

    def _build_system_page(self) -> Gtk.Widget:
        page = _Page()
        self.fm_switch = self._switch(self.settings.register_in_file_manager)
        page.add(_("Show in file manager 'Open with' menu"), self.fm_switch)

        self.language_combo = self._build_language_combo()
        page.add(_("Language (restart required)"), self.language_combo)
        return page.grid

    def _build_language_combo(self) -> Gtk.DropDown:
        self._language_options = ["auto", "en", "pl"]
        labels = [_("System default"), "English", "Polski"]
        model = Gtk.StringList.new(labels)
        combo = Gtk.DropDown(model=model)
        current = self.settings.language if self.settings.language in self._language_options else "auto"
        combo.set_selected(self._language_options.index(current))
        combo.connect("notify::selected", self._sync)
        return combo

    # ---------- widget builders ----------

    def _switch(self, active: bool) -> Gtk.Switch:
        sw = Gtk.Switch(active=active, halign=Gtk.Align.END, valign=Gtk.Align.CENTER)
        sw.connect("notify::active", self._sync)
        return sw

    def _build_autosave_combo(self) -> Gtk.DropDown:
        self._autosave_options = ["off", "delay", "focus"]
        labels = [_("Off"), _("After delay"), _("On focus loss")]
        model = Gtk.StringList.new(labels)
        combo = Gtk.DropDown(model=model)
        current = self.settings.autosave if self.settings.autosave in self._autosave_options else "off"
        combo.set_selected(self._autosave_options.index(current))
        combo.connect("notify::selected", self._sync)
        return combo

    def _build_theme_combo(self) -> Gtk.DropDown:
        self._theme_options = ["auto", "light", "dark"]
        labels = [_("Follow system"), _("Light"), _("Dark")]
        model = Gtk.StringList.new(labels)
        combo = Gtk.DropDown(model=model)
        current = self.settings.dark_ui if isinstance(self.settings.dark_ui, str) else (
            "dark" if self.settings.dark_ui else "auto"
        )
        if current in self._theme_options:
            combo.set_selected(self._theme_options.index(current))
        combo.connect("notify::selected", self._sync)
        return combo

    def _build_scheme_combo(self) -> Gtk.DropDown:
        manager = GtkSource.StyleSchemeManager.get_default()
        ids = sorted(manager.get_scheme_ids() or [])
        if not ids:
            ids = ["Adwaita"]
        self._scheme_ids = ids
        model = Gtk.StringList.new(ids)
        combo = Gtk.DropDown(model=model)
        if self.settings.color_scheme in ids:
            combo.set_selected(ids.index(self.settings.color_scheme))
        combo.connect("notify::selected", self._sync)
        return combo

    def _build_font_button(self) -> Gtk.FontDialogButton:
        btn = Gtk.FontDialogButton.new(Gtk.FontDialog.new())
        desc = Pango.FontDescription.from_string(self.settings.font_description())
        btn.set_font_desc(desc)
        btn.connect("notify::font-desc", self._sync)
        return btn

    # ---------- live sync ----------

    def _sync(self, *_: object) -> None:
        if self._suspend:
            return
        self._suspend = True
        try:
            desc = self.font_btn.get_font_desc()
            if desc:
                family = desc.get_family() or self.settings.font
                self.settings.font = family
                size_pango = desc.get_size()
                if size_pango > 0:
                    self.settings.font_size = max(6, int(size_pango / Pango.SCALE))

            idx = self.scheme_combo.get_selected()
            if 0 <= idx < len(self._scheme_ids):
                self.settings.color_scheme = self._scheme_ids[idx]

            theme_idx = self.theme_combo.get_selected()
            if 0 <= theme_idx < len(self._theme_options):
                self.settings.dark_ui = self._theme_options[theme_idx]

            self.settings.tab_width = int(self.tab_spin.get_value())
            self.settings.use_spaces = self.spaces_switch.get_active()
            self.settings.wrap_lines = self.wrap_switch.get_active()
            self.settings.show_line_numbers = self.lineno_switch.get_active()
            self.settings.auto_indent = self.autoindent_switch.get_active()
            self.settings.trim_trailing_whitespace = self.trim_switch.get_active()
            self.settings.markdown_preview_auto = self.md_preview_switch.get_active()

            self.settings.show_sidebar = self.sidebar_switch.get_active()
            self.settings.sidebar_compact = self.compact_switch.get_active()
            raw = self.ignore_entry.get_text()
            self.settings.ignore_patterns = [
                p.strip() for p in raw.split(",") if p.strip()
            ]

            self.settings.register_in_file_manager = self.fm_switch.get_active()
            ai = self.autosave_combo.get_selected()
            if 0 <= ai < len(self._autosave_options):
                self.settings.autosave = self._autosave_options[ai]
            self.settings.autosave_delay_ms = int(self.autosave_delay.get_value())

            li = self.language_combo.get_selected()
            if 0 <= li < len(self._language_options):
                self.settings.language = self._language_options[li]

            self.settings.save()
            self.on_changed(self.settings)
        finally:
            self._suspend = False
