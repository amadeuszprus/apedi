"""Which keys the focused terminal keeps and which stay editor shortcuts."""

from __future__ import annotations

import pytest

pytest.importorskip("gi")

from gi.repository import Gdk  # noqa: E402

from apedi.terminal_keys import APP, COPY, PASTE, TERMINAL, route  # noqa: E402

CTRL = Gdk.ModifierType.CONTROL_MASK
SHIFT = Gdk.ModifierType.SHIFT_MASK
ALT = Gdk.ModifierType.ALT_MASK
NONE = Gdk.ModifierType(0)


@pytest.mark.parametrize("keyval", [Gdk.KEY_C, Gdk.KEY_c])
def test_ctrl_shift_c_copies(keyval: int) -> None:
    assert route(keyval, CTRL | SHIFT) == COPY


@pytest.mark.parametrize("keyval", [Gdk.KEY_V, Gdk.KEY_v])
def test_ctrl_shift_v_pastes(keyval: int) -> None:
    assert route(keyval, CTRL | SHIFT) == PASTE


def test_insert_combinations() -> None:
    assert route(Gdk.KEY_Insert, CTRL) == COPY
    assert route(Gdk.KEY_Insert, SHIFT) == PASTE


@pytest.mark.parametrize(
    "keyval",
    [Gdk.KEY_r, Gdk.KEY_w, Gdk.KEY_p, Gdk.KEY_c, Gdk.KEY_d, Gdk.KEY_s, Gdk.KEY_q, Gdk.KEY_backslash],
)
def test_shell_control_keys_reach_the_terminal(keyval: int) -> None:
    assert route(keyval, CTRL) == TERMINAL


def test_alt_keys_reach_the_terminal() -> None:
    assert route(Gdk.KEY_z, ALT) == TERMINAL
    assert route(Gdk.KEY_period, ALT) == TERMINAL


def test_plain_and_function_keys_reach_the_terminal() -> None:
    assert route(Gdk.KEY_a, NONE) == TERMINAL
    assert route(Gdk.KEY_F2, NONE) == TERMINAL
    assert route(Gdk.KEY_F9, NONE) == TERMINAL


@pytest.mark.parametrize("keyval", [Gdk.KEY_p, Gdk.KEY_f, Gdk.KEY_o, Gdk.KEY_asciitilde])
def test_ctrl_shift_shortcuts_stay_with_the_editor(keyval: int) -> None:
    assert route(keyval, CTRL | SHIFT) == APP


@pytest.mark.parametrize(
    "keyval",
    [Gdk.KEY_Tab, Gdk.KEY_Page_Up, Gdk.KEY_Page_Down, Gdk.KEY_grave, Gdk.KEY_comma, Gdk.KEY_1],
)
def test_editor_navigation_stays_with_the_editor(keyval: int) -> None:
    assert route(keyval, CTRL) == APP
