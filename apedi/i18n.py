"""Translation setup. Use the underscore alias for marking strings."""

from __future__ import annotations

import gettext
import locale
import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)

DOMAIN = "apedi"


def _candidate_localedirs() -> list[Path]:
    candidates: list[Path] = []
    snap = os.environ.get("SNAP")
    if snap:
        candidates.append(Path(snap) / "usr" / "share" / "locale")
    candidates.append(Path(__file__).resolve().parent.parent / "build" / "locale")
    candidates.append(Path("/usr/share/locale"))
    return candidates


def _resolve_locale_dir() -> Path | None:
    for cand in _candidate_localedirs():
        if (cand / "pl" / "LC_MESSAGES" / f"{DOMAIN}.mo").exists():
            return cand
    return None


def install(language: str = "auto") -> None:
    """Install the global _() builtin. language is "auto" / "en" / "pl"."""
    if language == "auto":
        env = os.environ.get("LANG", "") or os.environ.get("LC_ALL", "")
        languages = [env.split(".")[0]] if env else None
    elif language and language != "en":
        languages = [language]
    else:
        languages = ["en"]

    localedir = _resolve_locale_dir()
    try:
        translation = gettext.translation(
            DOMAIN, localedir=str(localedir) if localedir else None,
            languages=languages, fallback=True,
        )
    except Exception as e:  # noqa: BLE001
        log.debug("gettext install fallback: %s", e)
        translation = gettext.NullTranslations()
    translation.install()  # adds builtin _()


def configure_locale() -> None:
    try:
        locale.setlocale(locale.LC_ALL, "")
    except locale.Error:
        pass
