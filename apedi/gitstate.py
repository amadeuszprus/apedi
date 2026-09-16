"""Git working-tree state for the sidebar colours and the change gutter, GTK-free."""

from __future__ import annotations

import difflib
import logging
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

log = logging.getLogger(__name__)

# difflib is quadratic in the worst case, so huge files get no gutter diff.
MAX_DIFF_LINES = 30_000

# Folder colour when several files below it differ: the loudest wins.
_PRIORITY = {"conflict": 3, "modified": 2, "added": 1}

_GIT_TIMEOUT = 15.0


# ---------- locating git ----------


def git_binary() -> str | None:
    """Path to git, preferring the copy bundled in the snap; None when there is none."""
    snap = os.environ.get("SNAP")
    if snap:
        candidate = Path(snap) / "usr" / "bin" / "git"
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return shutil.which("git")


def _git_env() -> dict[str, str]:
    env = dict(os.environ)
    snap = os.environ.get("SNAP")
    if snap:
        # Debian's git is not built with RUNTIME_PREFIX, so point it at the bundled helpers.
        env.setdefault("GIT_EXEC_PATH", str(Path(snap) / "usr" / "lib" / "git-core"))
    # Never block on a credential prompt or a pager.
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_PAGER"] = "cat"
    env.setdefault("LC_ALL", "C.UTF-8")
    return env


def _run(cwd: Path, *args: str) -> bytes | None:
    """Run one git command; stdout on success, None on any failure."""
    binary = git_binary()
    if binary is None:
        return None
    try:
        proc = subprocess.run(
            # --no-optional-locks keeps `status` from rewriting the index the watcher sees.
            [binary, "--no-optional-locks", *args], cwd=str(cwd), capture_output=True,
            timeout=_GIT_TIMEOUT, env=_git_env(),
        )
    except (OSError, subprocess.SubprocessError) as e:
        log.debug("git %s failed in %s: %s", args[0] if args else "", cwd, e)
        return None
    if proc.returncode != 0:
        log.debug("git %s exited %d in %s: %s", args[0] if args else "", proc.returncode,
                  cwd, proc.stderr.decode("utf-8", "replace").strip())
        return None
    return proc.stdout


def _decode_path(raw: bytes) -> str:
    return raw.decode("utf-8", "surrogateescape")


def repo_root(path: Path) -> Path | None:
    """Top-level directory of the repository containing `path`, or None."""
    cwd = path if path.is_dir() else path.parent
    out = _run(cwd, "rev-parse", "--show-toplevel")
    if not out:
        return None
    return Path(_decode_path(out.strip()))


# ---------- status ----------


@dataclass(frozen=True)
class RepoStatus:
    """Per-path change state for one repository, as `git status` saw it."""

    root: Path
    git_dir: Path | None = None
    files: dict[str, str] = field(default_factory=dict)
    dirs: dict[str, str] = field(default_factory=dict)
    untracked_dirs: tuple[str, ...] = ()

    def _relative(self, path: Path) -> str | None:
        # The plain comparison usually succeeds and saves a resolve() per row.
        try:
            rel = path.relative_to(self.root)
        except ValueError:
            try:
                rel = path.resolve().relative_to(self.root)
            except (ValueError, OSError):
                return None
        return PurePosixPath(rel).as_posix()

    def state_for(self, path: Path) -> str | None:
        """"modified" | "added" | "conflict" for a file or folder, else None."""
        rel = self._relative(path)
        if rel is None:
            return None
        if rel == ".":
            rel = ""
        state = self.files.get(rel) or self.dirs.get(rel)
        if state:
            return state
        for prefix in self.untracked_dirs:
            if rel == prefix or rel.startswith(prefix + "/"):
                return "added"
        return None


def _state_for_code(code: str) -> tuple[str | None, bool]:
    """Map a porcelain XY code to (state, present); deleted paths still colour their folders."""
    x, y = code[0], code[1]
    if code == "??":
        return "added", True
    if "U" in code or code in ("AA", "DD"):
        return "conflict", True
    if y == "D" or (x == "D" and y == " "):
        return "modified", False
    if x == "A" and y == " ":
        return "added", True
    return "modified", True


def _bump(table: dict[str, str], key: str, state: str) -> None:
    current = table.get(key)
    if current is None or _PRIORITY[state] > _PRIORITY[current]:
        table[key] = state


def parse_porcelain(data: bytes, root: Path) -> RepoStatus:
    """Parse `git status --porcelain=v1 -z --no-renames` output."""
    files: dict[str, str] = {}
    dirs: dict[str, str] = {}
    untracked_dirs: list[str] = []
    for raw in data.split(b"\0"):
        if len(raw) < 4:
            continue
        code = raw[:2].decode("ascii", "replace")
        rel = _decode_path(raw[3:])
        if code == "??" and rel.endswith("/"):
            untracked_dirs.append(rel.rstrip("/"))
            rel = rel.rstrip("/")
            state, present = "added", True
        else:
            state, present = _state_for_code(code)
        if state is None:
            continue
        if present and rel not in untracked_dirs:
            files[rel] = state
        parts = rel.split("/")
        for depth in range(len(parts)):
            _bump(dirs, "/".join(parts[:depth]), state)
    return RepoStatus(
        root=root, files=files, dirs=dirs, untracked_dirs=tuple(untracked_dirs),
    )


def status(project: Path) -> RepoStatus | None:
    """Change state for everything under `project`, or None outside a repo."""
    root = repo_root(project)
    if root is None:
        return None
    out = _run(
        project, "status", "--porcelain=v1", "-z", "--no-renames",
        "--untracked-files=normal", "--ignored=no", "--", ".",
    )
    if out is None:
        return None
    parsed = parse_porcelain(out, root)
    git_dir_out = _run(root, "rev-parse", "--absolute-git-dir")
    git_dir = Path(_decode_path(git_dir_out.strip())) if git_dir_out else None
    return RepoStatus(
        root=parsed.root, git_dir=git_dir, files=parsed.files, dirs=parsed.dirs,
        untracked_dirs=parsed.untracked_dirs,
    )


# ---------- HEAD content for the gutter ----------


def head_text(root: Path, file: Path, encoding: str) -> str | None:
    """Contents of `file` as committed in HEAD; None if HEAD has no such file."""
    try:
        rel = file.resolve().relative_to(root.resolve())
    except (ValueError, OSError):
        return None
    out = _run(root, "show", f"HEAD:./{PurePosixPath(rel).as_posix()}")
    if out is None:
        return None
    return out.decode(encoding or "utf-8", errors="replace")


@dataclass(frozen=True)
class LineMarks:
    """Gutter marks as 0-based buffer lines; `deleted` holds the line below each removed block."""

    added: frozenset[int] = frozenset()
    modified: frozenset[int] = frozenset()
    deleted: frozenset[int] = frozenset()

    def is_empty(self) -> bool:
        return not (self.added or self.modified or self.deleted)


EMPTY_MARKS = LineMarks()


def line_marks(base: str | None, current: str) -> LineMarks:
    """Diff `current` against `base` line by line into gutter marks."""
    if base is None:
        return EMPTY_MARKS
    old = base.split("\n")
    new = current.split("\n")
    if len(old) > MAX_DIFF_LINES or len(new) > MAX_DIFF_LINES:
        return EMPTY_MARKS
    added: set[int] = set()
    modified: set[int] = set()
    deleted: set[int] = set()
    matcher = difflib.SequenceMatcher(None, old, new, autojunk=False)
    for tag, _i1, _i2, j1, j2 in matcher.get_opcodes():
        if tag == "insert":
            added.update(range(j1, j2))
        elif tag == "replace":
            modified.update(range(j1, j2))
        elif tag == "delete":
            deleted.add(j1)
    return LineMarks(frozenset(added), frozenset(modified), frozenset(deleted))
