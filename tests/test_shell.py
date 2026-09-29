"""The integrated terminal must open the user's login shell."""

from __future__ import annotations

from pathlib import Path

import pytest

from apedi import shell


class _Pw:
    def __init__(self, shell: str) -> None:
        self.pw_shell = shell


def test_passwd_shell_beats_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHELL", "/bin/bash")
    monkeypatch.setattr(shell.pwd, "getpwuid", lambda _uid: _Pw("/usr/bin/zsh"))
    assert shell.user_shell_name() == "zsh"


def test_environment_is_the_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHELL", "/usr/bin/fish")

    def boom(_uid: int) -> _Pw:
        raise KeyError("no such user")

    monkeypatch.setattr(shell.pwd, "getpwuid", boom)
    assert shell.user_shell_name() == "fish"


def test_empty_passwd_shell_falls_back_to_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHELL", "/usr/bin/fish")
    monkeypatch.setattr(shell.pwd, "getpwuid", lambda _uid: _Pw(""))
    assert shell.user_shell_name() == "fish"


def test_spawn_env_advertises_the_resolved_shell(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHELL", "/bin/bash")
    env = shell.spawn_env("/snap/apedi/x4/bin/zsh")
    assert "SHELL=/snap/apedi/x4/bin/zsh" in env
    assert not any(e == "SHELL=/bin/bash" for e in env)


def test_no_zdotdir_outside_the_snap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SNAP", raising=False)
    assert shell.zsh_zdotdir("/usr/bin/zsh") is None


def test_zdotdir_only_for_zsh(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("SNAP", str(tmp_path))
    (tmp_path / "usr/share/apedi/zdotdir").mkdir(parents=True)
    monkeypatch.setattr(shell, "real_home", lambda: tmp_path / "home")
    assert shell.zsh_zdotdir("/bin/bash") is None
    assert shell.zsh_zdotdir(f"{tmp_path}/bin/zsh") == str(tmp_path / "usr/share/apedi/zdotdir")


def test_readable_user_config_wins(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("SNAP", str(tmp_path))
    (tmp_path / "usr/share/apedi/zdotdir").mkdir(parents=True)
    home = tmp_path / "home"
    home.mkdir()
    (home / ".zshrc").write_text("# mine\n")
    monkeypatch.setattr(shell, "real_home", lambda: home)
    assert shell.zsh_zdotdir("/bin/zsh") is None


def test_spawn_env_carries_zdotdir(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("SNAP", str(tmp_path))
    (tmp_path / "usr/share/apedi/zdotdir").mkdir(parents=True)
    monkeypatch.setattr(shell, "real_home", lambda: tmp_path / "home")
    env = shell.spawn_env("/snap/apedi/x6/bin/zsh")
    assert f"ZDOTDIR={tmp_path}/usr/share/apedi/zdotdir" in env


def test_real_home_comes_from_passwd(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Pw:
        pw_dir = "/home/someone"

    monkeypatch.setattr(shell.pwd, "getpwuid", lambda _uid: _Pw())
    assert shell.real_home() == Path("/home/someone")
