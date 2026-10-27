"""Session persistence — reopen the last window/tab layout on startup.

Stored as JSON at ~/.cache/apedi/session.json. Only files with a real path
are remembered (scratch buffers and unsaved content live in recovery drafts).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)

CACHE_DIR = Path.home() / ".cache" / "apedi"
SESSION_PATH = CACHE_DIR / "session.json"


def save(windows: list[dict]) -> None:
    """Persist tab layout and presentation state for every open window."""
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        SESSION_PATH.write_text(
            json.dumps({"windows": windows}), encoding="utf-8"
        )
    except OSError as e:
        log.debug("session save failed: %s", e)


def load() -> list[dict]:
    try:
        data = json.loads(SESSION_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, dict):
        return []
    windows = data.get("windows", [])
    return windows if isinstance(windows, list) else []


def ordered_tabs(state: dict) -> list[dict]:
    """Return restorable tabs with the active one first.

    Session files store tabs in their visual order, grouped left-to-right.
    Startup wants the selected tab first so useful content appears quickly;
    callers can restore the original order after all tabs have been opened.
    """
    raw_tabs = state.get("tabs", [])
    if not isinstance(raw_tabs, list):
        return []
    tabs = [tab for tab in raw_tabs if isinstance(tab, dict)]
    if not tabs:
        return []

    active_group = state.get("active_group", 0)
    if not isinstance(active_group, int) or active_group not in (0, 1):
        active_group = 0
    pages = state.get("group_pages")
    if not isinstance(pages, list):
        pages = [state.get("active", 0)]
    active_page = pages[active_group] if active_group < len(pages) else 0
    if not isinstance(active_page, int):
        active_page = 0

    in_active_group = [tab for tab in tabs if tab.get("group", 0) == active_group]
    active = (
        in_active_group[active_page]
        if 0 <= active_page < len(in_active_group)
        else (in_active_group[0] if in_active_group else tabs[0])
    )
    return [active, *(tab for tab in tabs if tab is not active)]


def clear() -> None:
    try:
        SESSION_PATH.unlink(missing_ok=True)
    except OSError as e:
        log.debug("session clear failed: %s", e)
