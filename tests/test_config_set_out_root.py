"""Tests for mr.config.set_out_root: validated, atomic config write-back."""

import os
import tomllib
from pathlib import Path

import pytest

from mr.config import default_config, load_config, set_out_root
from mr.core.transcribe import DEFAULT_MODEL


def test_returns_resolved_root_and_load_config_reads_it_back(tmp_path) -> None:
    p = tmp_path / "config.toml"
    new_root = str(tmp_path / "NewRoot")
    returned = set_out_root(new_root, config_path=p)
    assert returned == new_root
    assert os.path.isabs(returned)
    assert load_config(p).out_root == new_root


def test_existing_file_preserves_all_other_keys(tmp_path) -> None:
    p = tmp_path / "config.toml"
    p.write_text(
        'out_root = "~/Old"\n'
        'model = "local/model"\n'
        'language = "de"\n'
        "dedup_threshold = 0.75\n"
        "keep_audio = false\n"
        'future_option = "x"\n'
    )
    new_root = str(tmp_path / "NewRoot")
    assert set_out_root(new_root, config_path=p) == new_root

    # Raw TOML: out_root changed, everything else identical (including unknown key).
    data = tomllib.loads(p.read_text())
    assert data["out_root"] == new_root
    assert data["model"] == "local/model"
    assert data["language"] == "de"
    assert data["dedup_threshold"] == 0.75
    assert data["keep_audio"] is False
    assert data["future_option"] == "x"

    # And load_config agrees.
    cfg = load_config(p)
    assert cfg.out_root == new_root
    assert cfg.model == "local/model"
    assert cfg.language == "de"
    assert cfg.dedup_threshold == 0.75
    assert cfg.keep_audio is False


def test_missing_file_created_with_defaults_plus_new_root(tmp_path) -> None:
    p = tmp_path / "nested" / "config.toml"  # parent dir must be created too
    new_root = str(tmp_path / "NewRoot")
    returned = set_out_root(new_root, config_path=p)

    assert p.is_file()
    assert returned == new_root
    cfg = load_config(p)
    defaults = default_config()
    assert cfg.out_root == new_root
    assert cfg.model == defaults.model == DEFAULT_MODEL
    assert cfg.language == defaults.language
    assert cfg.dedup_threshold == defaults.dedup_threshold
    assert cfg.keep_audio == defaults.keep_audio


def test_tilde_expansion_and_resolution(tmp_path) -> None:
    p = tmp_path / "config.toml"
    returned = set_out_root("~/Sub/Meetings", config_path=p)
    home = os.path.expanduser("~")
    assert returned == str(Path(home + "/Sub/Meetings").resolve())
    assert os.path.isabs(returned)
    assert returned.startswith(home)
    assert load_config(p).out_root == returned
    # The written value is the absolute resolved string.
    assert tomllib.loads(p.read_text())["out_root"] == returned


def test_no_leftover_temp_files(tmp_path) -> None:
    p = tmp_path / "config.toml"
    set_out_root(str(tmp_path / "NewRoot"), config_path=p)
    leftovers = [name for name in os.listdir(tmp_path) if name != "config.toml"]
    assert leftovers == []


def test_empty_string_raises(tmp_path) -> None:
    p = tmp_path / "config.toml"
    with pytest.raises(ValueError, match="out_root"):
        set_out_root("", config_path=p)
    assert not p.exists()


def test_non_string_raises(tmp_path) -> None:
    p = tmp_path / "config.toml"
    with pytest.raises(ValueError, match="out_root"):
        set_out_root(42)  # type: ignore[arg-type]
    assert not p.exists()
