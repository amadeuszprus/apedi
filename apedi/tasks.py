"""Runnable tasks found in a project: build files, package scripts and .apedi/tasks.toml."""

from __future__ import annotations

import json
import logging
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

OWN_TASKS = Path(".apedi") / "tasks.toml"

_MAKE_TARGET = re.compile(r"^([A-Za-z0-9][A-Za-z0-9_.\-/]*)\s*:(?![=:])", re.MULTILINE)
_JUST_RECIPE = re.compile(r"^@?([A-Za-z0-9][A-Za-z0-9_-]*)(?:\s+[^:=\n]*)?:(?!=)", re.MULTILINE)


@dataclass(frozen=True)
class Task:
    name: str
    command: str
    cwd: Path
    source: str
    project: Path


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _json(path: Path) -> dict:
    text = _read(path)
    if text is None:
        return {}
    try:
        data = json.loads(text)
    except ValueError:
        log.debug("unreadable %s", path)
        return {}
    return data if isinstance(data, dict) else {}


def _toml(path: Path) -> dict:
    text = _read(path)
    if text is None:
        return {}
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        log.debug("unreadable %s", path)
        return {}


def _own(root: Path) -> list[Task]:
    out = []
    for name, spec in (_toml(root / OWN_TASKS).get("tasks") or {}).items():
        if isinstance(spec, str):
            command, cwd = spec, root
        elif isinstance(spec, dict) and isinstance(spec.get("command"), str):
            command = spec["command"]
            cwd = root / spec["cwd"] if isinstance(spec.get("cwd"), str) else root
        else:
            continue
        out.append(Task(str(name), command, cwd, "tasks.toml", root))
    return out


def _make(root: Path) -> list[Task]:
    for name in ("GNUmakefile", "makefile", "Makefile"):
        text = _read(root / name)
        if text is None:
            continue
        targets: list[str] = []
        for target in _MAKE_TARGET.findall(text):
            if "%" not in target and target not in targets:
                targets.append(target)
        return [Task(t, f"make {t}", root, "make", root) for t in targets]
    return []


def _node(root: Path) -> list[Task]:
    scripts = _json(root / "package.json").get("scripts")
    if not isinstance(scripts, dict):
        return []
    if (root / "pnpm-lock.yaml").exists():
        run = "pnpm run {}"
    elif (root / "yarn.lock").exists():
        run = "yarn {}"
    elif (root / "bun.lockb").exists() or (root / "bun.lock").exists():
        run = "bun run {}"
    else:
        run = "npm run {}"
    return [Task(name, run.format(name), root, "package.json", root) for name in scripts]


def _composer(root: Path) -> list[Task]:
    scripts = _json(root / "composer.json").get("scripts")
    if not isinstance(scripts, dict):
        return []
    # pre-/post- entries are hooks Composer runs itself, not tasks to pick.
    names = [n for n in scripts if not n.startswith(("pre-", "post-"))]
    return [Task(n, f"composer run-script {n}", root, "composer.json", root) for n in names]


def _python(root: Path) -> list[Task]:
    data = _toml(root / "pyproject.toml")
    tool = data.get("tool") or {}
    out = [Task(n, f"poe {n}", root, "poe", root) for n in (tool.get("poe") or {}).get("tasks") or {}]
    out += [Task(n, f"pdm run {n}", root, "pdm", root) for n in (tool.get("pdm") or {}).get("scripts") or {}]
    if "pytest" in tool or (root / "pytest.ini").exists():
        out.append(Task("pytest", "python3 -m pytest", root, "pytest", root))
    return out


def _just(root: Path) -> list[Task]:
    for name in ("justfile", "Justfile", ".justfile"):
        text = _read(root / name)
        if text is not None:
            recipes = [r for r in _JUST_RECIPE.findall(text) if r not in ("set", "alias", "export")]
            return [Task(r, f"just {r}", root, "just", root) for r in dict.fromkeys(recipes)]
    return []


def _toolchains(root: Path) -> list[Task]:
    out = []
    if (root / "Cargo.toml").exists():
        out += [Task(c, f"cargo {c}", root, "cargo", root) for c in ("build", "test", "run")]
    if (root / "go.mod").exists():
        out += [Task(c, f"go {c} ./...", root, "go", root) for c in ("build", "test")]
    return out


def detect_tasks(root: Path) -> list[Task]:
    """Every task the project offers, the user's own .apedi/tasks.toml first."""
    out: list[Task] = []
    for finder in (_own, _make, _node, _composer, _python, _just, _toolchains):
        try:
            out.extend(finder(root))
        except Exception:  # noqa: BLE001
            log.debug("task detection failed in %s for %s", finder.__name__, root, exc_info=True)
    return out
