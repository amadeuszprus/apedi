"""Tests for the lazy, background-loaded folder model behind the tree."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("gi")

from apedi.sidebar import DirModel, FileNode, _sync_store  # noqa: E402


def _nodes(*names: str) -> list[FileNode]:
    out = []
    for n in names:
        node = FileNode()
        node.name = n
        node.path_str = f"/p/{n}"
        out.append(node)
    return out


class _Recorder:
    def __init__(self, result: list[FileNode]) -> None:
        self.result = result
        self.calls = 0

    def __call__(self) -> list[FileNode]:
        self.calls += 1
        return self.result


def _model(scan: _Recorder) -> DirModel:
    return DirModel(Path("/p"), scan, defer=False)


def test_creation_does_not_scan() -> None:
    scan = _Recorder(_nodes("a"))
    _model(scan)
    assert scan.calls == 0


def test_first_item_request_scans_once() -> None:
    scan = _Recorder(_nodes("a", "b"))
    model = _model(scan)
    assert model.get_n_items() == 2
    assert model.get_n_items() == 2
    assert model.get_item(1).name == "b"
    assert scan.calls == 1


def test_items_changed_announces_the_loaded_rows() -> None:
    scan = _Recorder(_nodes("a", "b"))
    model = _model(scan)
    events: list[tuple[int, int, int]] = []
    model.connect("items-changed", lambda _m, p, r, a: events.append((p, r, a)))
    model.get_n_items()
    assert events == [(0, 0, 2)]


def test_placeholder_row_while_loading() -> None:
    scan = _Recorder(_nodes("a"))
    model = DirModel(Path("/p"), scan, defer=True, start_thread=False)
    assert model.get_n_items() == 1
    assert model.get_item(0).is_loading is True
    assert not model.ready
    events: list[tuple[int, int, int]] = []
    model.connect("items-changed", lambda _m, p, r, a: events.append((p, r, a)))
    model.finish(scan())
    assert events == [(0, 1, 1)]
    assert model.ready
    assert model.get_n_items() == 1
    assert model.get_item(0).name == "a"


def test_loaded_items_is_empty_until_ready() -> None:
    scan = _Recorder(_nodes("a"))
    model = _model(scan)
    assert model.loaded_items() == []
    assert scan.calls == 0
    model.get_n_items()
    assert [n.name for n in model.loaded_items()] == ["a"]


def test_sync_store_works_on_the_model() -> None:
    scan = _Recorder(_nodes("a", "c"))
    model = _model(scan)
    model.get_n_items()
    keep = model.get_item(0)
    _sync_store(model, _nodes("a", "b", "c"))
    assert [model.get_item(i).name for i in range(model.get_n_items())] == ["a", "b", "c"]
    assert model.get_item(0) is keep


def test_sync_on_an_unloaded_model_is_a_no_op() -> None:
    scan = _Recorder(_nodes("a"))
    model = _model(scan)
    model.sync(_nodes("x"))
    assert scan.calls == 0
    assert model.loaded_items() == []
