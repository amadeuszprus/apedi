from pathlib import Path

import pytest

from apedi import file_io


def test_load_utf8(tmp_path: Path) -> None:
    p = tmp_path / "a.txt"
    p.write_text("zażółć gęślą jaźń\n", encoding="utf-8")
    loaded = file_io.load_file(p)
    assert loaded.text == "zażółć gęślą jaźń\n"
    assert loaded.encoding == "utf-8"
    assert loaded.mtime > 0


def test_load_latin1_fallback(tmp_path: Path) -> None:
    p = tmp_path / "a.txt"
    p.write_bytes("café".encode("latin-1"))
    loaded = file_io.load_file(p)
    assert "caf" in loaded.text
    assert loaded.encoding != "utf-8"


def test_load_binary_raises(tmp_path: Path) -> None:
    p = tmp_path / "binary"
    p.write_bytes(b"\x00\x01\x02 hello \x00")
    with pytest.raises(file_io.BinaryFileError):
        file_io.load_file(p)


def test_load_binary_allow(tmp_path: Path) -> None:
    p = tmp_path / "binary"
    p.write_bytes(b"\x00 hi")
    loaded = file_io.load_file(p, allow_binary=True)
    assert "hi" in loaded.text


def test_load_too_large_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(file_io, "LARGE_FILE_THRESHOLD", 100)
    p = tmp_path / "big.txt"
    p.write_text("x" * 200, encoding="utf-8")
    with pytest.raises(file_io.FileTooLargeError):
        file_io.load_file(p)
    loaded = file_io.load_file(p, allow_large=True)
    assert len(loaded.text) == 200


def test_save_roundtrip(tmp_path: Path) -> None:
    p = tmp_path / "out.txt"
    text = "line1\nline2\nzażółć\n"
    mtime = file_io.save_file(p, text, encoding="utf-8")
    assert mtime > 0
    assert p.read_text(encoding="utf-8") == text


def test_save_creates_parent_dirs(tmp_path: Path) -> None:
    p = tmp_path / "deep" / "nested" / "out.txt"
    file_io.save_file(p, "hi")
    assert p.read_text() == "hi"


def test_is_binary() -> None:
    assert file_io.is_binary(b"hello\x00world") is True
    assert file_io.is_binary(b"hello world") is False


def test_detect_encoding_utf8() -> None:
    assert file_io.detect_encoding("hello".encode("utf-8")) == "utf-8"
