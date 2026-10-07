"""Hide / restore Apedi's entry in the desktop's right-click 'Open with' menu.

Snapd installs `<snap>_<app>.desktop` into the system's desktop database.
To suppress that entry per-user without uninstalling the snap, we write
a same-named override into ~/.local/share/applications/ with
NoDisplay=true. Removing the override re-exposes the snap's default.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from .shell import real_home

log = logging.getLogger(__name__)

_OVERRIDE_BODY = (
    "[Desktop Entry]\n"
    "Type=Application\n"
    "Name=Apedi\n"
    "NoDisplay=true\n"
    "Hidden=true\n"
)

_writable: bool | None = None


def _override_path() -> Path:
    # The real home, not $HOME: inside a snap that points at the snap's own data directory.
    snap_name = os.environ.get("SNAP_INSTANCE_NAME", "apedi")
    return real_home() / ".local" / "share" / "applications" / f"{snap_name}_apedi.desktop"


def available() -> bool:
    """Whether the entry can be changed at all; a confined snap cannot write there."""
    global _writable
    if _writable is None:
        probe = _override_path().with_suffix(".apedi-probe")
        try:
            probe.parent.mkdir(parents=True, exist_ok=True)
            probe.write_text("", encoding="utf-8")
            probe.unlink()
            _writable = True
        except OSError:
            _writable = False
    return _writable


def is_hidden() -> bool:
    """Whether an override is currently hiding Apedi from the file manager."""
    try:
        return "Hidden=true" in _override_path().read_text(encoding="utf-8")
    except OSError:
        return False


def apply(register: bool) -> bool:
    """Write or remove the override; False means the desktop entry could not be changed.

    If register=True, remove the user-local override.
    If register=False, write the override that hides Apedi from the launcher
    and from file-manager 'Open with' lists.
    """
    path = _override_path()
    try:
        if register:
            if path.exists():
                path.unlink()
                log.info("removed desktop override at %s", path)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(_OVERRIDE_BODY, encoding="utf-8")
            log.info("wrote desktop override at %s", path)
    except OSError as e:
        log.warning("desktop override update failed: %s", e)
        return False
    return True


def stranded_override() -> Path | None:
    """An override left by a run outside the snap, which the snap cannot delete itself."""
    if is_hidden() and not available():
        return _override_path()
    return None
