"""Tests for mr.config: Config dataclass, defaults, TOML parsing, validation."""

import os
import tomllib
from pathlib import Path

import pytest

from mr.config import Config, default_config, load_config
from mr.core.transcribe import DEFAULT_MODEL


def test_missing_file_returns_defaults(tmp_path) -> None:
    cfg = load_config(tmp_path / "does-not-exist.toml")
    assert cfg == default_config()
    expected_root = str(Path(os.path.expanduser("~/Meetings")).resolve())
    assert cfg.out_root == expected_root
    assert os.path.isabs(cfg.out_root)
    assert cfg.model == DEFAULT_MODEL
    assert cfg.language == "en"
    assert cfg.dedup_threshold == 0.6
    assert cfg.keep_audio is True


def test_empty_file_returns_defaults(tmp_path) -> None:
    p = tmp_path / "config.toml"
    p.write_text("# just a comment\n# nothing else\n")
    assert load_config(p) == default_config()


def test_parses_all_keys(tmp_path) -> None:
    p = tmp_path / "config.toml"
    p.write_text(
        'out_root = "~/MyMeetings"\n'
        'model = "local/model"\n'
        'language = "de"\n'
        "dedup_threshold = 0.75\n"
        "keep_audio = false\n"
    )
    cfg = load_config(p)
    expected = str(Path(os.path.expanduser("~/MyMeetings")).resolve())
    assert cfg.out_root == expected
    assert os.path.isabs(cfg.out_root)
    assert cfg.model == "local/model"
    assert cfg.language == "de"
    assert cfg.dedup_threshold == 0.75
    assert cfg.keep_audio is False


def test_out_root_expansion(tmp_path) -> None:
    p = tmp_path / "config.toml"
    p.write_text('out_root = "~/Meetings"\n')
    cfg = load_config(p)
    home = os.path.expanduser("~")
    assert cfg.out_root == str(Path(home + "/Meetings").resolve())
    assert os.path.isabs(cfg.out_root)
    assert cfg.out_root.startswith(home)


def test_unknown_keys_ignored(tmp_path) -> None:
    p = tmp_path / "config.toml"
    p.write_text("totally_unknown = 42\nother = 'x'\n")
    assert load_config(p) == default_config()


def test_partial_override(tmp_path) -> None:
    p = tmp_path / "config.toml"
    p.write_text('language = "fr"\n')
    cfg = load_config(p)
    assert cfg.language == "fr"
    assert cfg.model == DEFAULT_MODEL
    assert cfg.keep_audio is True


def test_invalid_dedup_raises(tmp_path) -> None:
    for bad in ("1.5", "-0.1", '"high"', "true"):
        p = tmp_path / "config.toml"
        p.write_text(f"dedup_threshold = {bad}\n")
        with pytest.raises(ValueError, match="dedup_threshold"):
            load_config(p)


def test_invalid_model_raises(tmp_path) -> None:
    for bad in ('""', "123", "[1, 2]"):
        p = tmp_path / "config.toml"
        p.write_text(f"model = {bad}\n")
        with pytest.raises(ValueError, match="model"):
            load_config(p)


def test_invalid_keep_audio_raises(tmp_path) -> None:
    p = tmp_path / "config.toml"
    p.write_text('keep_audio = "yes"\n')
    with pytest.raises(ValueError, match="keep_audio"):
        load_config(p)


def test_invalid_out_root_raises(tmp_path) -> None:
    p = tmp_path / "config.toml"
    p.write_text("out_root = 42\n")
    with pytest.raises(ValueError, match="out_root"):
        load_config(p)


def test_malformed_toml_raises(tmp_path) -> None:
    p = tmp_path / "config.toml"
    p.write_text("out_root = \n")
    with pytest.raises(tomllib.TOMLDecodeError):
        load_config(p)


def test_config_is_frozen() -> None:
    cfg = default_config()
    with pytest.raises(Exception):
        cfg.model = "x"  # type: ignore[misc]


def test_load_config_accepts_posix_path(tmp_path) -> None:
    p = tmp_path / "config.toml"
    p.write_text('model = "m"\n')
    assert load_config(str(p)).model == "m"
    assert load_config(p).model == "m"
    assert isinstance(load_config(p), Config)
