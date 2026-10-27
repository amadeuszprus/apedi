"""Lightweight Markdown path detection shared by startup and the renderer."""

from pathlib import Path

MD_EXTENSIONS = {".md", ".markdown", ".mdown", ".mkd", ".mkdn"}


def is_markdown_path(path: Path | None) -> bool:
    if path is None:
        return False
    return path.suffix.lower() in MD_EXTENSIONS
