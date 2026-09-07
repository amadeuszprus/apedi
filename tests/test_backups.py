import time
from pathlib import Path

import pytest

from apedi import backups


@pytest.fixture(autouse=True)
def _isolated_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    target = tmp_path / "backups"
    monkeypatch.setattr(backups, "_backups_dir", lambda: target)
    return target


def test_save_copy_writes_body(tmp_path: Path) -> None:
    original = tmp_path / "notes.md"
    copy = backups.save_copy(original, "unsaved work\n", "utf-8")
    assert copy is not None
    assert copy.read_text(encoding="utf-8") == "unsaved work\n"


def test_save_copy_keeps_stem_and_suffix(tmp_path: Path) -> None:
    copy = backups.save_copy(tmp_path / "notes.md", "x", "utf-8")
    assert copy is not None
    assert copy.name.startswith("notes-")
    assert copy.suffix == ".md"


def test_save_copy_handles_suffixless_name(tmp_path: Path) -> None:
    copy = backups.save_copy(tmp_path / "Makefile", "x", "utf-8")
    assert copy is not None
    assert copy.name.startswith("Makefile-")


def test_two_copies_in_the_same_second_do_not_collide(tmp_path: Path) -> None:
    original = tmp_path / "notes.md"
    first = backups.save_copy(original, "one", "utf-8")
    second = backups.save_copy(original, "two", "utf-8")
    assert first is not None and second is not None
    assert first != second
    assert first.read_text(encoding="utf-8") == "one"
    assert second.read_text(encoding="utf-8") == "two"


def test_save_copy_survives_unwritable_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    blocked = tmp_path / "nope"
    blocked.write_text("i am a file, not a directory")
    monkeypatch.setattr(backups, "_backups_dir", lambda: blocked)
    assert backups.save_copy(tmp_path / "notes.md", "x", "utf-8") is None


def test_prune_removes_old_copies_only(tmp_path: Path, _isolated_dir: Path) -> None:
    fresh = backups.save_copy(tmp_path / "fresh.md", "new", "utf-8")
    stale = backups.save_copy(tmp_path / "stale.md", "old", "utf-8")
    assert fresh is not None and stale is not None
    ancient = time.time() - 60 * 60 * 24 * 40
    import os

    os.utime(stale, (ancient, ancient))
    backups.prune(max_age_days=30)
    assert fresh.exists()
    assert not stale.exists()


def test_prune_on_missing_dir_is_silent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(backups, "_backups_dir", lambda: tmp_path / "absent")
    backups.prune()  # must not raise
