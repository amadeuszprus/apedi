"""External code formatters — bundled in snap, fallback to PATH in dev."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

FORMAT_TIMEOUT_S = 5.0


@dataclass(frozen=True)
class FormatterSpec:
    binary: str          # name of binary, e.g. "black"
    snap_path: str       # absolute path inside snap, used when SNAP env is set
    args: tuple[str, ...] = ()
    use_filename: bool = False  # if True, expand {filename} in args


# language_id (GtkSourceView) → formatter spec
FORMATTERS: dict[str, FormatterSpec] = {
    "python3": FormatterSpec("black", "/bin/black", ("-q", "-")),
    "python": FormatterSpec("black", "/bin/black", ("-q", "-")),
    "js": FormatterSpec("prettier", "/lib/node_modules/.bin/prettier", ("--stdin-filepath", "{filename}"), use_filename=True),
    "javascript": FormatterSpec("prettier", "/lib/node_modules/.bin/prettier", ("--stdin-filepath", "{filename}"), use_filename=True),
    "typescript": FormatterSpec("prettier", "/lib/node_modules/.bin/prettier", ("--stdin-filepath", "{filename}"), use_filename=True),
    "json": FormatterSpec("prettier", "/lib/node_modules/.bin/prettier", ("--stdin-filepath", "{filename}"), use_filename=True),
    "html": FormatterSpec("prettier", "/lib/node_modules/.bin/prettier", ("--stdin-filepath", "{filename}"), use_filename=True),
    "css": FormatterSpec("prettier", "/lib/node_modules/.bin/prettier", ("--stdin-filepath", "{filename}"), use_filename=True),
    "markdown": FormatterSpec("prettier", "/lib/node_modules/.bin/prettier", ("--stdin-filepath", "{filename}"), use_filename=True),
    "yaml": FormatterSpec("prettier", "/lib/node_modules/.bin/prettier", ("--stdin-filepath", "{filename}"), use_filename=True),
    "go": FormatterSpec("gofmt", "/usr/bin/gofmt", ()),
    "rust": FormatterSpec("rustfmt", "/usr/bin/rustfmt", ("--emit=stdout", "--quiet")),
    "c": FormatterSpec("clang-format", "/usr/bin/clang-format", ("--assume-filename={filename}",), use_filename=True),
    "cpp": FormatterSpec("clang-format", "/usr/bin/clang-format", ("--assume-filename={filename}",), use_filename=True),
    "chdr": FormatterSpec("clang-format", "/usr/bin/clang-format", ("--assume-filename={filename}",), use_filename=True),
    "cpphdr": FormatterSpec("clang-format", "/usr/bin/clang-format", ("--assume-filename={filename}",), use_filename=True),
    "java": FormatterSpec("clang-format", "/usr/bin/clang-format", ("--assume-filename={filename}",), use_filename=True),
    "c-sharp": FormatterSpec("clang-format", "/usr/bin/clang-format", ("--assume-filename={filename}",), use_filename=True),
    "sh": FormatterSpec("shfmt", "/usr/bin/shfmt", ("-",)),
    "bash": FormatterSpec("shfmt", "/usr/bin/shfmt", ("-",)),
}


class FormatError(Exception):
    """Formatter failed — message is user-facing."""


def supports(language_id: str | None) -> bool:
    return language_id is not None and language_id in FORMATTERS


def resolve_binary(spec: FormatterSpec) -> str | None:
    """Find binary: $SNAP-prefixed path inside snap, otherwise PATH."""
    snap = os.environ.get("SNAP")
    if snap:
        candidate = snap + spec.snap_path
        if Path(candidate).exists():
            return candidate
    return shutil.which(spec.binary)


def format_text(language_id: str, text: str, filename: str = "stdin") -> str:
    """Run formatter, return formatted text. Raises FormatError on any failure."""
    spec = FORMATTERS.get(language_id)
    if spec is None:
        raise FormatError(f"No formatter for language: {language_id}")

    binary = resolve_binary(spec)
    if binary is None:
        raise FormatError(f"Formatter not found: {spec.binary}")

    args = [a.replace("{filename}", filename) if spec.use_filename else a for a in spec.args]
    cmd = [binary, *args]

    try:
        result = subprocess.run(
            cmd,
            input=text,
            capture_output=True,
            text=True,
            timeout=FORMAT_TIMEOUT_S,
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        raise FormatError(f"Format timed out after {FORMAT_TIMEOUT_S}s") from e
    except FileNotFoundError as e:
        raise FormatError(f"Formatter binary missing: {binary}") from e

    if result.returncode != 0:
        first_line = (result.stderr or result.stdout or "unknown error").splitlines()[0][:200]
        log.warning("Formatter %s failed (exit %d): %s", spec.binary, result.returncode, result.stderr)
        raise FormatError(f"Format failed: {first_line}")

    return result.stdout
