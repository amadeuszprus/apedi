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
    """Persist a list of window states. Each window: {tabs: [...], active: int}."""
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


def clear() -> None:
    try:
        SESSION_PATH.unlink(missing_ok=True)
    except OSError as e:
        log.debug("session clear failed: %s", e)
