"""File I/O — load/save with encoding fallback and binary detection."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

BINARY_SAMPLE_SIZE = 8192
LARGE_FILE_THRESHOLD = 50 * 1024 * 1024  # 50 MB
CHARDET_CONFIDENCE = 0.7


class FileTooLargeError(Exception):
    def __init__(self, path: Path, size: int) -> None:
        super().__init__(f"{path}: {size} bytes")
        self.path = path
        self.size = size


class BinaryFileError(Exception):
    def __init__(self, path: Path) -> None:
        super().__init__(str(path))
        self.path = path


@dataclass
class LoadedFile:
    text: str
    encoding: str
    mtime: float


def is_binary(sample: bytes) -> bool:
    return b"\x00" in sample


def detect_encoding(data: bytes, default: str = "utf-8") -> str:
    """Return encoding for raw bytes. Strategy: UTF-8 → chardet → latin-1."""
    try:
        data.decode(default)
        return default
    except UnicodeDecodeError:
        pass
    try:
        import chardet  # noqa: PLC0415
        guess = chardet.detect(data)
        encoding = guess.get("encoding")
        confidence = guess.get("confidence") or 0.0
        if encoding and confidence >= CHARDET_CONFIDENCE:
            try:
                data.decode(encoding)
                return encoding
            except UnicodeDecodeError:
                pass
    except ImportError:
        log.warning("chardet not available — falling back to latin-1")
    return "latin-1"


def load_file(path: Path, *, allow_binary: bool = False, allow_large: bool = False) -> LoadedFile:
    """Load file from disk. Raises FileTooLargeError, BinaryFileError, OSError."""
    stat = path.stat()
    if stat.st_size > LARGE_FILE_THRESHOLD and not allow_large:
        raise FileTooLargeError(path, stat.st_size)
    data = path.read_bytes()
    if not allow_binary and is_binary(data[:BINARY_SAMPLE_SIZE]):
        raise BinaryFileError(path)
    encoding = detect_encoding(data)
    text = data.decode(encoding, errors="replace")
    return LoadedFile(text=text, encoding=encoding, mtime=stat.st_mtime)


def save_file(path: Path, text: str, encoding: str = "utf-8") -> float:
    """Write text to disk, return new mtime."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode(encoding, errors="replace"))
    return path.stat().st_mtime
