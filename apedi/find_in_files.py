"""Find and Replace in Files across open project roots, with per-match preview and selection."""

from __future__ import annotations

import builtins
import logging
import os
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

if not hasattr(builtins, "_"):
    builtins._ = lambda s: s  # type: ignore[attr-defined]

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, GLib, GObject, Gio, Gtk  # noqa: E402

from . import file_io
from .ignore_filter import HEAVY_DIRS, IgnoreFilter

log = logging.getLogger(__name__)

_MAX_FILES_SCANNED = 5000
_MAX_RESULTS = 1000
_MAX_FILE_BYTES = 2 * 1024 * 1024  # skip files bigger than 2 MB
_CONTEXT = 60  # characters of the line kept on each side of a match in previews
_PROGRESS_EVERY = 200  # files between progress updates


# ---------- pure search / replace ----------


def compile_query(query: str, *, regex: bool, case_sensitive: bool) -> re.Pattern[str]:
    flags = 0 if case_sensitive else re.IGNORECASE
    try:
        return re.compile(query if regex else re.escape(query), flags)
    except re.error as e:
        raise ValueError(str(e)) from e


def _split_lines(text: str) -> list[tuple[str, str]]:
    """Each line's body and its ending, so CRLF files are written back unchanged."""
    out = []
    for raw in text.split("\n"):
        if raw.endswith("\r"):
            out.append((raw[:-1], "\r"))
        else:
            out.append((raw, ""))
    return out


def find_in_text(text: str, pattern: re.Pattern[str]) -> list[tuple[int, str, list[re.Match[str]]]]:
    """(1-based line, line text, non-empty matches) for every line that matches."""
    hits = []
    for idx, (body, _end) in enumerate(_split_lines(text)):
        matches = [m for m in pattern.finditer(body) if m.end() > m.start()]
        if matches:
            hits.append((idx + 1, body, matches))
    return hits


def replace_in_text(
    text: str,
    pattern: re.Pattern[str],
    replacement: str,
    selected: set[tuple[int, int, int]],
    *,
    use_regex: bool,
) -> tuple[str, int]:
    """Replace only the matches whose (line, start, end) is in `selected`; stale ones are skipped."""
    lines = _split_lines(text)
    wanted_lines = {line for line, _s, _e in selected}
    count = 0
    for idx, (body, ending) in enumerate(lines):
        line_no = idx + 1
        if line_no not in wanted_lines:
            continue
        chosen = [m for m in pattern.finditer(body) if (line_no, m.start(), m.end()) in selected]
        if not chosen:
            continue
        parts = []
        last = 0
        for m in chosen:
            parts.append(body[last:m.start()])
            parts.append(m.expand(replacement) if use_regex else replacement)
            last = m.end()
        parts.append(body[last:])
        lines[idx] = ("".join(parts), ending)
        count += len(chosen)
    return "\n".join(body + ending for body, ending in lines), count


def replace_file(
    path: Path,
    pattern: re.Pattern[str],
    replacement: str,
    selected: set[tuple[int, int, int]],
    *,
    use_regex: bool,
) -> int:
    """Apply the selected replacements on disk in the file's own encoding; returns how many."""
    data = path.read_bytes()
    encoding = file_io.detect_encoding(data)
    text = data.decode(encoding)
    new, count = replace_in_text(text, pattern, replacement, selected, use_regex=use_regex)
    if count:
        path.write_bytes(new.encode(encoding))
    return count


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


def _read_text(path: Path) -> str | None:
    """Text of a searchable file, or None for big, binary or unreadable ones."""
    try:
        if path.stat().st_size > _MAX_FILE_BYTES:
            return None
        data = path.read_bytes()
    except OSError:
        return None
    if file_io.is_binary(data[:4096]):
        return None
    return data.decode(file_io.detect_encoding(data), errors="replace")


@dataclass
class _Hit:
    path: Path
    line_no: int
    line_text: str
    matches: list[re.Match[str]] = field(default_factory=list)


def _scan(
    pattern: re.Pattern[str],
    projects: list[Path],
    extra_patterns: list[str],
    texts: dict[str, str],
    progress: Callable[[int, int], None] = lambda _files, _matches: None,
    cancelled: Callable[[], bool] = lambda: False,
) -> tuple[list[_Hit], bool]:
    """Search every project file off the main thread; `texts` holds the unsaved copies."""
    hits: list[_Hit] = []
    total = scanned = 0
    for full in _iter_text_files(projects, extra_patterns):
        if cancelled():
            return hits, False
        scanned += 1
        if scanned % _PROGRESS_EVERY == 0:
            progress(scanned, total)
        text = texts.get(str(full))
        if text is None and texts:
            text = texts.get(str(full.resolve()))
        if text is None:
            text = _read_text(full)
        if text is None:
            continue
        for line_no, body, matches in find_in_text(text, pattern):
            hits.append(_Hit(full, line_no, body, matches))
            total += len(matches)
            if total >= _MAX_RESULTS:
                return hits, True
    return hits, False


# ---------- previews ----------


def _clip(body: str, start: int, end: int) -> tuple[str, str, str, bool, bool]:
    lo = max(0, start - _CONTEXT)
    hi = min(len(body), end + _CONTEXT)
    return body[lo:start], body[start:end], body[end:hi], lo > 0, hi < len(body)


def _esc(s: str) -> str:
    return GLib.markup_escape_text(s.replace("\t", "    ").replace("\n", "↵"))


def _preview_find(body: str, matches: list[re.Match[str]]) -> str:
    """The line with every match in bold, trimmed around the first one."""
    lo = max(0, matches[0].start() - _CONTEXT)
    hi = min(len(body), matches[-1].end() + _CONTEXT)
    parts = ["…" if lo > 0 else ""]
    last = lo
    for m in matches:
        if m.start() < lo or m.end() > hi:
            continue
        parts.append(_esc(body[last:m.start()]))
        parts.append(f"<b>{_esc(m.group(0))}</b>")
        last = m.end()
    parts.append(_esc(body[last:hi]))
    parts.append("…" if hi < len(body) else "")
    return "".join(parts)


def _preview_replace(body: str, m: re.Match[str], new: str) -> str:
    before, old, after, cut_left, cut_right = _clip(body, m.start(), m.end())
    return (
        ("…" if cut_left else "")
        + _esc(before)
        + f'<span strikethrough="true" alpha="60%">{_esc(old)}</span>'
        + f'<span weight="bold" foreground="#2e9e5b">{_esc(new)}</span>'
        + _esc(after)
        + ("…" if cut_right else "")
    )


class _ResultRow(GObject.Object):
    __gtype_name__ = "ApediFiFRow"
    label = GObject.Property(type=str, default="")
    path_str = GObject.Property(type=str, default="")
    line = GObject.Property(type=int, default=0)
    start = GObject.Property(type=int, default=0)
    end = GObject.Property(type=int, default=0)
    is_header = GObject.Property(type=bool, default=False)
    checked = GObject.Property(type=bool, default=True)


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
        all_projects: list[Path] | None = None,
        open_texts: Callable[[], dict[str, str]] | None = None,
        apply_to_buffer: Callable[[Path, str], bool] | None = None,
    ) -> None:
        title = _("Replace in Files") if with_replace else _("Find in Files")
        super().__init__(
            title=title,
            transient_for=parent, modal=True,
            default_width=760, default_height=580,
        )
        self.set_destroy_with_parent(True)
        self.projects = projects
        self.extra_patterns = extra_patterns
        self.on_chosen = on_chosen
        self.with_replace = with_replace
        self._open_texts = open_texts or dict
        self._apply_to_buffer = apply_to_buffer
        self._texts: dict[str, str] = {}
        self._cancel = threading.Event()
        self._searching = False
        self._pattern: re.Pattern[str] | None = None
        self._rows_by_file: dict[str, list[_ResultRow]] = {}
        self._headers: dict[str, _ResultRow] = {}
        self._syncing = False
        # Project switcher is only shown when the caller passes the full project
        # list AND there is no forced scope (right-click "search this folder"
        # uses scope_label and shouldn't override the user's explicit target).
        show_project_switcher = (
            all_projects is not None and len(all_projects) > 1 and not scope_label
        )
        self._all_projects: list[Path] = list(all_projects) if all_projects else []

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

        if show_project_switcher:
            scope_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            scope_row.append(Gtk.Label(label=_("In:"), xalign=0))
            labels = [_("All open projects")]
            labels.extend(p.name or str(p) for p in self._all_projects)
            self.project_dropdown = Gtk.DropDown.new_from_strings(labels)
            self.project_dropdown.set_hexpand(True)
            initial_index = 0
            if len(projects) == 1:
                try:
                    initial_index = self._all_projects.index(projects[0]) + 1
                except ValueError:
                    initial_index = 0
            self.project_dropdown.set_selected(initial_index)
            self.project_dropdown.connect("notify::selected", self._on_project_changed)
            scope_row.append(self.project_dropdown)
            outer.append(scope_row)
        else:
            self.project_dropdown = None

        controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.entry = Gtk.SearchEntry()
        placeholder = _("Find…") if with_replace else _("Search across open projects…")
        self.entry.set_placeholder_text(placeholder)
        self.entry.set_hexpand(True)
        self.entry.connect("activate", lambda *_: self._run())
        controls.append(self.entry)

        self.regex_btn = Gtk.ToggleButton(label=".*")
        self.regex_btn.set_tooltip_text(_("Regular expression"))
        self.regex_btn.connect("toggled", lambda *_: self._rerun_if_searched())
        controls.append(self.regex_btn)

        self.case_btn = Gtk.ToggleButton(label="Aa")
        self.case_btn.set_tooltip_text(_("Match case"))
        self.case_btn.connect("toggled", lambda *_: self._rerun_if_searched())
        controls.append(self.case_btn)

        self.run_btn = Gtk.Button.new_with_label(_("Search"))
        self.run_btn.add_css_class("suggested-action")
        self.run_btn.connect("clicked", lambda *_: self._stop() if self._searching else self._run())
        controls.append(self.run_btn)
        outer.append(controls)

        if with_replace:
            replace_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            self.replace_entry = Gtk.Entry()
            self.replace_entry.set_placeholder_text(_("Replace with…"))
            self.replace_entry.set_hexpand(True)
            self.replace_entry.connect("changed", lambda *_: self._rerun_if_searched())
            self.replace_entry.connect("activate", lambda *_: self._run())
            replace_row.append(self.replace_entry)
            self.replace_btn = Gtk.Button.new_with_label(_("Replace Selected"))
            self.replace_btn.add_css_class("destructive-action")
            self.replace_btn.set_sensitive(False)
            self.replace_btn.connect("clicked", lambda *_: self._confirm_replace())
            replace_row.append(self.replace_btn)
            outer.append(replace_row)
        else:
            self.replace_entry = None
            self.replace_btn = None

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
        factory.connect("unbind", self._unbind_row)
        self.list_view.set_factory(factory)
        scrolled.set_child(self.list_view)
        outer.append(scrolled)

        self.connect("close-request", lambda *_: self._cancel.set() or False)
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

    def _on_project_changed(self, dropdown: Gtk.DropDown, _pspec: object) -> None:
        idx = dropdown.get_selected()
        if idx == 0:
            self.projects = list(self._all_projects)
        else:
            self.projects = [self._all_projects[idx - 1]]
        if self.entry.get_text():
            self._run()

    def focus_replace_entry(self) -> None:
        if self.replace_entry is not None:
            self.replace_entry.grab_focus()

    # ---------- rows ----------

    def _setup_row(self, _factory, item: Gtk.ListItem) -> None:
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8,
                      margin_start=6, margin_end=8, margin_top=2, margin_bottom=2)
        check = Gtk.CheckButton()
        check.set_visible(self.with_replace)
        box.append(check)
        line_label = Gtk.Label(xalign=1)
        line_label.set_size_request(44, -1)
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
        check = box.get_first_child()
        line_label = check.get_next_sibling()
        text_label = line_label.get_next_sibling()
        if row.is_header:
            line_label.set_text("")
            text_label.set_markup(f"<b>{GLib.markup_escape_text(row.label)}</b>")
            # Headers are paths, so cut from the left and keep the file name visible.
            text_label.set_ellipsize(1)
        else:
            line_label.set_text(str(row.line))
            text_label.set_markup(row.label)
            text_label.set_ellipsize(3)
        if self.with_replace:
            item._binding = row.bind_property(  # type: ignore[attr-defined]
                "checked", check, "active",
                GObject.BindingFlags.BIDIRECTIONAL | GObject.BindingFlags.SYNC_CREATE,
            )

    def _unbind_row(self, _factory, item: Gtk.ListItem) -> None:
        binding = getattr(item, "_binding", None)
        if binding is not None:
            binding.unbind()
            item._binding = None  # type: ignore[attr-defined]

    def _on_checked(self, row: _ResultRow, _pspec: object) -> None:
        if self._syncing:
            return
        self._syncing = True
        try:
            hits = self._rows_by_file.get(row.path_str, [])
            if row.is_header:
                for hit in hits:
                    hit.checked = row.checked
            else:
                header = self._headers.get(row.path_str)
                if header is not None:
                    header.checked = any(h.checked for h in hits)
        finally:
            self._syncing = False
        self._update_selection_summary()

    # ---------- search ----------

    def _rerun_if_searched(self) -> None:
        if self.entry.get_text() and self.store.get_n_items() > 0:
            self._run()

    def _run(self) -> None:
        """Search in a worker thread; the dialog stays responsive and can be stopped."""
        query = self.entry.get_text()
        self._stop()
        self.store.remove_all()
        self._rows_by_file.clear()
        self._headers.clear()
        self._pattern = None
        if self.replace_btn is not None:
            self.replace_btn.set_sensitive(False)
        if not query:
            self.summary.set_text("")
            return
        try:
            pattern = compile_query(
                query, regex=self.regex_btn.get_active(), case_sensitive=self.case_btn.get_active(),
            )
        except ValueError as e:
            self._error(str(e))
            return
        # Unsaved buffers are read here, on the main thread, and handed to the worker.
        self._texts = self._open_texts()
        self._cancel = threading.Event()
        self._searching = True
        self.run_btn.set_label(_("Stop"))
        self.summary.set_text(_("Searching…"))
        cancel = self._cancel
        worker = threading.Thread(
            target=self._search,
            args=(pattern, list(self.projects), list(self.extra_patterns), dict(self._texts), cancel),
            daemon=True,
        )
        worker.start()

    def _search(
        self,
        pattern: re.Pattern[str],
        projects: list[Path],
        extra_patterns: list[str],
        texts: dict[str, str],
        cancel: threading.Event,
    ) -> None:
        def progress(files: int, matches: int) -> None:
            GLib.idle_add(self._on_progress, files, matches, cancel)

        try:
            hits, truncated = _scan(
                pattern, projects, extra_patterns, texts, progress, cancel.is_set,
            )
        except Exception as e:  # noqa: BLE001
            log.exception("search failed")
            GLib.idle_add(self._on_failed, str(e), cancel)
            return
        GLib.idle_add(self._on_found, pattern, hits, truncated, cancel)

    def _on_progress(self, files: int, matches: int, cancel: threading.Event) -> bool:
        if cancel.is_set() or not self._searching:
            return False
        self.summary.set_text(
            _("Searching… {files} files, {matches} matches").format(files=files, matches=matches)
        )
        return False

    def _on_failed(self, message: str, cancel: threading.Event) -> bool:
        if not cancel.is_set():
            self._finish_search()
            self._error(message)
        return False

    def _on_found(
        self, pattern: re.Pattern[str], hits: list[_Hit], truncated: bool, cancel: threading.Event,
    ) -> bool:
        if cancel.is_set():
            return False
        self._finish_search()
        try:
            rows = self._build_rows(hits)
        except (re.error, IndexError) as e:
            self._error(str(e))
            return False
        self._pattern = pattern
        for row in rows:
            self.store.append(row)
        files = len(self._headers)
        count = sum(len(h.matches) for h in hits)
        plural = _("matches") if count != 1 else _("match")
        files_word = _("files") if files != 1 else _("file")
        text = f"{count} {plural} in {files} {files_word}"
        if truncated:
            text += " " + _("(showing the first {n})").format(n=_MAX_RESULTS)
        self._found_text = text
        self._update_selection_summary()
        return False

    def _finish_search(self) -> None:
        self._searching = False
        self.run_btn.set_label(_("Search"))

    def _stop(self) -> None:
        if not self._searching:
            return
        self._cancel.set()
        self._finish_search()
        self.summary.set_text(_("Search stopped"))

    def _build_rows(self, hits: list[_Hit]) -> list[_ResultRow]:
        replacement = self.replace_entry.get_text() if self.replace_entry is not None else ""
        use_regex = self.regex_btn.get_active()
        rows: list[_ResultRow] = []
        for hit in hits:
            key = str(hit.path)
            if key not in self._headers:
                header = _ResultRow(is_header=True, label=self._display_path(hit.path), path_str=key)
                header.connect("notify::checked", self._on_checked)
                self._headers[key] = header
                self._rows_by_file[key] = []
                rows.append(header)
            if not self.with_replace:
                row = _ResultRow(
                    label=_preview_find(hit.line_text, hit.matches), path_str=key, line=hit.line_no,
                )
                rows.append(row)
                continue
            for m in hit.matches:
                new = m.expand(replacement) if use_regex else replacement
                row = _ResultRow(
                    label=_preview_replace(hit.line_text, m, new), path_str=key,
                    line=hit.line_no, start=m.start(), end=m.end(),
                )
                row.connect("notify::checked", self._on_checked)
                self._rows_by_file[key].append(row)
                rows.append(row)
        return rows

    def _display_path(self, path: Path) -> str:
        for root in self._all_projects or self.projects:
            if root.is_dir():
                try:
                    return f"{root.name}/{path.relative_to(root)}"
                except ValueError:
                    continue
        return str(path)

    def _selected(self) -> dict[str, set[tuple[int, int, int]]]:
        out: dict[str, set[tuple[int, int, int]]] = {}
        for key, rows in self._rows_by_file.items():
            chosen = {(r.line, r.start, r.end) for r in rows if r.checked}
            if chosen:
                out[key] = chosen
        return out

    def _update_selection_summary(self) -> None:
        text = getattr(self, "_found_text", "")
        if self.with_replace and self._rows_by_file:
            total = sum(len(rows) for rows in self._rows_by_file.values())
            chosen = sum(len(s) for s in self._selected().values())
            text += " · " + _("{n} of {total} selected").format(n=chosen, total=total)
            if self.replace_btn is not None:
                self.replace_btn.set_sensitive(chosen > 0)
        self.summary.set_text(text)

    def _error(self, message: str) -> None:
        self.summary.set_markup(f"<span color='red'>{GLib.markup_escape_text(message)}</span>")

    def _on_row_activate(self, _view, position: int) -> None:
        row: _ResultRow = self.store.get_item(position)
        if row is None or row.is_header:
            return
        self.on_chosen(Path(row.path_str), row.line)

    # ---------- replace ----------

    def _confirm_replace(self) -> None:
        if not self.with_replace or self.replace_entry is None or self._pattern is None:
            return
        selected = self._selected()
        if not selected:
            return
        count = sum(len(s) for s in selected.values())
        dialog = Gtk.AlertDialog()
        dialog.set_message(_("Replace {n} selected matches?").format(n=count))
        dialog.set_detail(_(
            "Files open in a tab are changed in the editor and left unsaved, so you can undo. "
            "The others are rewritten on disk."
        ))
        dialog.set_buttons([_("Cancel"), _("Replace")])
        dialog.set_default_button(1)
        dialog.set_cancel_button(0)

        def on_response(dlg: Gtk.AlertDialog, result: Gio.AsyncResult) -> None:
            try:
                button = dlg.choose_finish(result)
            except GLib.Error:
                return
            if button == 1:
                self._do_replace(selected)

        dialog.choose(self, None, on_response)

    def _do_replace(self, selected: dict[str, set[tuple[int, int, int]]]) -> None:
        pattern = self._pattern
        self._texts = self._open_texts()
        replacement = self.replace_entry.get_text()
        use_regex = self.regex_btn.get_active()
        total = files_changed = in_tabs = 0
        failed: list[str] = []
        for key, chosen in selected.items():
            path = Path(key)
            try:
                text = self._texts.get(str(path))
                if text is not None and self._apply_to_buffer is not None:
                    new, n = replace_in_text(text, pattern, replacement, chosen, use_regex=use_regex)
                    if n and not self._apply_to_buffer(path, new):
                        n = 0
                    if n:
                        in_tabs += 1
                else:
                    n = replace_file(path, pattern, replacement, chosen, use_regex=use_regex)
            except (OSError, UnicodeError, re.error, IndexError) as e:
                log.warning("replace failed for %s: %s", path, e)
                failed.append(path.name)
                continue
            if n:
                total += n
                files_changed += 1
        self._run()
        message = _("Replaced {n} in {f} files").format(n=total, f=files_changed)
        if in_tabs:
            message += " · " + _("{t} open in tabs, not saved yet").format(t=in_tabs)
        if failed:
            message += " · " + _("failed: {names}").format(names=", ".join(failed))
        self._found_text = message
        self.summary.set_text(message)
