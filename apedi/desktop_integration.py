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

log = logging.getLogger(__name__)

_OVERRIDE_BODY = (
    "[Desktop Entry]\n"
    "Type=Application\n"
    "Name=Apedi\n"
    "NoDisplay=true\n"
    "Hidden=true\n"
)


def _override_path() -> Path:
    snap_name = os.environ.get("SNAP_INSTANCE_NAME", "apedi")
    app_name = "apedi"
    return Path.home() / ".local" / "share" / "applications" / f"{snap_name}_{app_name}.desktop"


def apply(register: bool) -> None:
    """If register=True, remove the user-local override.
    If register=False, write the override that hides Apedi from the launcher
    and from file-manager 'Open with' lists."""
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
