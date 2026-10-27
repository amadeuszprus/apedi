from pathlib import Path

import pytest

gi = pytest.importorskip("gi")
try:
    gi.require_version("GtkSource", "5")
except ValueError:
    pytest.skip("GtkSource 5 not available", allow_module_level=True)

from apedi import languages  # noqa: E402
from gi.repository import GtkSource  # noqa: E402


def test_python_by_extension() -> None:
    assert languages.language_id_for_path(Path("foo.py")) == "python3"


def test_javascript_by_extension() -> None:
    assert languages.language_id_for_path(Path("foo.js")) in {"js", "javascript"}


def test_markdown_uses_apedi_grammar() -> None:
    assert languages.language_id_for_path(Path("notes.md")) == "apedi-markdown"


def test_indented_fence_does_not_leak_highlighting() -> None:
    text = "1. item\n\n    ```bash\n    echo '$HOME'\n    ```\n\n    prose after\n"
    buffer = GtkSource.Buffer()
    buffer.set_language(languages.language_for_path(Path("notes.md"), text))
    buffer.set_highlight_syntax(True)
    buffer.set_text(text)
    buffer.ensure_highlight(buffer.get_start_iter(), buffer.get_end_iter())

    inside = buffer.get_iter_at_line(3)[1]
    after = buffer.get_iter_at_line(6)[1]
    assert "no-spell-check" in buffer.get_context_classes_at_iter(inside)
    assert "no-spell-check" not in buffer.get_context_classes_at_iter(after)


def test_unknown_extension_returns_none_or_text() -> None:
    result = languages.language_id_for_path(Path("foo.unknownext"))
    assert result in (None, "txt2tags") or isinstance(result, str)


def test_none_path_returns_none() -> None:
    assert languages.language_id_for_path(None) is None


def test_shebang_detection() -> None:
    lid = languages.language_id_for_path(Path("script"), content="#!/usr/bin/env python3\nprint(1)\n")
    assert lid in {"python3", "python"}
