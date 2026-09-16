"""Tests for the git state behind the sidebar colours and the change gutter."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from apedi import gitstate
from apedi.gitstate import RepoStatus, line_marks, parse_porcelain

ROOT = Path("/repo")


def _status(*entries: str) -> RepoStatus:
    """Build a RepoStatus from porcelain v1 lines like "?? new.txt"."""
    data = b"".join(e.encode() + b"\0" for e in entries)
    return parse_porcelain(data, ROOT)


# ---------- porcelain parsing ----------


def test_empty_output_means_clean_tree() -> None:
    status = _status()
    assert status.state_for(ROOT / "a.py") is None
    assert status.state_for(ROOT) is None


def test_untracked_file_is_added() -> None:
    status = _status("?? new.txt")
    assert status.state_for(ROOT / "new.txt") == "added"


def test_index_added_file_is_added() -> None:
    status = _status("A  new.txt")
    assert status.state_for(ROOT / "new.txt") == "added"


@pytest.mark.parametrize("code", [" M", "M ", "MM", "T ", " T", "AM", "RM"])
def test_changed_file_is_modified(code: str) -> None:
    status = _status(f"{code} src/app.py")
    assert status.state_for(ROOT / "src" / "app.py") == "modified"


@pytest.mark.parametrize("code", ["UU", "AA", "DD", "AU", "UD", "DU", "UA"])
def test_unmerged_file_is_conflict(code: str) -> None:
    status = _status(f"{code} src/app.py")
    assert status.state_for(ROOT / "src" / "app.py") == "conflict"


def test_deleted_file_is_not_reported() -> None:
    status = _status(" D gone.txt", "D  also-gone.txt")
    assert status.state_for(ROOT / "gone.txt") is None
    assert status.state_for(ROOT / "also-gone.txt") is None


def test_untracked_directory_covers_everything_below_it() -> None:
    status = _status("?? scratch/")
    assert status.state_for(ROOT / "scratch") == "added"
    assert status.state_for(ROOT / "scratch" / "deep" / "file.py") == "added"
    assert status.state_for(ROOT / "scratchy.txt") is None


def test_folders_take_the_state_of_their_contents() -> None:
    status = _status(" M src/pkg/mod.py")
    assert status.state_for(ROOT / "src") == "modified"
    assert status.state_for(ROOT / "src" / "pkg") == "modified"
    assert status.state_for(ROOT / "src" / "other") is None


def test_repo_root_itself_takes_a_state() -> None:
    status = _status("?? new.txt")
    assert status.state_for(ROOT) == "added"


def test_folder_state_priority_conflict_over_modified_over_added() -> None:
    status = _status("?? src/new.txt", " M src/a.py", "UU src/b.py")
    assert status.state_for(ROOT / "src") == "conflict"
    status = _status("?? src/new.txt", " M src/a.py")
    assert status.state_for(ROOT / "src") == "modified"
    status = _status("?? src/new.txt")
    assert status.state_for(ROOT / "src") == "added"


def test_deleted_files_still_mark_their_folder() -> None:
    status = _status(" D src/gone.py")
    assert status.state_for(ROOT / "src") == "modified"


def test_paths_outside_the_repo_have_no_state() -> None:
    status = _status(" M a.py")
    assert status.state_for(Path("/elsewhere/a.py")) is None


def test_non_utf8_path_does_not_crash() -> None:
    data = b" M caf\xe9.txt\0"
    status = parse_porcelain(data, ROOT)
    assert status.state_for(ROOT / "caf\udce9.txt") == "modified"


# ---------- line marks ----------


def _marks(base: str, current: str):
    return line_marks(base, current)


def test_identical_text_has_no_marks() -> None:
    m = _marks("a\nb\nc\n", "a\nb\nc\n")
    assert not m.added and not m.modified and not m.deleted
    assert m.is_empty()


def test_inserted_lines_are_added() -> None:
    m = _marks("a\nc\n", "a\nb1\nb2\nc\n")
    assert m.added == frozenset({1, 2})
    assert not m.modified and not m.deleted


def test_changed_line_is_modified() -> None:
    m = _marks("a\nb\nc\n", "a\nB\nc\n")
    assert m.modified == frozenset({1})
    assert not m.added and not m.deleted


def test_removed_lines_mark_the_line_below_the_gap() -> None:
    m = _marks("a\nb\nc\n", "a\nc\n")
    assert m.deleted == frozenset({1})
    assert not m.added and not m.modified


def test_removal_at_end_of_file_marks_past_the_last_line() -> None:
    m = _marks("a\nb\n", "a\n")
    assert m.deleted == frozenset({1})


def test_replacement_growing_the_block_marks_all_new_lines_modified() -> None:
    m = _marks("a\nb\nc\n", "a\nB1\nB2\nc\n")
    assert m.modified == frozenset({1, 2})
    assert not m.added and not m.deleted


def test_replacement_shrinking_the_block_is_modified_not_deleted() -> None:
    m = _marks("a\nb1\nb2\nc\n", "a\nB\nc\n")
    assert m.modified == frozenset({1})
    assert not m.deleted


def test_no_baseline_means_no_marks() -> None:
    m = line_marks(None, "anything\n")
    assert m.is_empty()


def test_oversized_input_is_skipped() -> None:
    big = "x\n" * (gitstate.MAX_DIFF_LINES + 1)
    m = line_marks(big, big + "y\n")
    assert m.is_empty()


# ---------- real git ----------

pytestmark_git = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True,
        env={"HOME": str(cwd), "PATH": "/usr/bin:/bin",
             "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
             "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid",
             "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"},
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    (root / "src").mkdir()
    (root / "src" / "app.py").write_text("print('hi')\n", encoding="utf-8")
    (root / "README.md").write_text("# hi\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "init")
    return root


@pytestmark_git
def test_repo_root_finds_toplevel_from_subdir(repo: Path) -> None:
    assert gitstate.repo_root(repo / "src") == repo.resolve()


@pytestmark_git
def test_repo_root_is_none_outside_a_repo(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    assert gitstate.repo_root(plain) is None


@pytestmark_git
def test_status_reports_modified_and_untracked(repo: Path) -> None:
    (repo / "src" / "app.py").write_text("print('changed')\n", encoding="utf-8")
    (repo / "new.txt").write_text("x\n", encoding="utf-8")
    status = gitstate.status(repo)
    assert status is not None
    assert status.root == repo.resolve()
    assert status.state_for(repo / "src" / "app.py") == "modified"
    assert status.state_for(repo / "src") == "modified"
    assert status.state_for(repo / "new.txt") == "added"
    assert status.state_for(repo / "README.md") is None
    assert status.git_dir == (repo / ".git").resolve()


@pytestmark_git
def test_status_from_a_project_below_the_root_stays_root_relative(repo: Path) -> None:
    (repo / "src" / "app.py").write_text("print('changed')\n", encoding="utf-8")
    status = gitstate.status(repo / "src")
    assert status is not None
    assert status.root == repo.resolve()
    assert status.state_for(repo / "src" / "app.py") == "modified"


@pytestmark_git
def test_status_is_none_outside_a_repo(tmp_path: Path) -> None:
    assert gitstate.status(tmp_path) is None


@pytestmark_git
def test_head_text_returns_committed_content(repo: Path) -> None:
    (repo / "src" / "app.py").write_text("print('changed')\n", encoding="utf-8")
    assert gitstate.head_text(repo, repo / "src" / "app.py", "utf-8") == "print('hi')\n"


@pytestmark_git
def test_head_text_is_none_for_untracked_file(repo: Path) -> None:
    (repo / "new.txt").write_text("x\n", encoding="utf-8")
    assert gitstate.head_text(repo, repo / "new.txt", "utf-8") is None
