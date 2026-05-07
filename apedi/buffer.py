"""EditorBuffer — GtkSource.Buffer subclass tracking file metadata."""

from __future__ import annotations

from pathlib import Path

import gi

gi.require_version("GtkSource", "5")
from gi.repository import GObject, GtkSource  # noqa: E402

from . import languages


class EditorBuffer(GtkSource.Buffer):
    __gtype_name__ = "ApediEditorBuffer"

    def __init__(self) -> None:
        super().__init__()
        self._path: Path | None = None
        self._encoding: str = "utf-8"
        self._mtime_at_load: float | None = None
        self.set_highlight_matching_brackets(True)

    @GObject.Property(type=str, default="")
    def path_str(self) -> str:
        return str(self._path) if self._path else ""

    @property
    def path(self) -> Path | None:
        return self._path

    @path.setter
    def path(self, value: Path | None) -> None:
        self._path = value
        self.notify("path-str")

    @property
    def encoding(self) -> str:
        return self._encoding

    @encoding.setter
    def encoding(self, value: str) -> None:
        self._encoding = value

    @property
    def mtime_at_load(self) -> float | None:
        return self._mtime_at_load

    @mtime_at_load.setter
    def mtime_at_load(self, value: float | None) -> None:
        self._mtime_at_load = value

    def display_name(self) -> str:
        if self._path is None:
            return "Untitled"
        return self._path.name

    def detect_language(self) -> None:
        """Re-run language detection based on current path + content."""
        text = self.get_text(self.get_start_iter(), self.get_end_iter(), False)
        lang = languages.language_for_path(self._path, text)
        self.set_language(lang)

    def load(self, text: str, path: Path | None, encoding: str, mtime: float | None) -> None:
        """Replace contents and metadata. Does not mark dirty."""
        self.begin_irreversible_action()
        self.set_text(text)
        self.end_irreversible_action()
        self._path = path
        self._encoding = encoding
        self._mtime_at_load = mtime
        self.set_modified(False)
        self.detect_language()
        self.notify("path-str")

    def get_full_text(self) -> str:
        return self.get_text(self.get_start_iter(), self.get_end_iter(), False)

    def replace_text_preserving_cursor(self, new_text: str) -> None:
        """Replace whole text in single undo group, keep cursor on same line."""
        line = self.get_iter_at_mark(self.get_insert()).get_line()
        self.begin_user_action()
        self.set_text(new_text)
        line_count = self.get_line_count()
        target_line = min(line, line_count - 1) if line_count > 0 else 0
        target_iter = self.get_iter_at_line(target_line)[1]
        self.place_cursor(target_iter)
        self.end_user_action()
