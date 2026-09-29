"""Editing commands on a GtkSource buffer: comments, duplication, occurrences, auto-pairs."""

from __future__ import annotations

import builtins
from typing import Callable

if not hasattr(builtins, "_"):
    builtins._ = lambda s: s  # type: ignore[attr-defined]

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("GtkSource", "5")
from gi.repository import Gdk, Gtk, GtkSource  # noqa: E402

from . import editing


def _lang_id(buf: GtkSource.Buffer) -> str | None:
    lang = buf.get_language()
    return lang.get_id() if lang is not None else None


def _line_bounds(buf: GtkSource.Buffer) -> tuple[Gtk.TextIter, Gtk.TextIter, bool]:
    """Whole lines covered by the selection or the cursor, and whether there was a selection."""
    bounds = buf.get_selection_bounds()
    has_sel = bool(bounds)
    if has_sel:
        start, end = bounds
    else:
        start = buf.get_iter_at_mark(buf.get_insert())
        end = start.copy()
    first, last = start.get_line(), end.get_line()
    # A selection ending at the start of a line does not include that line.
    if has_sel and last > first and end.starts_line():
        last -= 1
    line_start = buf.get_iter_at_line(first)[1]
    line_end = buf.get_iter_at_line(last)[1]
    if not line_end.ends_line():
        line_end.forward_to_line_end()
    return line_start, line_end, has_sel


def _replace(buf: GtkSource.Buffer, start: Gtk.TextIter, end: Gtk.TextIter, text: str) -> int:
    """Swap a range for `text` as one undo step; returns the start offset."""
    offset = start.get_offset()
    buf.begin_user_action()
    buf.delete(start, end)
    buf.insert(buf.get_iter_at_offset(offset), text)
    buf.end_user_action()
    return offset


def toggle_comment(buf: GtkSource.Buffer) -> str | None:
    """Comment or uncomment the current lines; returns a status message when nothing can be done."""
    lang = buf.get_language()
    if lang is None:
        return _("No comment syntax for plain text")
    line_tok, block = editing.comment_tokens(
        lang.get_id(),
        lang.get_metadata("line-comment-start"),
        lang.get_metadata("block-comment-start"),
        lang.get_metadata("block-comment-end"),
    )
    if line_tok is None and block is None:
        return _("No comment syntax for {lang}").format(lang=lang.get_name())

    cursor = buf.get_iter_at_mark(buf.get_insert())
    cursor_line, cursor_col = cursor.get_line(), cursor.get_line_offset()
    start, end, has_sel = _line_bounds(buf)
    if line_tok is None and has_sel:
        sel_start, sel_end = buf.get_selection_bounds()
        text = buf.get_text(sel_start, sel_end, False)
        new = editing.toggle_block_comment(text, *block)
        offset = _replace(buf, sel_start, sel_end, new)
        buf.select_range(buf.get_iter_at_offset(offset), buf.get_iter_at_offset(offset + len(new)))
        return None

    text = buf.get_text(start, end, False)
    if line_tok is not None:
        new = "\n".join(editing.toggle_line_comment(text.split("\n"), line_tok))
    else:
        new = editing.toggle_block_comment(text, *block)
    if new == text:
        return None
    first_line = start.get_line()
    old_cursor_line = text.split("\n")[cursor_line - first_line] if not has_sel else ""
    offset = _replace(buf, start, end, new)
    if has_sel:
        buf.select_range(buf.get_iter_at_offset(offset), buf.get_iter_at_offset(offset + len(new)))
        return None
    # Keep the cursor on the same character, shifted by what the line gained or lost.
    new_line = new.split("\n")[cursor_line - first_line]
    col = max(0, min(len(new_line), cursor_col + len(new_line) - len(old_cursor_line)))
    it = buf.get_iter_at_line(cursor_line)[1]
    it.forward_chars(col)
    buf.place_cursor(it)
    return None


def duplicate(buf: GtkSource.Buffer, *, down: bool) -> None:
    """Copy the selection, or the current line, below or above itself."""
    bounds = buf.get_selection_bounds()
    if bounds:
        start, end = bounds
        text = buf.get_text(start, end, False)
        s, e = start.get_offset(), end.get_offset()
        buf.begin_user_action()
        buf.insert(buf.get_iter_at_offset(e), text)
        buf.end_user_action()
        new_start = e if down else s
        buf.select_range(buf.get_iter_at_offset(new_start), buf.get_iter_at_offset(new_start + len(text)))
        return
    cursor = buf.get_iter_at_mark(buf.get_insert())
    col = cursor.get_line_offset()
    line_start = cursor.copy()
    line_start.set_line_offset(0)
    line_end = cursor.copy()
    if not line_end.ends_line():
        line_end.forward_to_line_end()
    text = buf.get_text(line_start, line_end, False)
    end_offset = line_end.get_offset()
    start_offset = line_start.get_offset()
    buf.begin_user_action()
    buf.insert(buf.get_iter_at_offset(end_offset), "\n" + text)
    buf.end_user_action()
    target = end_offset + 1 + col if down else start_offset + col
    buf.place_cursor(buf.get_iter_at_offset(target))


def select_next_occurrence(buf: GtkSource.Buffer) -> bool:
    """Select the word at the cursor, or move the selection to the next copy of it."""
    text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
    bounds = buf.get_selection_bounds()
    if not bounds:
        offset = buf.get_iter_at_mark(buf.get_insert()).get_offset()
        word = editing.word_at(text, offset)
        if word is None:
            return False
        buf.select_range(buf.get_iter_at_offset(word[0]), buf.get_iter_at_offset(word[1]))
        return True
    start, end = bounds
    needle = buf.get_text(start, end, False)
    found = editing.next_occurrence(text, needle, end.get_offset())
    if found is None or found[0] == start.get_offset():
        return False
    buf.select_range(buf.get_iter_at_offset(found[0]), buf.get_iter_at_offset(found[1]))
    return True


def _char_before(it: Gtk.TextIter) -> str:
    if it.starts_line():
        return ""
    prev = it.copy()
    prev.backward_char()
    return prev.get_char()


def _char_at(it: Gtk.TextIter) -> str:
    return "" if it.ends_line() else it.get_char()


class AutoPairs:
    """Closes brackets and quotes as they are typed and wraps selections in them."""

    _MODS = Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.ALT_MASK | Gdk.ModifierType.SUPER_MASK

    def __init__(self, view: GtkSource.View, enabled: Callable[[], bool]) -> None:
        self._view = view
        self._enabled = enabled
        key = Gtk.EventControllerKey()
        key.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        key.connect("key-pressed", self._on_key)
        view.add_controller(key)

    def _on_key(self, _ctrl: Gtk.EventControllerKey, keyval: int, _code: int, state: Gdk.ModifierType) -> bool:
        if not self._enabled() or state & self._MODS or self._view.get_overwrite():
            return False
        if not self._view.get_editable():
            return False
        buf = self._view.get_buffer()
        if keyval == Gdk.KEY_BackSpace:
            return self._backspace(buf)
        codepoint = Gdk.keyval_to_unicode(keyval)
        if not codepoint:
            return False
        char = chr(codepoint)
        lang_id = _lang_id(buf)
        bounds = buf.get_selection_bounds()
        if bounds:
            pair = editing.wrap_pair(char, lang_id)
            if pair is None:
                return False
            start, end = bounds
            s, e = start.get_offset(), end.get_offset()
            buf.begin_user_action()
            buf.insert(buf.get_iter_at_offset(e), pair[1])
            buf.insert(buf.get_iter_at_offset(s), pair[0])
            buf.end_user_action()
            buf.select_range(buf.get_iter_at_offset(s + 1), buf.get_iter_at_offset(e + 1))
            return True
        cursor = buf.get_iter_at_mark(buf.get_insert())
        action = editing.pair_action(char, _char_before(cursor), _char_at(cursor), lang_id)
        if action == editing.PAIR:
            closer = editing.wrap_pair(char, lang_id)[1]
            offset = cursor.get_offset()
            buf.begin_user_action()
            buf.insert(cursor, char + closer)
            buf.end_user_action()
            buf.place_cursor(buf.get_iter_at_offset(offset + 1))
            return True
        if action == editing.SKIP:
            cursor.forward_char()
            buf.place_cursor(cursor)
            return True
        return False

    def _backspace(self, buf: GtkSource.Buffer) -> bool:
        if buf.get_has_selection():
            return False
        cursor = buf.get_iter_at_mark(buf.get_insert())
        if not editing.deletes_pair(_char_before(cursor), _char_at(cursor)):
            return False
        start = cursor.copy()
        start.backward_char()
        end = cursor.copy()
        end.forward_char()
        buf.begin_user_action()
        buf.delete(start, end)
        buf.end_user_action()
        return True
