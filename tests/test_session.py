"""Tests for session ordering used by incremental startup restore."""

from apedi import session


def test_ordered_tabs_puts_active_tab_first_and_preserves_rest() -> None:
    left_a = {"path": "/tmp/a.md", "group": 0}
    left_b = {"path": "/tmp/b.md", "group": 0}
    right_a = {"path": "/tmp/c.md", "group": 1}
    right_b = {"path": "/tmp/d.md", "group": 1}
    state = {
        "tabs": [left_a, left_b, right_a, right_b],
        "group_pages": [0, 1],
        "active_group": 1,
    }

    assert session.ordered_tabs(state) == [right_b, left_a, left_b, right_a]


def test_ordered_tabs_falls_back_when_saved_page_is_invalid() -> None:
    left = {"path": "/tmp/a.md", "group": 0}
    right = {"path": "/tmp/b.md", "group": 1}

    assert session.ordered_tabs({
        "tabs": [left, right],
        "group_pages": [9, -1],
        "active_group": 1,
    }) == [right, left]


def test_ordered_tabs_tolerates_malformed_session() -> None:
    assert session.ordered_tabs({}) == []
    assert session.ordered_tabs({"tabs": "not-a-list"}) == []
    assert session.ordered_tabs({"tabs": [None, "bad"]}) == []
