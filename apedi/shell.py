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


def real_home() -> Path:
    """The user's home from passwd; inside a snap $HOME points at the snap's own data directory."""
    try:
        pw_dir = pwd.getpwuid(os.getuid()).pw_dir
    except (KeyError, OSError):
        pw_dir = ""
    return Path(pw_dir) if pw_dir else Path.home()


def _readable(path: Path) -> bool:
    """Whether the file can really be read; os.access only checks permissions, not confinement."""
    try:
        with path.open("rb") as handle:
            handle.read(1)
    except OSError:
        return False
    return True


def zsh_zdotdir(shell: str) -> str | None:
    """Apedi's own zsh startup files, used only where the user's own ones are out of reach."""
    snap = os.environ.get("SNAP", "")
    if not snap or Path(shell).name != "zsh":
        return None
    if _readable(real_home() / ".zshrc"):
        return None
    zdotdir = Path(snap) / "usr/share/apedi/zdotdir"
    return str(zdotdir) if zdotdir.is_dir() else None


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
    zdotdir = zsh_zdotdir(shell)
    if zdotdir is not None:
        env["ZDOTDIR"] = zdotdir
    return [f"{k}={v}" for k, v in env.items()]
