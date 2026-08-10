"""Light/dark theme resolution.

Kept free of GTK at import time so the mapping logic stays unit-testable:
the scheme metadata GtkSourceView reports is passed in as a plain mapping,
and `collect_scheme_variants()` — the only part that needs `gi` — imports
it lazily and degrades to empty data when unavailable.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Mapping, Sequence

log = logging.getLogger(__name__)

LIGHT_FALLBACK = "Adwaita"
DARK_FALLBACK = "Adwaita-dark"


@dataclass(frozen=True)
class SchemeVariants:
    """What GtkSourceView knows about one style scheme's light/dark siblings."""

    variant: str = ""  # "light" | "dark" | "" when the scheme says nothing
    light_variant: str = ""  # id of the light sibling, or ""
    dark_variant: str = ""  # id of the dark sibling, or ""


def is_dark_scheme(scheme_id: str, variants: Mapping[str, SchemeVariants]) -> bool:
    """True when `scheme_id` is a dark scheme.

    Prefers the scheme's own metadata — names lie: `cobalt` and `oblivion`
    are dark, `cobalt-light` is light, and none of them say so.
    """
    info = variants.get(scheme_id)
    if info is not None and info.variant:
        return info.variant == "dark"
    return "dark" in scheme_id.lower()


def _strip_variant_suffix(scheme_id: str) -> str:
    lowered = scheme_id.lower()
    if lowered.endswith("-dark"):
        return scheme_id[: -len("-dark")]
    if lowered.endswith("-light"):
        return scheme_id[: -len("-light")]
    return scheme_id


def scheme_for_mode(
    scheme_id: str,
    dark: bool,
    variants: Mapping[str, SchemeVariants],
    available: Sequence[str],
) -> str:
    """The counterpart of `scheme_id` for the requested mode.

    Returns `scheme_id` unchanged when it already matches or when no usable
    counterpart exists — never a scheme id the manager doesn't know about.
    """
    if is_dark_scheme(scheme_id, variants) == dark:
        return scheme_id

    candidates: list[str] = []
    info = variants.get(scheme_id)
    if info is not None:
        sibling = info.dark_variant if dark else info.light_variant
        if sibling:
            candidates.append(sibling)

    base = _strip_variant_suffix(scheme_id)
    if dark:
        candidates += [f"{base}-dark", DARK_FALLBACK]
    else:
        candidates += [base, f"{base}-light", LIGHT_FALLBACK]

    for candidate in candidates:
        if candidate not in available:
            continue
        candidate_info = variants.get(candidate)
        if candidate_info is not None and candidate_info.variant:
            if (candidate_info.variant == "dark") != dark:
                continue
        return candidate
    return scheme_id


def next_theme(
    color_scheme: str,
    *,
    currently_dark: bool,
    variants: Mapping[str, SchemeVariants],
    available: Sequence[str],
) -> tuple[str, str]:
    """Flip light <-> dark, returning `(dark_ui, color_scheme)`.

    Two states only: the UI theme and the editor scheme move together in a
    single step, and `auto` is never produced — it stays a Preferences
    choice rather than a stop on the toggle.
    """
    target_dark = not currently_dark
    return (
        "dark" if target_dark else "light",
        scheme_for_mode(color_scheme, target_dark, variants, available),
    )


def collect_scheme_variants() -> tuple[dict[str, SchemeVariants], list[str]]:
    """Read light/dark metadata for every known scheme.

    Returns `({}, [])` when GtkSourceView is missing or too old to expose
    scheme metadata; callers then fall back to the name heuristics above.
    """
    try:
        import gi

        gi.require_version("GtkSource", "5")
        from gi.repository import GtkSource
    except (ImportError, ValueError) as e:
        log.debug("GtkSource unavailable for scheme metadata: %s", e)
        return {}, []

    manager = GtkSource.StyleSchemeManager.get_default()
    ids = list(manager.get_scheme_ids() or [])
    variants: dict[str, SchemeVariants] = {}
    for scheme_id in ids:
        scheme = manager.get_scheme(scheme_id)
        get_metadata = getattr(scheme, "get_metadata", None)
        if scheme is None or get_metadata is None:
            continue  # GtkSourceView < 5.4 — name heuristics take over
        try:
            variants[scheme_id] = SchemeVariants(
                variant=get_metadata("variant") or "",
                light_variant=get_metadata("light-variant") or "",
                dark_variant=get_metadata("dark-variant") or "",
            )
        except Exception:  # noqa: BLE001 — metadata is best-effort
            log.debug("no metadata for scheme %s", scheme_id, exc_info=True)
    return variants, ids
