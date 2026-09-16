"""GTK side of the git decorations: the gutter change bar and the background tracker."""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("GtkSource", "5")
from gi.repository import Gdk, Gio, GLib, Graphene, Gtk, GtkSource  # noqa: E402

from . import gitstate
from .gitstate import EMPTY_MARKS, LineMarks, RepoStatus

log = logging.getLogger(__name__)

# Between the line numbers (-30) and the text; marks sit at -20.
GUTTER_POSITION = -10
_BAR_WIDTH = 3
_DELETED_BAR_HEIGHT = 2

# Same hues as the sidebar colours in style.py, tuned per background.
_COLOURS = {
    False: {"added": "#2e9e5b", "modified": "#c8931b", "deleted": "#d64545"},
    True: {"added": "#81b88b", "modified": "#e2c08d", "deleted": "#e06c6c"},
}

# A rebase or checkout touches .git dozens of times in a burst.
REPO_CHANGE_DEBOUNCE_MS = 500


def _rgba(spec: str) -> Gdk.RGBA:
    rgba = Gdk.RGBA()
    rgba.parse(spec)
    return rgba


class ChangeGutterRenderer(GtkSource.GutterRenderer):
    """A thin bar per changed line: green added, amber modified, red where a block was removed."""

    __gtype_name__ = "ApediChangeGutterRenderer"

    def __init__(self) -> None:
        super().__init__()
        self.set_size_request(_BAR_WIDTH + 1, -1)
        self._marks: LineMarks = EMPTY_MARKS
        self._colours = {k: _rgba(v) for k, v in _COLOURS[False].items()}

    def set_dark(self, dark: bool) -> None:
        self._colours = {k: _rgba(v) for k, v in _COLOURS[bool(dark)].items()}
        self.queue_draw()

    def set_marks(self, marks: LineMarks) -> None:
        if marks == self._marks:
            return
        self._marks = marks
        self.queue_draw()

    def do_snapshot_line(
        self, snapshot: Gtk.Snapshot, lines: GtkSource.GutterLines, line: int,
    ) -> None:
        marks = self._marks
        if marks.is_empty():
            return
        y, height = lines.get_line_yrange(line, GtkSource.GutterRendererAlignmentMode.CELL)
        if line in marks.added:
            snapshot.append_color(
                self._colours["added"], Graphene.Rect().init(0, y, _BAR_WIDTH, height),
            )
        elif line in marks.modified:
            snapshot.append_color(
                self._colours["modified"], Graphene.Rect().init(0, y, _BAR_WIDTH, height),
            )
        if line in marks.deleted:
            snapshot.append_color(
                self._colours["deleted"],
                Graphene.Rect().init(0, y, _BAR_WIDTH, _DELETED_BAR_HEIGHT),
            )
        buffer = self.get_buffer()
        if (
            buffer is not None
            and line == buffer.get_line_count() - 1
            and (line + 1) in marks.deleted
        ):
            # Removed after the last line: the gap has no line below it.
            snapshot.append_color(
                self._colours["deleted"],
                Graphene.Rect().init(
                    0, y + height - _DELETED_BAR_HEIGHT, _BAR_WIDTH, _DELETED_BAR_HEIGHT,
                ),
            )


class GitTracker:
    """Runs git off the main thread and watches each repository's .git directory."""

    def __init__(self) -> None:
        self.on_repo_changed: Callable[[], None] | None = None
        self._monitors: dict[str, Gio.FileMonitor] = {}
        self._debounce_id: int | None = None
        # Generation counters drop results overtaken by a newer request.
        self._status_gen: dict[str, int] = {}

    # ---------- async git ----------

    def refresh_status(
        self, project: Path, on_done: Callable[[Path, RepoStatus | None], None],
    ) -> None:
        key = str(project)
        gen = self._status_gen.get(key, 0) + 1
        self._status_gen[key] = gen

        def work() -> None:
            result = gitstate.status(project)

            def deliver() -> bool:
                if self._status_gen.get(key) != gen:
                    return False
                if result is not None and result.git_dir is not None:
                    self._watch(result.git_dir)
                on_done(project, result)
                return False

            GLib.idle_add(deliver)

        threading.Thread(target=work, name="apedi-git-status", daemon=True).start()

    def fetch_baseline(
        self, path: Path, encoding: str, on_done: Callable[[str | None], None],
    ) -> None:
        """HEAD's copy of `path` delivered on the main loop, None when there is none."""

        def work() -> None:
            root = gitstate.repo_root(path)
            text = gitstate.head_text(root, path, encoding) if root is not None else None
            GLib.idle_add(lambda: (on_done(text), False)[1])

        threading.Thread(target=work, name="apedi-git-baseline", daemon=True).start()

    # ---------- .git watching ----------

    def _watch(self, git_dir: Path) -> None:
        key = str(git_dir)
        if key in self._monitors:
            return
        gfile = Gio.File.new_for_path(key)
        try:
            monitor = gfile.monitor_directory(Gio.FileMonitorFlags.NONE, None)
        except GLib.GError as e:
            log.debug("cannot watch %s: %s", git_dir, e)
            return
        monitor.connect("changed", self._on_git_dir_changed)
        self._monitors[key] = monitor

    def _on_git_dir_changed(self, _monitor, file: Gio.File, _other, event) -> None:
        if event not in (
            Gio.FileMonitorEvent.CHANGES_DONE_HINT,
            Gio.FileMonitorEvent.CREATED,
            Gio.FileMonitorEvent.DELETED,
            Gio.FileMonitorEvent.MOVED_IN,
            Gio.FileMonitorEvent.RENAMED,
        ):
            return
        name = file.get_basename() or ""
        if name.endswith(".lock"):
            return
        if self._debounce_id is not None:
            GLib.source_remove(self._debounce_id)
        self._debounce_id = GLib.timeout_add(REPO_CHANGE_DEBOUNCE_MS, self._fire_repo_changed)

    def _fire_repo_changed(self) -> bool:
        self._debounce_id = None
        if self.on_repo_changed is not None:
            self.on_repo_changed()
        return False

    def clear(self) -> None:
        """Stop watching everything; used when the decorations are switched off."""
        for monitor in self._monitors.values():
            monitor.cancel()
        self._monitors.clear()
        self._status_gen.clear()
        if self._debounce_id is not None:
            GLib.source_remove(self._debounce_id)
            self._debounce_id = None
