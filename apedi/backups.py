"""Conflict backups — a timestamped copy of an unsaved buffer, kept out of
the user's project tree.

Written when a file changes underneath a tab that still has local edits, so
that reloading from disk can never be the move that loses work. Unlike
`recovery` drafts, these are not tied to a session and are never discarded on
save: they age out after `DEFAULT_MAX_AGE_DAYS`.
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

DEFAULT_MAX_AGE_DAYS = 30


def _backups_dir() -> Path:
    snap_user = os.environ.get("SNAP_USER_COMMON")
    if snap_user:
        return Path(snap_user) / "backups"
    return Path.home() / ".cache" / "apedi" / "backups"


def backups_dir() -> Path:
    """Public accessor — also used by the 'Open Backups Folder' action."""
    return _backups_dir()


def save_copy(path: Path, body: str, encoding: str = "utf-8") -> Path | None:
    """Write `body` to a timestamped copy of `path`. None if that failed.

    Never raises: losing the backup must not also break the reload it is
    protecting.
    """
    try:
        directory = _backups_dir()
        directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = directory / f"{path.stem}-{stamp}{path.suffix}"
        # Two conflicts on the same file within one second is unlikely but
        # would otherwise overwrite the older copy — the one thing this
        # module exists to prevent.
        counter = 2
        while target.exists():
            target = directory / f"{path.stem}-{stamp}-{counter}{path.suffix}"
            counter += 1
        target.write_text(body, encoding=encoding, errors="replace")
        return target
    except (OSError, LookupError) as e:
        log.warning("conflict backup failed for %s: %s", path, e)
        return None


def prune(max_age_days: int = DEFAULT_MAX_AGE_DAYS) -> None:
    """Delete backups older than `max_age_days`. Silent on any failure."""
    directory = _backups_dir()
    if not directory.is_dir():
        return
    cutoff = time.time() - max_age_days * 86400
    for entry in directory.iterdir():
        try:
            if entry.is_file() and entry.stat().st_mtime < cutoff:
                entry.unlink()
        except OSError as e:
            log.debug("backup prune skipped %s: %s", entry, e)
