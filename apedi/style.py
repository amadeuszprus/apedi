"""Per-extension colors for the sidebar — applied via a global CSS provider."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, Gtk  # noqa: E402


_CSS = b"""
.file-py    { color: #4b86c2; }
.file-js    { color: #d4a017; }
.file-ts    { color: #2f74c0; }
.file-rust  { color: #d97706; }
.file-go    { color: #0891b2; }
.file-md    { color: #8b9aa8; }
.file-html  { color: #e34c26; }
.file-css   { color: #a78bfa; }
.file-json  { color: #84cc16; }
.file-yaml  { color: #84cc16; }
.file-toml  { color: #84cc16; }
.file-c     { color: #5b6dca; }
.file-cpp   { color: #5b6dca; }
.file-java  { color: #b07219; }
.file-sh    { color: #22c55e; }
.file-rb    { color: #d63a24; }
.file-php   { color: #6f7eb3; }
.file-img   { color: #ec4899; }
.file-archive { color: #f59e0b; }
.file-other { /* default */ }

/* Ignored entries (gitignore / heavy dirs / user patterns) */
.file-ignored { opacity: 0.45; font-style: italic; }
.file-heavy   { opacity: 0.55; }

/* Compact sidebar density */
.sidebar-compact listview > row { padding-top: 1px; padding-bottom: 1px; min-height: 18px; }
.sidebar-compact listview > row > * { padding-top: 0; padding-bottom: 0; }
.sidebar-compact label { font-size: 0.92em; }
.sidebar-compact image { -gtk-icon-size: 14px; }
"""


_installed = False


def install() -> None:
    global _installed
    if _installed:
        return
    css = Gtk.CssProvider()
    css.load_from_data(_CSS)
    display = Gdk.Display.get_default()
    if display is not None:
        Gtk.StyleContext.add_provider_for_display(
            display, css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )
        _installed = True


_EXT_CLASS = {
    "py": "py", "pyx": "py", "pyi": "py",
    "js": "js", "mjs": "js", "cjs": "js", "jsx": "js",
    "ts": "ts", "tsx": "ts",
    "json": "json", "jsonc": "json",
    "yaml": "yaml", "yml": "yaml",
    "toml": "toml",
    "md": "md", "markdown": "md", "rst": "md",
    "html": "html", "htm": "html", "xml": "html", "svg": "html",
    "css": "css", "scss": "css", "sass": "css", "less": "css",
    "rs": "rust",
    "go": "go",
    "c": "c", "h": "c",
    "cpp": "cpp", "cc": "cpp", "cxx": "cpp", "hpp": "cpp", "hxx": "cpp",
    "java": "java", "kt": "java", "scala": "java",
    "sh": "sh", "bash": "sh", "zsh": "sh", "fish": "sh",
    "rb": "rb",
    "php": "php",
    "png": "img", "jpg": "img", "jpeg": "img", "gif": "img", "webp": "img", "ico": "img",
    "zip": "archive", "tar": "archive", "gz": "archive", "xz": "archive", "bz2": "archive",
    "7z": "archive", "rar": "archive", "deb": "archive", "rpm": "archive",
}


def class_for_filename(name: str) -> str:
    if "." not in name:
        return "file-other"
    ext = name.rsplit(".", 1)[1].lower()
    return f"file-{_EXT_CLASS.get(ext, 'other')}"
