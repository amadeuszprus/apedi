from pathlib import Path

import pytest

from apedi import ignore_filter
from apedi.ignore_filter import IgnoreFilter


@pytest.fixture
def root(tmp_path: Path) -> Path:
    (tmp_path / ".gitignore").write_text("build/\n*.log\n", encoding="utf-8")
    (tmp_path / "build").mkdir()
    (tmp_path / "src").mkdir()
    (tmp_path / "app.log").write_text("", encoding="utf-8")
    return tmp_path


needs_pathspec = pytest.mark.skipif(not ignore_filter._HAS_PATHSPEC, reason="pathspec missing")


@needs_pathspec
def test_matches_files_and_folders(root: Path) -> None:
    f = IgnoreFilter(root, [])
    assert f.is_ignored(root / "app.log")
    assert f.is_ignored(root / "build")
    assert not f.is_ignored(root / "src")


@needs_pathspec
def test_is_dir_hint_avoids_the_stat(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    f = IgnoreFilter(root, [])

    def no_stat(self: Path) -> bool:
        raise AssertionError("is_dir() should not be called when the hint is given")

    monkeypatch.setattr(Path, "is_dir", no_stat)
    assert f.is_ignored(root / "build", is_dir=True)
    assert not f.is_ignored(root / "src", is_dir=True)


@needs_pathspec
def test_paths_under_the_root_do_not_resolve(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    f = IgnoreFilter(root, [])

    def no_resolve(self: Path, strict: bool = False) -> Path:
        raise AssertionError("resolve() should not be needed for a path under the root")

    monkeypatch.setattr(Path, "resolve", no_resolve)
    assert f.is_ignored(root / "app.log", is_dir=False)


def test_outside_root_is_not_ignored(root: Path) -> None:
    f = IgnoreFilter(root, [])
    assert not f.is_ignored(Path("/elsewhere/app.log"))
