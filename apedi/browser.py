"""Opening HTML files in the desktop's browser, kept free of GTK for testing."""

from __future__ import annotations

from pathlib import Path

HTML_EXTENSIONS = {".html", ".htm", ".xhtml"}


def is_html_path(path: Path | None) -> bool:
    return path is not None and path.suffix.lower() in HTML_EXTENSIONS


def handler_is_self(handler_id: str | None, app_id: str) -> bool:
    """Whether a default-handler desktop id is Apedi itself, packaged as a snap or not."""
    if not handler_id:
        return False
    stem = handler_id.lower().removesuffix(".desktop")
    return stem in {app_id.lower(), "apedi_apedi", "apedi"}
