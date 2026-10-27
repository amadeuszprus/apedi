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

/* Git state - listed after the per-extension colours so it wins over them */
label.git-added    { color: #2e9e5b; }
label.git-modified { color: #c8931b; }
label.git-conflict { color: #d64545; font-weight: bold; }

/* Split editor - the group without focus mutes its selected tab */
notebook.apedi-group-inactive > header > tabs > tab:checked { box-shadow: none; }
notebook.apedi-group-inactive > header > tabs > tab:checked label { opacity: 0.6; }

/* Ignored entries (gitignore / heavy dirs / user patterns) */
.file-ignored { opacity: 0.45; font-style: italic; }
.file-heavy   { opacity: 0.55; }

/* Compact sidebar density */
.sidebar-compact listview > row { padding-top: 1px; padding-bottom: 1px; min-height: 18px; }
.sidebar-compact listview > row > * { padding-top: 0; padding-bottom: 0; }
.sidebar-compact label { font-size: 0.92em; }
.sidebar-compact image { -gtk-icon-size: 14px; }

/* About dialog: drop the underline from credit-section links */
aboutdialog button.link,
aboutdialog button.link:hover,
aboutdialog button.link:active,
aboutdialog button.link:focus { text-decoration: none; }

/* Markdown preview - long-form reading rhythm */
.apedi-md-prose {
    font-size: 1.02em;
    margin: 4px 0 8px;
}
.apedi-md-heading-1,
.apedi-md-heading-2,
.apedi-md-heading-3,
.apedi-md-heading-4,
.apedi-md-heading-5,
.apedi-md-heading-6 {
    margin-top: 18px;
    margin-bottom: 8px;
}
.apedi-md-heading-1 {
    padding-bottom: 9px;
    border-bottom: 1px solid alpha(currentColor, 0.18);
}
.apedi-md-heading-2 {
    padding-bottom: 7px;
    border-bottom: 1px solid alpha(currentColor, 0.11);
}
.apedi-md-heading-3 { margin-top: 14px; }
.apedi-md-list {
    margin-top: 3px;
    margin-bottom: 10px;
}
.apedi-md-quote {
    color: alpha(currentColor, 0.82);
    background: alpha(currentColor, 0.045);
    border-left: 3px solid alpha(currentColor, 0.30);
    border-radius: 0 6px 6px 0;
    padding: 10px 14px;
    margin: 7px 0 13px;
}
separator.apedi-md-break {
    min-height: 1px;
    background: alpha(currentColor, 0.16);
    margin: 18px 0;
}

/* Markdown preview - tables */
frame.apedi-md-table {
    border: 1px solid alpha(currentColor, 0.15);
    border-radius: 8px;
    margin: 10px 0 14px;
}
.apedi-md-table > grid > label {
    padding: 8px 12px;
    background: transparent;
}
.apedi-md-table > grid > label.header {
    font-weight: bold;
    background: alpha(currentColor, 0.065);
    border-bottom: 1px solid alpha(currentColor, 0.15);
}
.apedi-md-table > grid > label.odd {
    background: alpha(currentColor, 0.028);
}
.apedi-md-table > grid > label.column-separator {
    border-right: 1px solid alpha(currentColor, 0.10);
}
.apedi-md-table > grid > label.row-separator {
    border-bottom: 1px solid alpha(currentColor, 0.08);
}

/* Markdown preview - code blocks */
frame.apedi-md-code {
    background: alpha(currentColor, 0.06);
    border: none;
    border-radius: 8px;
    box-shadow:
        0 0 0 1px alpha(currentColor, 0.10),
        0 1px 2px alpha(black, 0.06),
        0 2px 4px alpha(black, 0.035);
    margin: 10px 1px 14px;
}
.apedi-md-code-language {
    font-family: monospace;
    font-size: 0.78em;
    color: alpha(currentColor, 0.58);
    background: alpha(currentColor, 0.035);
    border-bottom: 1px solid alpha(currentColor, 0.08);
    padding: 6px 12px 5px;
}
.apedi-md-code label {
    font-family: monospace;
}

/* Markdown preview - images */
.apedi-md-image {
    border-radius: 6px;
    outline: 1px solid rgba(0, 0, 0, 0.10);
    outline-offset: -1px;
    margin: 10px 0 14px;
}
.apedi-md-preview.apedi-dark .apedi-md-image {
    outline-color: rgba(255, 255, 255, 0.10);
}
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
