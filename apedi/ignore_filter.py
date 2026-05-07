"""Gitignore + heavy-folder + custom-pattern path filter for the sidebar."""

from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger(__name__)

try:
    import pathspec
    _HAS_PATHSPEC = True
except ImportError:
    pathspec = None  # type: ignore[assignment]
    _HAS_PATHSPEC = False


HEAVY_DIRS = frozenset({
    ".git", "node_modules", "__pycache__",
    ".venv", "venv", ".env",
    "target", "dist", "build", "out",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox",
    ".cache", ".idea", ".vscode",
    "vendor", ".gradle", ".cargo",
    "Pods", "DerivedData",
})


class IgnoreFilter:
    """Matches paths against .gitignore + heavy dirs + user-configured patterns."""

    def __init__(self, root: Path, extra_patterns: list[str] | None = None) -> None:
        self.root = root.resolve()
        self.extra_patterns = [p.strip() for p in (extra_patterns or []) if p.strip()]
        self._spec = self._build_spec() if _HAS_PATHSPEC else None

    def _build_spec(self):
        patterns: list[str] = list(self.extra_patterns)
        gitignore = self.root / ".gitignore"
        if gitignore.exists():
            try:
                patterns.extend(gitignore.read_text(encoding="utf-8").splitlines())
            except OSError as e:
                log.debug("cannot read %s: %s", gitignore, e)
        return pathspec.PathSpec.from_lines("gitwildmatch", patterns) if patterns else None

    def is_ignored(self, path: Path) -> bool:
        try:
            rel = path.resolve().relative_to(self.root)
        except (ValueError, OSError):
            return False
        if self._spec is not None and self._spec.match_file(str(rel)):
            return True
        if self._spec is not None and path.is_dir():
            if self._spec.match_file(str(rel) + "/"):
                return True
        return False

    def is_heavy(self, path: Path) -> bool:
        return path.name in HEAVY_DIRS
