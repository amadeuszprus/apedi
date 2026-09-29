"""Detecting runnable tasks in a project."""

from __future__ import annotations

import json
from pathlib import Path

from apedi.tasks import Task, detect_tasks


def _commands(tasks: list[Task]) -> list[str]:
    return [t.command for t in tasks]


def test_makefile_targets(tmp_path: Path) -> None:
    (tmp_path / "Makefile").write_text(
        "VAR := 1\nOTHER = 2\n.PHONY: build test\n\nbuild: deps\n\tgo build\n"
        "test:\n\tgo test\n%.o: %.c\n\tcc\ndeps:\n\ttrue\nbuild: extra\n"
    )
    assert _commands(detect_tasks(tmp_path)) == ["make build", "make test", "make deps"]


def test_npm_scripts_use_the_lockfile_runner(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {"dev": "vite", "build": "vite build"}}))
    assert _commands(detect_tasks(tmp_path)) == ["npm run dev", "npm run build"]
    (tmp_path / "pnpm-lock.yaml").write_text("")
    assert _commands(detect_tasks(tmp_path)) == ["pnpm run dev", "pnpm run build"]
    (tmp_path / "pnpm-lock.yaml").unlink()
    (tmp_path / "yarn.lock").write_text("")
    assert _commands(detect_tasks(tmp_path)) == ["yarn dev", "yarn build"]


def test_composer_scripts_skip_event_hooks(tmp_path: Path) -> None:
    (tmp_path / "composer.json").write_text(json.dumps({"scripts": {
        "test": "phpunit", "post-install-cmd": ["x"], "pre-update-cmd": "y", "cs": "php-cs-fixer fix",
    }}))
    assert _commands(detect_tasks(tmp_path)) == ["composer run-script test", "composer run-script cs"]


def test_pyproject_tools(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[tool.poe.tasks]\nlint = "ruff check ."\n'
        '[tool.pdm.scripts]\nserve = "python -m http.server"\n'
        "[tool.pytest.ini_options]\ntestpaths = ['tests']\n"
    )
    assert _commands(detect_tasks(tmp_path)) == ["poe lint", "pdm run serve", "python3 -m pytest"]


def test_justfile_cargo_and_go(tmp_path: Path) -> None:
    (tmp_path / "justfile").write_text("set shell := [\"bash\"]\ndefault:\n  echo\nrelease version:\n  echo\n")
    (tmp_path / "Cargo.toml").write_text("[package]\nname='x'\n")
    (tmp_path / "go.mod").write_text("module x\n")
    assert _commands(detect_tasks(tmp_path)) == [
        "just default", "just release",
        "cargo build", "cargo test", "cargo run",
        "go build ./...", "go test ./...",
    ]


def test_own_tasks_come_first_and_support_cwd(tmp_path: Path) -> None:
    (tmp_path / ".apedi").mkdir()
    (tmp_path / "backend").mkdir()
    (tmp_path / ".apedi" / "tasks.toml").write_text(
        '[tasks]\ndeploy = "./deploy.sh"\ntest = { command = "pytest -q", cwd = "backend" }\n'
    )
    (tmp_path / "Makefile").write_text("all:\n\ttrue\n")
    tasks = detect_tasks(tmp_path)
    assert [(t.name, t.command, t.cwd, t.source) for t in tasks] == [
        ("deploy", "./deploy.sh", tmp_path, "tasks.toml"),
        ("test", "pytest -q", tmp_path / "backend", "tasks.toml"),
        ("all", "make all", tmp_path, "make"),
    ]


def test_broken_files_are_ignored(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text("{not json")
    (tmp_path / "pyproject.toml").write_text("[[[")
    assert detect_tasks(tmp_path) == []
