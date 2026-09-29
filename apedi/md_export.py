"""Export markdown to a self-contained HTML page or a paginated A4 PDF."""

from __future__ import annotations

import base64
import html as html_lib
import io
import logging
import re
from pathlib import Path

import cairo
import gi

gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
gi.require_version("GdkPixbuf", "2.0")
gi.require_foreign("cairo")
from gi.repository import GdkPixbuf, GLib, Pango, PangoCairo  # noqa: E402

from . import markdown_preview as mp
from .outline import markdown_headings

log = logging.getLogger(__name__)

_MAX_INLINE_IMAGE = 10 * 1024 * 1024
_MIME = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
    ".svg": "image/svg+xml", ".webp": "image/webp", ".bmp": "image/bmp",
}


def split_front_matter(text: str) -> tuple[dict[str, str], str]:
    """YAML front matter's simple `key: value` pairs, and the markdown after it."""
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return {}, text
    for end in range(1, len(lines)):
        if lines[end].strip() in ("---", "..."):
            meta: dict[str, str] = {}
            for line in lines[1:end]:
                key, sep, value = line.partition(":")
                value = value.strip().strip("\"'")
                if sep and key.strip() and value and value[0] not in "[{|>":
                    meta[key.strip()] = value
            return meta, "\n".join(lines[end + 1:])
    return {}, text


def document_title(text: str, fallback: str) -> str:
    meta, body = split_front_matter(text)
    if meta.get("title"):
        return meta["title"]
    headings = markdown_headings(body)
    top = [h for h in headings if h.level == 1] or headings
    return top[0].title if top else fallback


# ---------- HTML ----------

_CSS = """
:root { color-scheme: light; }
body { margin: 0; background: #fff; color: #1f2328;
  font: 16px/1.6 -apple-system, "Segoe UI", "Noto Sans", Ubuntu, Cantarell, sans-serif; }
main { max-width: 820px; margin: 0 auto; padding: 40px 24px 64px; }
h1, h2 { border-bottom: 1px solid #d8dee4; padding-bottom: .3em; }
h1, h2, h3, h4 { line-height: 1.25; margin: 1.5em 0 .6em; }
a { color: #0969da; }
code, pre { font-family: ui-monospace, "JetBrains Mono", "DejaVu Sans Mono", monospace; font-size: .88em; }
:not(pre) > code { background: #eff1f3; padding: .15em .35em; border-radius: 5px; }
pre { background: #f6f8fa; border: 1px solid #d8dee4; border-radius: 8px; padding: 14px 16px; overflow-x: auto; }
table { border-collapse: collapse; margin: 1em 0; }
th, td { border: 1px solid #d0d7de; padding: 6px 12px; }
th { background: #f6f8fa; }
tr:nth-child(even) td { background: #fafbfc; }
blockquote { margin: 1em 0; padding: 0 1em; color: #59636e; border-left: 4px solid #d0d7de; }
img { max-width: 100%; }
hr { border: 0; border-top: 1px solid #d8dee4; margin: 2em 0; }
@media print { main { max-width: none; padding: 0; } pre, table, img { break-inside: avoid; } }
"""

_IMG_SRC = re.compile(r'(<img\b[^>]*?\bsrc=")([^"]*)(")')


def _inline_images(body: str, base: Path | None) -> str:
    """Swap local image sources for data URIs so the page works wherever it is saved."""

    def swap(m: re.Match[str]) -> str:
        src = html_lib.unescape(m.group(2))
        path = mp.local_image_path(src, base)
        mime = _MIME.get(path.suffix.lower()) if path is not None else None
        if path is None or mime is None:
            return m.group(0)
        try:
            if path.stat().st_size > _MAX_INLINE_IMAGE:
                return m.group(0)
            data = base64.b64encode(path.read_bytes()).decode("ascii")
        except OSError:
            return m.group(0)
        return f"{m.group(1)}data:{mime};base64,{data}{m.group(3)}"

    return _IMG_SRC.sub(swap, body)


def to_html(text: str, base: Path | None, fallback_title: str) -> str:
    import markdown

    title = document_title(text, fallback_title)
    _meta, body_md = split_front_matter(text)
    body = markdown.Markdown(extensions=["fenced_code", "tables", "sane_lists"]).convert(body_md)
    body = _inline_images(body, base)
    return (
        "<!DOCTYPE html>\n<html>\n<head>\n<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        f"<title>{html_lib.escape(title)}</title>\n<style>{_CSS}</style>\n</head>\n"
        f"<body>\n<main>\n{body}\n</main>\n</body>\n</html>\n"
    )


# ---------- PDF ----------

_PAGE_W, _PAGE_H = 595.28, 841.89  # A4 in points
_MARGIN = 56.0
_CONTENT_W = _PAGE_W - 2 * _MARGIN
_GAP = 8.0
_CELL_PAD = 5.0
_CODE_PAD = 8.0
_LINK_OPEN = re.compile(r'<a href="[^"]*">')


def _pango_markup(markup: str) -> str:
    """The preview's GtkLabel markup made valid for plain Pango, which has no links."""
    return _LINK_OPEN.sub('<span foreground="#0969da" underline="single">', markup).replace("</a>", "</span>")


def _set_markup(layout: Pango.Layout, markup: str) -> None:
    """Pango drops invalid markup silently, so validate first and fall back to plain text."""
    try:
        Pango.parse_markup(markup, -1, "\x00")
    except GLib.Error:
        layout.set_text(re.sub(r"<[^>]+>", "", markup), -1)
        return
    layout.set_markup(markup, -1)


class _Pdf:
    def __init__(self, out: Path) -> None:
        self.surface = cairo.PDFSurface(str(out), _PAGE_W, _PAGE_H)
        self.cr = cairo.Context(self.surface)
        self.y = _MARGIN
        self.body_font = Pango.FontDescription.from_string("Sans 10.5")
        self.mono_font = Pango.FontDescription.from_string("Monospace 9")

    @property
    def bottom(self) -> float:
        return _PAGE_H - _MARGIN

    def new_page(self) -> None:
        self.cr.show_page()
        self.y = _MARGIN

    def ensure(self, height: float) -> None:
        if self.y + height > self.bottom and self.y > _MARGIN:
            self.new_page()

    def layout(self, width: float | None, mono: bool = False) -> Pango.Layout:
        layout = PangoCairo.create_layout(self.cr)
        layout.set_font_description(self.mono_font if mono else self.body_font)
        if width is not None:
            layout.set_width(int(width * Pango.SCALE))
            layout.set_wrap(Pango.WrapMode.WORD_CHAR)
        return layout

    def flow(self, layout: Pango.Layout, x: float, background: tuple[float, float, float] | None = None) -> None:
        """Draw a layout line by line, breaking pages between lines."""
        it = layout.get_iter()
        lines = []
        while True:
            _ink, logical = it.get_line_extents()
            lines.append((it.get_line_readonly(), logical.y / Pango.SCALE,
                          logical.height / Pango.SCALE, it.get_baseline() / Pango.SCALE))
            if not it.next_line():
                break
        origin = lines[0][1] if lines else 0.0
        top = self.y
        for line, ly, lh, base in lines:
            if top + (ly - origin) + lh > self.bottom:
                self.new_page()
                origin, top = ly, self.y
            y = top + (ly - origin)
            if background is not None:
                self.cr.set_source_rgb(*background)
                self.cr.rectangle(_MARGIN, y, _CONTENT_W, lh)
                self.cr.fill()
            self.cr.set_source_rgb(0.12, 0.14, 0.16)
            self.cr.move_to(x, top + (base - origin))
            PangoCairo.show_layout_line(self.cr, line)
        if lines:
            _line, ly, lh, _base = lines[-1]
            self.y = top + (ly - origin) + lh

    def prose(self, block: mp.ProseBlock) -> None:
        # Room for a heading and a couple of lines, so a title never ends a page alone.
        self.ensure(48)
        layout = self.layout(_CONTENT_W)
        _set_markup(layout, _pango_markup(block.pango_markup))
        self.flow(layout, _MARGIN)

    def code(self, block: mp.CodeBlock) -> None:
        layout = self.layout(_CONTENT_W - 2 * _CODE_PAD, mono=True)
        layout.set_text(block.text or " ", -1)
        shade = (0.965, 0.973, 0.98)
        self.ensure(3 * _CODE_PAD)
        self.cr.set_source_rgb(*shade)
        self.cr.rectangle(_MARGIN, self.y, _CONTENT_W, _CODE_PAD)
        self.cr.fill()
        self.y += _CODE_PAD
        self.flow(layout, _MARGIN + _CODE_PAD, background=shade)
        self.cr.set_source_rgb(*shade)
        self.cr.rectangle(_MARGIN, self.y, _CONTENT_W, _CODE_PAD)
        self.cr.fill()
        self.y += _CODE_PAD

    def _cell(self, markup: str, width: float | None, bold: bool) -> Pango.Layout:
        layout = self.layout(width)
        text = _pango_markup(markup) or " "
        _set_markup(layout, f"<b>{text}</b>" if bold else text)
        return layout

    def table(self, block: mp.TableBlock) -> None:
        rows = [(block.header, True)] + [(r, False) for r in block.rows]
        cols = max((len(r) for r, _h in rows), default=0)
        if cols == 0:
            return
        natural = [0.0] * cols
        for cells, header in rows:
            for c, markup in enumerate(cells):
                w, _h = self._cell(markup, None, header).get_pixel_size()
                natural[c] = max(natural[c], w + 2 * _CELL_PAD)
        total = sum(natural)
        widths = natural if total <= _CONTENT_W else [max(40.0, w * _CONTENT_W / total) for w in natural]
        scale = min(1.0, _CONTENT_W / sum(widths))
        widths = [w * scale for w in widths]
        for cells, header in rows:
            layouts = [
                self._cell(cells[c] if c < len(cells) else "", widths[c] - 2 * _CELL_PAD, header)
                for c in range(cols)
            ]
            height = max(lay.get_pixel_size()[1] for lay in layouts) + 2 * _CELL_PAD
            self.ensure(height)
            x = _MARGIN
            for c, lay in enumerate(layouts):
                if header:
                    self.cr.set_source_rgb(0.965, 0.973, 0.98)
                    self.cr.rectangle(x, self.y, widths[c], height)
                    self.cr.fill()
                self.cr.set_source_rgb(0.82, 0.84, 0.87)
                self.cr.set_line_width(0.6)
                self.cr.rectangle(x, self.y, widths[c], height)
                self.cr.stroke()
                self.cr.set_source_rgb(0.12, 0.14, 0.16)
                self.cr.move_to(x + _CELL_PAD, self.y + _CELL_PAD)
                PangoCairo.show_layout(self.cr, lay)
                x += widths[c]
            self.y += height

    def image(self, block: mp.ImageBlock, base: Path | None) -> None:
        path = mp.local_image_path(block.src, base)
        surface = None
        if path is not None and path.is_file():
            try:
                pixbuf = GdkPixbuf.Pixbuf.new_from_file(str(path))
                ok, png = pixbuf.save_to_bufferv("png", [], [])
                if ok:
                    surface = cairo.ImageSurface.create_from_png(io.BytesIO(png))
            except (GLib.Error, cairo.Error, MemoryError) as e:
                log.debug("cannot embed image %s: %s", path, e)
        if surface is None:
            self.prose(mp.ProseBlock(f"<i>[{GLib.markup_escape_text(block.alt or block.src)}]</i>"))
            return
        w, h = surface.get_width(), surface.get_height()
        scale = min(1.0, _CONTENT_W / w, (self.bottom - _MARGIN) / h)
        self.ensure(h * scale)
        self.cr.save()
        self.cr.translate(_MARGIN, self.y)
        self.cr.scale(scale, scale)
        self.cr.set_source_surface(surface, 0, 0)
        self.cr.paint()
        self.cr.restore()
        self.y += h * scale

    def finish(self) -> None:
        self.surface.finish()


def to_pdf(text: str, base: Path | None, out: Path) -> None:
    """Typeset the same blocks the preview shows onto A4 pages."""
    _meta, body = split_front_matter(text)
    pdf = _Pdf(out)
    try:
        for i, block in enumerate(mp.render_blocks(body)):
            if i:
                pdf.y += _GAP
            if isinstance(block, mp.ProseBlock):
                pdf.prose(block)
            elif isinstance(block, mp.CodeBlock):
                pdf.code(block)
            elif isinstance(block, mp.TableBlock):
                pdf.table(block)
            elif isinstance(block, mp.ImageBlock):
                pdf.image(block, base)
    finally:
        pdf.finish()
