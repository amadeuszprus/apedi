"""Find in Files — text search across all open project roots."""

from __future__ import annotations

import builtins
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

if not hasattr(builtins, "_"):
    builtins._ = lambda s: s  # type: ignore[attr-defined]

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, GLib, GObject, Gio, Gtk  # noqa: E402

from .ignore_filter import HEAVY_DIRS, IgnoreFilter

log = logging.getLogger(__name__)

_MAX_FILES_SCANNED = 5000
_MAX_RESULTS = 1000
_MAX_FILE_BYTES = 2 * 1024 * 1024  # skip files bigger than 2 MB
_BINARY_NULL_BYTE_THRESHOLD = 1


@dataclass
class _Hit:
    path: Path
    line_no: int
    line_text: str


class _ResultRow(GObject.Object):
    __gtype_name__ = "ApediFiFRow"
    label = GObject.Property(type=str, default="")
    path_str = GObject.Property(type=str, default="")
    line = GObject.Property(type=int, default=0)
    is_header = GObject.Property(type=bool, default=False)


def _iter_text_files(projects: list[Path], extra_patterns: list[str]):
    seen = 0
    for project in projects:
        if project.is_file():
            yield project
            seen += 1
            if seen >= _MAX_FILES_SCANNED:
                return
            continue
        if not project.is_dir():
            continue
        ignore = IgnoreFilter(project, extra_patterns)
        for root, dirs, files in os.walk(project, followlinks=False):
            dirs[:] = [
                d for d in dirs
                if d not in HEAVY_DIRS
                and not d.startswith(".")
                and not ignore.is_ignored(Path(root) / d)
            ]
            for fname in files:
                if fname.startswith("."):
                    continue
                full = Path(root) / fname
                if ignore.is_ignored(full):
                    continue
                yield full
                seen += 1
                if seen >= _MAX_FILES_SCANNED:
                    return


def _looks_binary(sample: bytes) -> bool:
    return sample.count(b"\x00") >= _BINARY_NULL_BYTE_THRESHOLD


def _scan(query: str, projects: list[Path], extra_patterns: list[str],
          regex: bool, case_sensitive: bool) -> list[_Hit]:
    if not query:
        return []
    flags = 0 if case_sensitive else re.IGNORECASE
    if regex:
        try:
            pattern = re.compile(query, flags)
        except re.error as e:
            raise ValueError(str(e))
    else:
        pattern = re.compile(re.escape(query), flags)

    hits: list[_Hit] = []
    for full in _iter_text_files(projects, extra_patterns):
        try:
            stat = full.stat()
        except OSError:
            continue
        if stat.st_size > _MAX_FILE_BYTES:
            continue
        try:
            with full.open("rb") as f:
                head = f.read(4096)
        except OSError:
            continue
        if _looks_binary(head):
            continue
        try:
            text = full.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if pattern.search(line):
                hits.append(_Hit(full, i, line.rstrip()[:240]))
                if len(hits) >= _MAX_RESULTS:
                    return hits
    return hits


class FindInFilesDialog(Gtk.Window):
    __gtype_name__ = "ApediFindInFilesDialog"

    def __init__(
        self,
        parent: Gtk.Window,
        projects: list[Path],
        extra_patterns: list[str],
        on_chosen: Callable[[Path, int], None],
        *,
        with_replace: bool = False,
        scope_label: str | None = None,
        initial_query: str = "",
    ) -> None:
        title = _("Replace in Files") if with_replace else _("Find in Files")
        super().__init__(
            title=title,
            transient_for=parent, modal=True,
            default_width=720, default_height=560,
        )
        self.set_destroy_with_parent(True)
        self.set_resizable(False)
        self.projects = projects
        self.extra_patterns = extra_patterns
        self.on_chosen = on_chosen
        self.with_replace = with_replace

        key_ctrl = Gtk.EventControllerKey()
        key_ctrl.connect("key-pressed", self._on_key_pressed)
        self.add_controller(key_ctrl)

        outer = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=8,
            margin_top=10, margin_bottom=10, margin_start=12, margin_end=12,
        )

        if scope_label:
            scope = Gtk.Label(xalign=0)
            scope.add_css_class("dim-label")
            scope.set_text(_("Scope: {label}").format(label=scope_label))
            outer.append(scope)

        controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.entry = Gtk.SearchEntry()
        placeholder = _("Find…") if with_replace else _("Search across open projects…")
        self.entry.set_placeholder_text(placeholder)
        self.entry.set_hexpand(True)
        self.entry.connect("activate", lambda *_: self._run())
        controls.append(self.entry)

        self.regex_btn = Gtk.ToggleButton(label=".*")
        self.regex_btn.set_tooltip_text(_("Regular expression"))
        controls.append(self.regex_btn)

        self.case_btn = Gtk.ToggleButton(label="Aa")
        self.case_btn.set_tooltip_text(_("Match case"))
        controls.append(self.case_btn)

        run_btn = Gtk.Button.new_with_label(_("Search"))
        run_btn.add_css_class("suggested-action")
        run_btn.connect("clicked", lambda *_: self._run())
        controls.append(run_btn)
        outer.append(controls)

        if with_replace:
            replace_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            self.replace_entry = Gtk.Entry()
            self.replace_entry.set_placeholder_text(_("Replace with…"))
            self.replace_entry.set_hexpand(True)
            replace_row.append(self.replace_entry)
            replace_btn = Gtk.Button.new_with_label(_("Replace All"))
            replace_btn.add_css_class("destructive-action")
            replace_btn.connect("clicked", lambda *_: self._confirm_replace_all())
            replace_row.append(replace_btn)
            outer.append(replace_row)
        else:
            self.replace_entry = None

        self.summary = Gtk.Label(xalign=0)
        self.summary.add_css_class("dim-label")
        outer.append(self.summary)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.add_css_class("frame")

        self.store = Gio.ListStore.new(_ResultRow)
        self.selection = Gtk.SingleSelection.new(self.store)
        self.list_view = Gtk.ListView()
        self.list_view.set_single_click_activate(True)
        self.list_view.set_model(self.selection)
        self.list_view.connect("activate", self._on_row_activate)

        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", self._setup_row)
        factory.connect("bind", self._bind_row)
        self.list_view.set_factory(factory)
        scrolled.set_child(self.list_view)
        outer.append(scrolled)

        self.set_child(outer)
        if initial_query:
            self.entry.set_text(initial_query)
            GLib.idle_add(lambda: (self._run(), False)[1])
        self.entry.grab_focus()
        self.entry.select_region(0, -1)

    def _on_key_pressed(
        self, _ctrl: Gtk.EventControllerKey, keyval: int, _keycode: int, _state: int,
    ) -> bool:
        if keyval == Gdk.KEY_Escape:
            self.close()
            return True
        return False

    def focus_replace_entry(self) -> None:
        if self.replace_entry is not None:
            self.replace_entry.grab_focus()

    def _setup_row(self, _factory, item: Gtk.ListItem) -> None:
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10,
                      margin_start=8, margin_end=8, margin_top=2, margin_bottom=2)
        line_label = Gtk.Label(xalign=1)
        line_label.set_size_request(50, -1)
        line_label.add_css_class("dim-label")
        box.append(line_label)
        text_label = Gtk.Label(xalign=0)
        text_label.set_hexpand(True)
        text_label.set_ellipsize(3)
        box.append(text_label)
        item.set_child(box)

    def _bind_row(self, _factory, item: Gtk.ListItem) -> None:
        row: _ResultRow = item.get_item()
        box: Gtk.Box = item.get_child()
        line_label = box.get_first_child()
        text_label = line_label.get_next_sibling()
        if row.is_header:
            line_label.set_text("")
            text_label.set_markup(f"<b>{GLib.markup_escape_text(row.label)}</b>")
        else:
            line_label.set_text(str(row.line))
            text_label.set_text(row.label)

    def _run(self) -> None:
        query = self.entry.get_text()
        try:
            hits = _scan(
                query, self.projects, self.extra_patterns,
                self.regex_btn.get_active(), self.case_btn.get_active(),
            )
        except ValueError as e:
            self.summary.set_markup(f"<span color='red'>{GLib.markup_escape_text(str(e))}</span>")
            return
        self.store.remove_all()
        if not query:
            self.summary.set_text("")
            return
        # group by file
        grouped: dict[Path, list[_Hit]] = {}
        for h in hits:
            grouped.setdefault(h.path, []).append(h)
        for path, items in grouped.items():
            header = _ResultRow()
            header.is_header = True
            header.label = str(path)
            header.path_str = str(path)
            self.store.append(header)
            for h in items:
                row = _ResultRow()
                row.is_header = False
                row.label = h.line_text
                row.path_str = str(h.path)
                row.line = h.line_no
                self.store.append(row)
        plural = _("matches") if len(hits) != 1 else _("match")
        files_word = _("files") if len(grouped) != 1 else _("file")
        self.summary.set_text(f"{len(hits)} {plural} in {len(grouped)} {files_word}")

    def _on_row_activate(self, _view, position: int) -> None:
        row: _ResultRow = self.store.get_item(position)
        if row is None or row.is_header:
            return
        self.on_chosen(Path(row.path_str), row.line)

    def _confirm_replace_all(self) -> None:
        if not self.with_replace or self.replace_entry is None:
            return
        query = self.entry.get_text()
        if not query:
            self.summary.set_markup(
                f"<span color='red'>{GLib.markup_escape_text(_('Enter a query first'))}</span>"
            )
            return
        replacement = self.replace_entry.get_text()
        dialog = Gtk.AlertDialog()
        dialog.set_message(_("Replace all matches?"))
        dialog.set_detail(
            _("This rewrites files on disk and cannot be undone. Continue?")
        )
        dialog.set_buttons([_("Cancel"), _("Replace")])
        dialog.set_default_button(1)
        dialog.set_cancel_button(0)

        def on_response(dlg: Gtk.AlertDialog, result: Gio.AsyncResult) -> None:
            try:
                button = dlg.choose_finish(result)
            except GLib.Error:
                return
            if button != 1:
                return
            self._do_replace_all(query, replacement)

        dialog.choose(self, None, on_response)

    def _do_replace_all(self, query: str, replacement: str) -> None:
        flags = 0 if self.case_btn.get_active() else re.IGNORECASE
        try:
            if self.regex_btn.get_active():
                pattern = re.compile(query, flags)
                use_regex = True
            else:
                pattern = re.compile(re.escape(query), flags)
                use_regex = False
        except re.error as e:
            self.summary.set_markup(
                f"<span color='red'>{GLib.markup_escape_text(str(e))}</span>"
            )
            return
        total = 0
        files_changed = 0
        for full in _iter_text_files(self.projects, self.extra_patterns):
            try:
                stat = full.stat()
            except OSError:
                continue
            if stat.st_size > _MAX_FILE_BYTES:
                continue
            try:
                with full.open("rb") as f:
                    head = f.read(4096)
            except OSError:
                continue
            if _looks_binary(head):
                continue
            try:
                text = full.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if use_regex:
                new_text, n = pattern.subn(replacement, text)
            else:
                new_text, n = pattern.subn(
                    replacement.replace("\\", "\\\\"), text,
                )
            if n == 0 or new_text == text:
                continue
            try:
                full.write_text(new_text, encoding="utf-8")
            except OSError as e:
                log.warning("write failed for %s: %s", full, e)
                continue
            total += n
            files_changed += 1
        files_word = _("files") if files_changed != 1 else _("file")
        self.summary.set_text(
            _("Replaced {n} occurrence(s) in {f} {files_word}").format(
                n=total, f=files_changed, files_word=files_word,
            )
        )
        self._run()
