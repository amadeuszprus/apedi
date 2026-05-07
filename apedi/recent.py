"""Recent files list — JSON at ~/.config/apedi/recent.json."""

from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)

RECENT_PATH = Path.home() / ".config" / "apedi" / "recent.json"
MAX_RECENT = 20


def load(path: Path = RECENT_PATH) -> list[Path]:
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        log.warning("Failed to read recent files %s: %s", path, e)
        return []
    if not isinstance(raw, list):
        return []
    return [Path(p) for p in raw if isinstance(p, str)]


def save(paths: list[Path], path: Path = RECENT_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([str(p) for p in paths], indent=2), encoding="utf-8")


def add(new_path: Path, current: list[Path] | None = None) -> list[Path]:
    """Return new list with new_path on top, deduped, capped at MAX_RECENT."""
    if current is None:
        current = load()
    new_path = new_path.resolve()
    deduped = [p for p in current if p.resolve() != new_path]
    return [new_path, *deduped][:MAX_RECENT]


def filter_existing(paths: list[Path]) -> list[Path]:
    return [p for p in paths if p.exists()]
