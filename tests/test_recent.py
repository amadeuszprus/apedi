from pathlib import Path

from apedi import recent


def test_load_returns_empty_when_missing(tmp_path: Path) -> None:
    assert recent.load(tmp_path / "missing.json") == []


def test_save_and_load_roundtrip(tmp_path: Path) -> None:
    f = tmp_path / "recent.json"
    paths = [tmp_path / "a.py", tmp_path / "b.py"]
    recent.save(paths, f)
    loaded = recent.load(f)
    assert [str(p) for p in loaded] == [str(p) for p in paths]


def test_add_dedupes_and_promotes(tmp_path: Path) -> None:
    a = tmp_path / "a.py"
    b = tmp_path / "b.py"
    a.touch()
    b.touch()
    result = recent.add(a, [b, a])
    assert [p.name for p in result] == ["a.py", "b.py"]


def test_add_caps_at_max(tmp_path: Path) -> None:
    paths = [tmp_path / f"f{i}.txt" for i in range(25)]
    for p in paths:
        p.touch()
    new = tmp_path / "new.txt"
    new.touch()
    result = recent.add(new, paths)
    assert len(result) == recent.MAX_RECENT
    assert result[0].name == "new.txt"


def test_load_handles_corrupt_file(tmp_path: Path) -> None:
    f = tmp_path / "recent.json"
    f.write_text("not json [[[", encoding="utf-8")
    assert recent.load(f) == []


def test_load_handles_wrong_shape(tmp_path: Path) -> None:
    f = tmp_path / "recent.json"
    f.write_text('{"not": "a list"}', encoding="utf-8")
    assert recent.load(f) == []


def test_filter_existing(tmp_path: Path) -> None:
    real = tmp_path / "real.txt"
    real.touch()
    fake = tmp_path / "fake.txt"
    assert recent.filter_existing([real, fake]) == [real]
