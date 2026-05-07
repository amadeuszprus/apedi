from pathlib import Path

from apedi.settings import Settings


def test_load_defaults_when_missing(tmp_path: Path) -> None:
    s = Settings.load(tmp_path / "missing.toml")
    assert s.font == "Monospace"
    assert s.tab_width == 4
    assert s.use_spaces is True


def test_save_and_load_roundtrip(tmp_path: Path) -> None:
    cfg = tmp_path / "config.toml"
    s1 = Settings(font="Fira Code", font_size=13, tab_width=2, use_spaces=False)
    s1.save(cfg)
    s2 = Settings.load(cfg)
    assert s2.font == "Fira Code"
    assert s2.font_size == 13
    assert s2.tab_width == 2
    assert s2.use_spaces is False


def test_load_ignores_unknown_keys(tmp_path: Path) -> None:
    cfg = tmp_path / "config.toml"
    cfg.write_text('font = "Hack"\nbogus_key = 42\n', encoding="utf-8")
    s = Settings.load(cfg)
    assert s.font == "Hack"


def test_load_handles_corrupt_file(tmp_path: Path) -> None:
    cfg = tmp_path / "config.toml"
    cfg.write_text("this is not toml [[[", encoding="utf-8")
    s = Settings.load(cfg)
    assert s.font == "Monospace"


def test_font_description() -> None:
    assert Settings(font="Hack", font_size=12).font_description() == "Hack 12"
