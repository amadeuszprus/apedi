"""Tests for `EditorApp._resolve` — CLI/URI argument → absolute Path."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def resolve():
    # `apedi.app` pulls in `gi`. Skip the module if it's not importable in
    # the test env — these are headless tests of a single helper.
    pytest.importorskip("gi")
    from apedi.app import EditorApp
    return EditorApp._resolve


def test_absolute_path_passes_through(resolve) -> None:
    assert resolve(Path("/tmp"), "/etc/hosts") == Path("/etc/hosts")


def test_relative_path_joined_with_cwd(resolve, tmp_path) -> None:
    f = tmp_path / "x.txt"
    f.write_text("hi")
    assert resolve(tmp_path, "x.txt") == f


def test_file_uri_with_absolute_path(resolve) -> None:
    assert resolve(Path("/anywhere"), "file:///etc/hosts") == Path("/etc/hosts")


def test_file_uri_percent_decoded(resolve) -> None:
    out = resolve(Path("/anywhere"), "file:///home/aprus/My%20Notes/foo.md")
    assert out == Path("/home/aprus/My Notes/foo.md")


def test_file_uri_with_query_or_fragment_ignored(resolve) -> None:
    # Browsers sometimes add `#fragment` (anchors); urlparse drops it from path.
    out = resolve(Path("/anywhere"), "file:///etc/hosts#top")
    assert out == Path("/etc/hosts")
