from pathlib import Path

import pytest

gi = pytest.importorskip("gi")
try:
    gi.require_version("GtkSource", "5")
except ValueError:
    pytest.skip("GtkSource 5 not available", allow_module_level=True)

from apedi import languages  # noqa: E402


def test_python_by_extension() -> None:
    assert languages.language_id_for_path(Path("foo.py")) == "python3"


def test_javascript_by_extension() -> None:
    assert languages.language_id_for_path(Path("foo.js")) in {"js", "javascript"}


def test_unknown_extension_returns_none_or_text() -> None:
    result = languages.language_id_for_path(Path("foo.unknownext"))
    assert result in (None, "txt2tags") or isinstance(result, str)


def test_none_path_returns_none() -> None:
    assert languages.language_id_for_path(None) is None


def test_shebang_detection() -> None:
    lid = languages.language_id_for_path(Path("script"), content="#!/usr/bin/env python3\nprint(1)\n")
    assert lid in {"python3", "python"}
