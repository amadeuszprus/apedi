"""Which files open in a browser, and when the default handler is Apedi itself."""

from __future__ import annotations

from pathlib import Path

import pytest

from apedi.browser import handler_is_self, is_html_path


@pytest.mark.parametrize("name", ["page.html", "index.htm", "doc.XHTML", "a/b/c.Html"])
def test_html_paths(name: str) -> None:
    assert is_html_path(Path(name)) is True


@pytest.mark.parametrize("name", ["notes.md", "main.py", "index.html.twig", "Makefile"])
def test_other_paths(name: str) -> None:
    assert is_html_path(Path(name)) is False


def test_no_path() -> None:
    assert is_html_path(None) is False


@pytest.mark.parametrize(
    "handler",
    ["pl.aprus.apedi.desktop", "apedi_apedi.desktop", "apedi.desktop", "PL.APRUS.APEDI.desktop"],
)
def test_handler_is_apedi(handler: str) -> None:
    assert handler_is_self(handler, "pl.aprus.apedi") is True


@pytest.mark.parametrize("handler", ["firefox_firefox.desktop", "brave-browser.desktop", "", None])
def test_handler_is_a_browser(handler: str | None) -> None:
    assert handler_is_self(handler, "pl.aprus.apedi") is False
