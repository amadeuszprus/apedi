"""User settings — TOML at ~/.config/apedi/config.toml."""

from __future__ import annotations

import logging
import tomllib
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


def _toml_value(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return repr(v)
    if isinstance(v, str):
        return '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'
    if isinstance(v, list):
        return "[" + ", ".join(_toml_value(x) for x in v) + "]"
    raise TypeError(f"Cannot serialize {type(v).__name__} to TOML")


def _dumps(data: dict[str, Any]) -> str:
    return "".join(f"{k} = {_toml_value(v)}\n" for k, v in data.items())

CONFIG_DIR = Path.home() / ".config" / "apedi"
CONFIG_PATH = CONFIG_DIR / "config.toml"


@dataclass
class Settings:
    font: str = "Monospace"
    font_size: int = 11
    tab_width: int = 4
    use_spaces: bool = True
    wrap_lines: bool = False
    show_line_numbers: bool = True
    color_scheme: str = "Adwaita"
    auto_indent: bool = True
    trim_trailing_whitespace: bool = True
    default_encoding: str = "utf-8"
    dark_ui: str = "auto"  # "auto" | "light" | "dark"
    last_seen_version: str = ""
    show_sidebar: bool = False
    last_project: str = ""  # legacy; migrated to projects on first load
    projects: list[str] = field(default_factory=list)
    show_terminal: bool = False
    sidebar_compact: bool = True
    ignore_patterns: list[str] = field(default_factory=list)
    register_in_file_manager: bool = True
    autosave: str = "off"  # "off" | "delay" | "focus"
    autosave_delay_ms: int = 2000
    language: str = "auto"  # "auto" | "en" | "pl"

    @classmethod
    def load(cls, path: Path = CONFIG_PATH) -> "Settings":
        if not path.exists():
            return cls()
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as e:
            log.warning("Failed to read settings %s: %s — using defaults", path, e)
            return cls()
        if isinstance(data.get("dark_ui"), bool):
            data["dark_ui"] = "dark" if data["dark_ui"] else "auto"
        if data.get("last_project") and not data.get("projects"):
            data["projects"] = [data["last_project"]]
        valid = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in valid})

    def save(self, path: Path = CONFIG_PATH) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_dumps(asdict(self)), encoding="utf-8")

    def font_description(self) -> str:
        return f"{self.font} {self.font_size}"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)
