"""Startup regressions that do not require constructing a GTK window."""

from pathlib import Path
from types import SimpleNamespace

from apedi import app, backups, recovery


def test_draft_for_session_file_is_not_opened_as_modified_duplicate(
    tmp_path: Path, monkeypatch,
) -> None:
    path = tmp_path / "note.md"
    path.write_text("saved", encoding="utf-8")
    draft = recovery.Draft(
        original_path=path,
        body="older unsaved text",
        encoding="utf-8",
        saved_at=1.0,
        base_mtime=None,
        draft_path=tmp_path / "draft.json",
    )
    monkeypatch.setattr(backups, "prune", lambda: None)
    monkeypatch.setattr(recovery, "list_pending", lambda: [draft])

    class Window:
        def __init__(self) -> None:
            self.added = []

        def all_tabs(self):
            return [SimpleNamespace(buffer=SimpleNamespace(path=path))]

        def add_tab(self, buffer) -> None:
            self.added.append(buffer)

        def _set_status(self, _message: str) -> None:
            pass

    window = Window()

    assert app.EditorApp._maybe_restore_drafts(object(), window) is False
    assert window.added == []
