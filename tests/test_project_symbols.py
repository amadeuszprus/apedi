"""Project-wide symbol index."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

pytest.importorskip("gi")

from apedi import project_symbols  # noqa: E402
from apedi.symbols import extract_symbols  # noqa: E402


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    _write(root / "app" / "models.py", "class User:\n    def save(self):\n        pass\n\ndef helper():\n    pass\n")
    _write(root / "web" / "api.ts", "export class Client {}\nexport function fetchAll() {}\n")
    _write(root / "src" / "Controller.php", "<?php\nfinal class HomeController\n{\n    public function index() {}\n}\n")
    _write(root / "node_modules" / "lib" / "x.js", "function hidden() {}\n")
    _write(root / ".git" / "hooks" / "x.py", "def hidden(): pass\n")
    _write(root / "notes.txt", "class NotCode\n")
    _write(root / ".gitignore", "build/\n")
    _write(root / "build" / "gen.py", "def generated(): pass\n")
    return root


def _names(symbols: list[project_symbols.ProjectSymbol]) -> set[str]:
    return {s.name for s in symbols}


def test_indexes_supported_languages_and_skips_ignored(project: Path) -> None:
    syms = project_symbols.index_projects([project], [], cache={})
    assert _names(syms) == {"User", "User.save", "helper", "Client", "fetchAll", "HomeController", "index"}
    user = next(s for s in syms if s.name == "User")
    assert user.path == project / "app" / "models.py"
    assert user.line == 1
    assert user.kind == "class"


def test_cache_skips_unchanged_files(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cache: dict = {}
    project_symbols.index_projects([project], [], cache=cache)
    calls: list[str] = []
    real = project_symbols.extract_symbols

    def spy(lang: str | None, text: str):
        calls.append(lang or "")
        return real(lang, text)

    monkeypatch.setattr(project_symbols, "extract_symbols", spy)
    project_symbols.index_projects([project], [], cache=cache)
    assert calls == []

    target = project / "app" / "models.py"
    target.write_text("class Account:\n    pass\n")
    stat = target.stat()
    os.utime(target, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000_000))
    syms = project_symbols.index_projects([project], [], cache=cache)
    assert calls == ["python3"]
    assert "Account" in _names(syms) and "User" not in _names(syms)


def test_cancel_stops_early(project: Path) -> None:
    assert project_symbols.index_projects([project], [], cache={}, cancelled=lambda: True) == []


def test_php_symbols() -> None:
    text = (
        "<?php\nnamespace App;\n\nabstract class Base {}\ninterface Shape {}\ntrait Loggable {}\n"
        "enum Suit: string {}\nfunction top_level() {}\nclass A {\n    public static function make() {}\n"
        "    private function secret() {}\n}\n"
    )
    names = [(s.kind, s.name) for s in extract_symbols("php", text)]
    assert names == [
        ("class", "Base"), ("interface", "Shape"), ("trait", "Loggable"), ("enum", "Suit"),
        ("function", "top_level"), ("class", "A"), ("function", "make"), ("function", "secret"),
    ]


def test_filter_ranks_contiguous_matches_first() -> None:
    syms = [
        project_symbols.ProjectSymbol("r_e_n_d", "function", Path("/p/a.js"), 1),
        project_symbols.ProjectSymbol("Renderer", "class", Path("/p/b.js"), 1),
        project_symbols.ProjectSymbol("unrelated", "function", Path("/p/c.js"), 1),
    ]
    ranked = project_symbols.filter_symbols(syms, "rend")
    assert [s.name for s in ranked] == ["Renderer", "r_e_n_d"]
    assert project_symbols.filter_symbols(syms, "") == syms


def test_python_methods_are_not_listed_twice() -> None:
    names = [s.name for s in extract_symbols("python3", "class A:\n    def m(self):\n        def inner():\n            pass\n")]
    assert names.count("m") == 0 and "A.m" in names
