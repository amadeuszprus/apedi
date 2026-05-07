"""Language detection via GtkSourceView's LanguageManager."""

from __future__ import annotations

from pathlib import Path

import gi

gi.require_version("GtkSource", "5")
from gi.repository import Gio, GtkSource  # noqa: E402


_manager: GtkSource.LanguageManager | None = None


def manager() -> GtkSource.LanguageManager:
    global _manager
    if _manager is None:
        _manager = GtkSource.LanguageManager.get_default()
    return _manager


def language_for_path(path: Path | None, content: str | None = None) -> GtkSource.Language | None:
    """Guess language by filename + content type. Returns None when unknown."""
    if path is None:
        return None
    filename = path.name
    content_type = None
    if content is not None:
        sample = content[:4096].encode("utf-8", errors="replace")
        guessed_type, _ = Gio.content_type_guess(filename, sample)
        content_type = guessed_type
    return manager().guess_language(filename, content_type)


def language_id_for_path(path: Path | None, content: str | None = None) -> str | None:
    lang = language_for_path(path, content)
    return lang.get_id() if lang else None
