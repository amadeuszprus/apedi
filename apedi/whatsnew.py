"""What's New dialog — shown once per version on first launch."""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk  # noqa: E402

log = logging.getLogger(__name__)


def _changelog_path() -> Path | None:
    snap = os.environ.get("SNAP")
    if snap:
        candidate = Path(snap) / "usr/share/apedi/CHANGELOG.md"
        if candidate.exists():
            return candidate
    candidate = Path(__file__).resolve().parent.parent / "CHANGELOG.md"
    return candidate if candidate.exists() else None


_SECTION_PATTERN = re.compile(
    r"^## \[(?P<v>[^\]]+)\][^\n]*\n(?P<body>.*?)(?=^## \[|\Z)",
    re.MULTILINE | re.DOTALL,
)


def section_for_version(version: str) -> str | None:
    """Extract the CHANGELOG section for the given semantic version."""
    path = _changelog_path()
    if path is None:
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        log.warning("cannot read CHANGELOG: %s", e)
        return None
    for match in _SECTION_PATTERN.finditer(text):
        if match.group("v") == version:
            return match.group("body").strip()
    return None


class WhatsNewDialog(Gtk.Window):
    __gtype_name__ = "ApediWhatsNewDialog"

    def __init__(self, parent: Gtk.Window, version: str, content: str) -> None:
        super().__init__(
            title=f"What's new in Apedi {version}",
            transient_for=parent,
            modal=True,
            default_width=600,
            default_height=480,
        )

        outer = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=14,
            margin_top=18, margin_bottom=18, margin_start=22, margin_end=22,
        )
        header = Gtk.Label(
            label=f"<span size='x-large' weight='bold'>What's new in {version}</span>",
            use_markup=True,
            xalign=0,
        )
        outer.append(header)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_hexpand(True)
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.add_css_class("frame")

        view = Gtk.TextView()
        view.set_editable(False)
        view.set_cursor_visible(False)
        view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        view.set_left_margin(14)
        view.set_right_margin(14)
        view.set_top_margin(10)
        view.set_bottom_margin(10)
        buffer = view.get_buffer()
        _render_markdown(buffer, content)
        scrolled.set_child(view)
        outer.append(scrolled)

        button_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        button_row.set_halign(Gtk.Align.END)
        close_btn = Gtk.Button(label="Got it")
        close_btn.add_css_class("suggested-action")
        close_btn.connect("clicked", lambda *_: self.close())
        button_row.append(close_btn)
        outer.append(button_row)

        self.set_child(outer)


def _ensure_tags(buffer: Gtk.TextBuffer) -> None:
    table = buffer.get_tag_table()
    if table.lookup("h3"):
        return
    h3 = Gtk.TextTag.new("h3")
    h3.set_property("weight", 700)
    h3.set_property("scale", 1.10)
    h3.set_property("pixels-above-lines", 12)
    h3.set_property("pixels-below-lines", 4)
    table.add(h3)

    h2 = Gtk.TextTag.new("h2")
    h2.set_property("weight", 800)
    h2.set_property("scale", 1.20)
    h2.set_property("pixels-above-lines", 16)
    h2.set_property("pixels-below-lines", 6)
    table.add(h2)

    bullet = Gtk.TextTag.new("bullet")
    bullet.set_property("indent", 4)
    bullet.set_property("left-margin", 14)
    table.add(bullet)

    bold = Gtk.TextTag.new("bold")
    bold.set_property("weight", 700)
    table.add(bold)

    code = Gtk.TextTag.new("code")
    code.set_property("family", "Monospace")
    code.set_property("background", "rgba(128,128,128,0.18)")
    code.set_property("scale", 0.96)
    table.add(code)


_INLINE_PATTERN = re.compile(r"(\*\*[^*]+\*\*|`[^`]+`)")


def _insert_inline(buffer: Gtk.TextBuffer, text: str, line_tag: str | None) -> None:
    """Insert `text` into buffer, applying inline markdown spans
    (``**bold**`` and `` `code` ``). `line_tag` (e.g. ``"h3"`` or
    ``"bullet"``) is applied uniformly to every chunk."""
    for piece in _INLINE_PATTERN.split(text):
        if not piece:
            continue
        end = buffer.get_end_iter()
        tags: list[str] = []
        if line_tag:
            tags.append(line_tag)
        if piece.startswith("**") and piece.endswith("**") and len(piece) >= 4:
            piece = piece[2:-2]
            tags.append("bold")
        elif piece.startswith("`") and piece.endswith("`") and len(piece) >= 2:
            piece = piece[1:-1]
            tags.append("code")
        if tags:
            buffer.insert_with_tags_by_name(end, piece, *tags)
        else:
            buffer.insert(end, piece)


def _render_markdown(buffer: Gtk.TextBuffer, content: str) -> None:
    _ensure_tags(buffer)
    for raw_line in content.splitlines():
        line = raw_line.rstrip()
        end = buffer.get_end_iter()
        if not line:
            buffer.insert(end, "\n")
            continue
        if line.startswith("### "):
            _insert_inline(buffer, line[4:], "h3")
            buffer.insert(buffer.get_end_iter(), "\n")
            continue
        if line.startswith("## "):
            _insert_inline(buffer, line[3:], "h2")
            buffer.insert(buffer.get_end_iter(), "\n")
            continue
        if line.lstrip().startswith(("- ", "* ", "• ")):
            stripped = line.lstrip()[2:]
            buffer.insert_with_tags_by_name(end, "•  ", "bullet")
            _insert_inline(buffer, stripped, "bullet")
            buffer.insert(buffer.get_end_iter(), "\n")
            continue
        _insert_inline(buffer, line, None)
        buffer.insert(buffer.get_end_iter(), "\n")
