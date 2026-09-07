"""Tests for the in-place store merge behind ProjectSidebar.refresh_dir.

Needs GTK's GObject stack for Gio.ListStore, so it skips where `gi` is
unavailable (the same convention the rest of the suite uses for optional
runtime dependencies).
"""

from __future__ import annotations

import pytest

pytest.importorskip("gi")

from apedi.sidebar import FileNode, _sync_store  # noqa: E402
from gi.repository import Gio  # noqa: E402


def _node(name: str, *, is_dir: bool = False, parent: str = "/p") -> FileNode:
    node = FileNode()
    node.name = name
    node.path_str = f"{parent}/{name}"
    node.is_dir = is_dir
    return node


def _store(*nodes: FileNode) -> Gio.ListStore:
    store = Gio.ListStore.new(FileNode)
    for n in nodes:
        store.append(n)
    return store


def _names(store: Gio.ListStore) -> list[str]:
    return [store.get_item(i).name for i in range(store.get_n_items())]


def test_rename_swaps_only_the_renamed_entry() -> None:
    keep = _node("aaa.txt")
    store = _store(keep, _node("old.txt"), _node("zzz.txt"))
    _sync_store(store, [_node("aaa.txt"), _node("new.txt"), _node("zzz.txt")])
    assert _names(store) == ["aaa.txt", "new.txt", "zzz.txt"]
    # Untouched siblings keep their identity — that is what preserves the
    # expansion state of the rows built from them.
    assert store.get_item(0) is keep


def test_insert_keeps_existing_objects() -> None:
    a, c = _node("a.txt"), _node("c.txt")
    store = _store(a, c)
    _sync_store(store, [_node("a.txt"), _node("b.txt"), _node("c.txt")])
    assert _names(store) == ["a.txt", "b.txt", "c.txt"]
    assert store.get_item(0) is a
    assert store.get_item(2) is c


def test_removal_from_middle() -> None:
    store = _store(_node("a.txt"), _node("b.txt"), _node("c.txt"))
    _sync_store(store, [_node("a.txt"), _node("c.txt")])
    assert _names(store) == ["a.txt", "c.txt"]


def test_removal_from_tail() -> None:
    store = _store(_node("a.txt"), _node("b.txt"))
    _sync_store(store, [_node("a.txt")])
    assert _names(store) == ["a.txt"]


def test_emptying_the_directory() -> None:
    store = _store(_node("a.txt"), _node("b.txt"))
    _sync_store(store, [])
    assert _names(store) == []


def test_filling_an_empty_directory() -> None:
    store = _store()
    _sync_store(store, [_node("a.txt")])
    assert _names(store) == ["a.txt"]


def test_folders_sort_before_files() -> None:
    store = _store(_node("zzz", is_dir=True), _node("aaa.txt"))
    _sync_store(store, [
        _node("zzz", is_dir=True), _node("aaa.txt"), _node("mmm.txt"),
    ])
    assert _names(store) == ["zzz", "aaa.txt", "mmm.txt"]


def test_new_folder_lands_before_files() -> None:
    a = _node("a.txt")
    store = _store(a)
    _sync_store(store, [_node("newdir", is_dir=True), _node("a.txt")])
    assert _names(store) == ["newdir", "a.txt"]
    assert store.get_item(1) is a


def test_flags_refresh_on_surviving_entries() -> None:
    existing = _node("a.txt")
    existing.is_ignored = False
    store = _store(existing)
    fresh = _node("a.txt")
    fresh.is_ignored = True
    _sync_store(store, [fresh])
    assert store.get_item(0) is existing
    assert existing.is_ignored is True


def test_identical_listing_is_a_no_op() -> None:
    a, b = _node("a.txt"), _node("b.txt")
    store = _store(a, b)
    _sync_store(store, [_node("a.txt"), _node("b.txt")])
    assert store.get_item(0) is a
    assert store.get_item(1) is b


def test_wholesale_replacement() -> None:
    store = _store(_node("a.txt"), _node("b.txt"))
    _sync_store(store, [_node("x.txt"), _node("y.txt")])
    assert _names(store) == ["x.txt", "y.txt"]


def test_type_change_replaces_the_node() -> None:
    was_file = _node("thing")
    store = _store(was_file)
    _sync_store(store, [_node("thing", is_dir=True)])
    assert _names(store) == ["thing"]
    assert store.get_item(0) is not was_file
    assert store.get_item(0).is_dir is True
