"""Which shell the integrated terminal should run, kept free of Vte for testing."""

from __future__ import annotations

import logging
import os
import pwd
from pathlib import Path

log = logging.getLogger(__name__)


def user_shell_name() -> str:
    """Basename of the login shell from passwd; snapd exports SHELL=/bin/bash, so it is only a fallback."""
    try:
        pw_shell = pwd.getpwuid(os.getuid()).pw_shell
    except (KeyError, OSError):
        pw_shell = ""
    if pw_shell:
        return Path(pw_shell).name
    shell_env = os.environ.get("SHELL", "")
    if shell_env:
        return Path(shell_env).name
    return ""


def resolve_shell() -> str:
    """Pick the shell binary by the user's basename, bundled copies first."""
    snap = os.environ.get("SNAP", "")
    name = user_shell_name()

    candidates: list[str] = []
    if name:
        candidates += [
            f"{snap}/bin/{name}",
            f"{snap}/usr/bin/{name}",
            f"/bin/{name}",
            f"/usr/bin/{name}",
        ]
    # Fallback chain when the requested shell is not packaged
    candidates += [
        f"{snap}/bin/zsh",
        f"{snap}/usr/bin/zsh",
        f"{snap}/bin/bash",
        f"{snap}/usr/bin/bash",
        "/bin/zsh", "/usr/bin/zsh",
        "/bin/bash", "/usr/bin/bash",
        "/bin/sh",
    ]
    for path in candidates:
        if path and Path(path).exists():
            log.info("terminal shell: %s (preferred basename: %r)", path, name)
            return path
    return "/bin/sh"


def spawn_env(shell: str) -> list[str]:
    """Environment for the terminal child with SHELL set to the shell actually started."""
    env = dict(os.environ)
    env["SHELL"] = shell
    return [f"{k}={v}" for k, v in env.items()]
