"""Tests for apedi.theming — light/dark resolution.

Pure logic, no GTK: the scheme metadata GtkSourceView would report is
passed in as a plain mapping so these run in a venv without `gi`.
"""

from __future__ import annotations

import pytest

from apedi import theming as t


# Mirrors what GtkSourceView 5 reports on a stock Ubuntu install. Note the
# two schemes whose name says nothing about their variant: `cobalt` is dark
# and pairs with `cobalt-light`, `oblivion` is dark and pairs with `tango`.
VARIANTS = {
    "Adwaita": t.SchemeVariants("light", "", "Adwaita-dark"),
    "Adwaita-dark": t.SchemeVariants("dark", "Adwaita", ""),
    "Yaru": t.SchemeVariants("light", "", "Yaru-dark"),
    "Yaru-dark": t.SchemeVariants("dark", "Yaru", ""),
    "cobalt": t.SchemeVariants("dark", "cobalt-light", ""),
    "cobalt-light": t.SchemeVariants("light", "", "cobalt"),
    "oblivion": t.SchemeVariants("dark", "tango", ""),
    "tango": t.SchemeVariants("light", "", "oblivion"),
    "solarized-dark": t.SchemeVariants("dark", "solarized-light", ""),
    "solarized-light": t.SchemeVariants("light", "", "solarized-dark"),
}
AVAILABLE = sorted(VARIANTS)


# ---------- is_dark_scheme ----------

@pytest.mark.parametrize("scheme,expected", [
    ("Adwaita", False),
    ("Adwaita-dark", True),
    ("cobalt", True),          # dark despite the name
    ("cobalt-light", False),
    ("oblivion", True),        # dark despite the name
    ("tango", False),
])
def test_is_dark_scheme_uses_metadata(scheme: str, expected: bool) -> None:
    assert t.is_dark_scheme(scheme, VARIANTS) is expected


def test_is_dark_scheme_falls_back_to_name_without_metadata() -> None:
    assert t.is_dark_scheme("something-dark", {}) is True
    assert t.is_dark_scheme("something", {}) is False


# ---------- scheme_for_mode ----------

@pytest.mark.parametrize("scheme,expected", [
    ("Adwaita", "Adwaita-dark"),
    ("Yaru", "Yaru-dark"),
    ("cobalt-light", "cobalt"),
    ("tango", "oblivion"),
    ("solarized-light", "solarized-dark"),
])
def test_scheme_for_mode_to_dark(scheme: str, expected: str) -> None:
    assert t.scheme_for_mode(scheme, True, VARIANTS, AVAILABLE) == expected


@pytest.mark.parametrize("scheme,expected", [
    ("Adwaita-dark", "Adwaita"),
    ("Yaru-dark", "Yaru"),
    ("cobalt", "cobalt-light"),
    ("oblivion", "tango"),
    ("solarized-dark", "solarized-light"),
])
def test_scheme_for_mode_to_light(scheme: str, expected: str) -> None:
    assert t.scheme_for_mode(scheme, False, VARIANTS, AVAILABLE) == expected


@pytest.mark.parametrize("scheme,dark", [
    ("Adwaita", False), ("Adwaita-dark", True), ("cobalt", True), ("tango", False),
])
def test_scheme_for_mode_keeps_matching_variant(scheme: str, dark: bool) -> None:
    assert t.scheme_for_mode(scheme, dark, VARIANTS, AVAILABLE) == scheme


def test_scheme_for_mode_never_returns_unavailable_id() -> None:
    """The old code turned solarized-dark into a nonexistent `solarized`."""
    got = t.scheme_for_mode("solarized-dark", False, VARIANTS, AVAILABLE)
    assert got in AVAILABLE


def test_scheme_for_mode_name_heuristic_without_metadata() -> None:
    available = ["Adwaita", "Adwaita-dark", "kate", "kate-dark"]
    assert t.scheme_for_mode("kate", True, {}, available) == "kate-dark"
    assert t.scheme_for_mode("kate-dark", False, {}, available) == "kate"


def test_scheme_for_mode_falls_back_to_adwaita() -> None:
    available = ["Adwaita", "Adwaita-dark", "lonely"]
    assert t.scheme_for_mode("lonely", True, {}, available) == "Adwaita-dark"


def test_scheme_for_mode_keeps_scheme_when_nothing_available() -> None:
    assert t.scheme_for_mode("weird", True, {}, []) == "weird"


# ---------- next_theme ----------

def test_next_theme_from_light_flips_ui_and_editor_at_once() -> None:
    """One toggle must change both halves — that was the reported bug."""
    dark_ui, scheme = t.next_theme(
        "Adwaita", currently_dark=False, variants=VARIANTS, available=AVAILABLE,
    )
    assert dark_ui == "dark"
    assert scheme == "Adwaita-dark"


def test_next_theme_from_dark_flips_back() -> None:
    dark_ui, scheme = t.next_theme(
        "Adwaita-dark", currently_dark=True, variants=VARIANTS, available=AVAILABLE,
    )
    assert dark_ui == "light"
    assert scheme == "Adwaita"


def test_next_theme_never_yields_auto() -> None:
    """Two states only — `auto` stays a Preferences choice, not a toggle stop."""
    scheme = "Adwaita"
    dark = False
    for _ in range(4):
        dark_ui, scheme = t.next_theme(
            scheme, currently_dark=dark, variants=VARIANTS, available=AVAILABLE,
        )
        assert dark_ui in ("light", "dark")
        dark = dark_ui == "dark"


def test_next_theme_round_trip_returns_to_start() -> None:
    dark_ui, scheme = t.next_theme(
        "cobalt-light", currently_dark=False, variants=VARIANTS, available=AVAILABLE,
    )
    assert (dark_ui, scheme) == ("dark", "cobalt")
    dark_ui, scheme = t.next_theme(
        scheme, currently_dark=True, variants=VARIANTS, available=AVAILABLE,
    )
    assert (dark_ui, scheme) == ("light", "cobalt-light")


def test_next_theme_two_presses_are_not_needed_from_auto() -> None:
    """Starting from `auto` on a light system, the first press must land dark."""
    dark_ui, scheme = t.next_theme(
        "Adwaita", currently_dark=False, variants=VARIANTS, available=AVAILABLE,
    )
    assert (dark_ui, scheme) == ("dark", "Adwaita-dark")


# ---------- collect_scheme_variants ----------

def test_collect_scheme_variants_degrades_without_gtksource() -> None:
    variants, ids = t.collect_scheme_variants()
    assert isinstance(variants, dict)
    assert isinstance(ids, list)
