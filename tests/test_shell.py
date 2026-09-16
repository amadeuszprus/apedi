"""The integrated terminal must open the user's login shell."""

from __future__ import annotations

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
