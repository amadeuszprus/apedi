import subprocess
from unittest.mock import MagicMock, patch

import pytest

from apedi import formatters


def test_supports_known_language() -> None:
    assert formatters.supports("python3") is True
    assert formatters.supports("rust") is True
    assert formatters.supports(None) is False
    assert formatters.supports("brainfuck") is False


def test_resolve_binary_uses_snap_when_set(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    snap_root = tmp_path / "snap"
    bin_dir = snap_root / "bin"
    bin_dir.mkdir(parents=True)
    fake = bin_dir / "black"
    fake.write_text("#!/bin/sh\n")
    fake.chmod(0o755)
    monkeypatch.setenv("SNAP", str(snap_root))
    spec = formatters.FORMATTERS["python3"]
    assert formatters.resolve_binary(spec) == str(fake)


def test_resolve_binary_falls_back_to_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SNAP", raising=False)
    monkeypatch.setattr(formatters.shutil, "which", lambda name: f"/usr/bin/{name}")
    spec = formatters.FORMATTERS["python3"]
    assert formatters.resolve_binary(spec) == "/usr/bin/black"


def test_format_text_unsupported_language_raises() -> None:
    with pytest.raises(formatters.FormatError, match="No formatter"):
        formatters.format_text("brainfuck", "+++.")


def test_format_text_missing_binary_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SNAP", raising=False)
    monkeypatch.setattr(formatters.shutil, "which", lambda name: None)
    with pytest.raises(formatters.FormatError, match="not found"):
        formatters.format_text("python3", "x = 1")


def test_format_text_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SNAP", raising=False)
    monkeypatch.setattr(formatters.shutil, "which", lambda name: "/fake/" + name)
    result = MagicMock(returncode=0, stdout="x = 1\n", stderr="")
    with patch.object(formatters.subprocess, "run", return_value=result) as run:
        out = formatters.format_text("python3", "x=1")
    assert out == "x = 1\n"
    assert run.call_args.args[0] == ["/fake/black", "-q", "-"]


def test_format_text_nonzero_exit_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SNAP", raising=False)
    monkeypatch.setattr(formatters.shutil, "which", lambda name: "/fake/black")
    result = MagicMock(returncode=1, stdout="", stderr="syntax error: foo\nmore\n")
    with patch.object(formatters.subprocess, "run", return_value=result):
        with pytest.raises(formatters.FormatError, match="syntax error"):
            formatters.format_text("python3", "x =")


def test_format_text_timeout_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SNAP", raising=False)
    monkeypatch.setattr(formatters.shutil, "which", lambda name: "/fake/black")
    def boom(*a, **kw):
        raise subprocess.TimeoutExpired(cmd="black", timeout=5)
    with patch.object(formatters.subprocess, "run", side_effect=boom):
        with pytest.raises(formatters.FormatError, match="timed out"):
            formatters.format_text("python3", "x")


def test_filename_substitution(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SNAP", raising=False)
    monkeypatch.setattr(formatters.shutil, "which", lambda name: "/fake/" + name)
    result = MagicMock(returncode=0, stdout="ok", stderr="")
    with patch.object(formatters.subprocess, "run", return_value=result) as run:
        formatters.format_text("javascript", "let x=1", filename="/path/foo.js")
    assert "/path/foo.js" in run.call_args.args[0]
