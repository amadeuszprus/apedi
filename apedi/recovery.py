"""Draft persistence — keep an unsaved-buffer copy on disk so a crash
or kernel OOM does not lose work between explicit saves."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)


def _drafts_dir() -> Path:
    snap_user = os.environ.get("SNAP_USER_COMMON")
    if snap_user:
        return Path(snap_user) / "drafts"
    return Path.home() / ".cache" / "apedi" / "drafts"


def _slug_for_path(path: Path) -> str:
    h = hashlib.sha1(str(path.resolve()).encode("utf-8", errors="replace"))
    return h.hexdigest()[:16]


@dataclass
class Draft:
    original_path: Path
    body: str
    encoding: str
    saved_at: float
    base_mtime: float | None  # mtime of original at the time the buffer was loaded
    draft_path: Path


def save(path: Path, body: str, encoding: str, base_mtime: float | None) -> None:
    """Write a draft for `path`. Cheap to call after every keystroke (small
    files) — for very large files the caller should debounce."""
    try:
        directory = _drafts_dir()
        directory.mkdir(parents=True, exist_ok=True)
        slug = _slug_for_path(path)
        meta = {
            "path": str(path),
            "encoding": encoding,
            "saved_at": time.time(),
            "base_mtime": base_mtime,
        }
        (directory / f"{slug}.json").write_text(
            json.dumps(meta), encoding="utf-8",
        )
        (directory / f"{slug}.body").write_text(body, encoding=encoding, errors="replace")
    except OSError as e:
        log.debug("draft save failed for %s: %s", path, e)


def discard(path: Path) -> None:
    try:
        slug = _slug_for_path(path)
        directory = _drafts_dir()
        for suffix in (".json", ".body"):
            f = directory / f"{slug}{suffix}"
            if f.exists():
                f.unlink()
    except OSError as e:
        log.debug("draft discard failed for %s: %s", path, e)


def list_pending() -> list[Draft]:
    """Return every draft whose body differs from the on-disk original
    (mtime increased since the draft was written, or the file is missing)."""
    out: list[Draft] = []
    directory = _drafts_dir()
    if not directory.exists():
        return out
    for meta_file in directory.glob("*.json"):
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        slug = meta_file.stem
        body_file = directory / f"{slug}.body"
        if not body_file.exists():
            continue
        original = Path(meta.get("path", ""))
        encoding = str(meta.get("encoding", "utf-8"))
        saved_at = float(meta.get("saved_at", 0))
        base_mtime = meta.get("base_mtime")
        try:
            body = body_file.read_text(encoding=encoding, errors="replace")
        except OSError:
            continue
        out.append(Draft(
            original_path=original, body=body, encoding=encoding,
            saved_at=saved_at, base_mtime=base_mtime, draft_path=meta_file,
        ))
    return out


def clear_all() -> None:
    directory = _drafts_dir()
    if not directory.exists():
        return
    for f in directory.iterdir():
        try:
            f.unlink()
        except OSError:
            pass
