"""The 'Open with' override must land in the real home, and say so when it cannot."""

from __future__ import annotations

from pathlib import Path

import pytest

from apedi import desktop_integration as di


@pytest.fixture(autouse=True)
def _fresh_cache() -> None:
    di._writable = None


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(di, "real_home", lambda: tmp_path)
    monkeypatch.delenv("SNAP_INSTANCE_NAME", raising=False)
    return tmp_path


def test_override_uses_the_real_home_not_snap_home(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", "/home/someone/snap/apedi/11")
    assert di._override_path() == home / ".local/share/applications/apedi_apedi.desktop"


def test_instance_name_is_honoured(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SNAP_INSTANCE_NAME", "apedi_dev")
    assert di._override_path().name == "apedi_dev_apedi.desktop"


def test_hiding_and_restoring(home: Path) -> None:
    assert di.is_hidden() is False
    assert di.apply(False) is True
    assert di.is_hidden() is True
    assert "Hidden=true" in di._override_path().read_text()
    assert di.apply(True) is True
    assert di.is_hidden() is False
    assert di._override_path().exists() is False


def test_restoring_is_fine_without_an_override(home: Path) -> None:
    assert di.apply(True) is True


def test_unwritable_home_reports_failure(home: Path) -> None:
    apps = home / ".local/share/applications"
    apps.mkdir(parents=True)
    (apps / "apedi_apedi.desktop").write_text(di._OVERRIDE_BODY)
    apps.chmod(0o500)
    try:
        assert di.available() is False
        assert di.apply(True) is False
        assert di.stranded_override() == apps / "apedi_apedi.desktop"
    finally:
        apps.chmod(0o700)


def test_no_stranded_override_when_writable(home: Path) -> None:
    di.apply(False)
    assert di.available() is True
    assert di.stranded_override() is None
