"""Offline tests for ``mr config set`` (v1.1: ``out_root`` only).

``mr.cli.set_out_root`` is monkeypatched so no real ``~/.config/mr/config.toml``
is ever touched.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

import mr.cli
from mr.cli import app

runner = CliRunner()


@pytest.fixture()
def fake_set_out_root(tmp_path, monkeypatch) -> list[str]:
    """Record values passed to ``mr.cli.set_out_root``; return a resolved root."""
    calls: list[str] = []
    resolved = str(tmp_path / "root")

    def fake(value: str, *, config_path: str | Path | None = None) -> str:
        calls.append(value)
        return resolved

    monkeypatch.setattr(mr.cli, "set_out_root", fake)
    return calls


def test_config_set_out_root_happy(tmp_path, fake_set_out_root) -> None:
    resolved = str(tmp_path / "root")
    result = runner.invoke(app, ["config", "set", "out_root", "/tmp/root"])
    assert result.exit_code == 0, result.output
    assert "out_root:" in result.output
    assert resolved in result.output
    assert fake_set_out_root == ["/tmp/root"]


def test_config_set_unsupported_key(fake_set_out_root) -> None:
    result = runner.invoke(app, ["config", "set", "model", "x"])
    assert result.exit_code == 2
    assert "model" in result.output
    assert "unsupported config key" in result.output
    assert fake_set_out_root == []  # set_out_root must NOT be called


def test_config_set_bad_value_is_usage_error(tmp_path, monkeypatch) -> None:
    def fake(value: str, *, config_path: str | Path | None = None) -> str:
        raise ValueError(f"out_root: empty or not a string: {value!r}")

    monkeypatch.setattr(mr.cli, "set_out_root", fake)
    result = runner.invoke(app, ["config", "set", "out_root", ""])
    assert result.exit_code == 2
    assert "empty" in result.output
    assert "Traceback" not in result.output


def test_config_help_mentions_set_out_root() -> None:
    result = runner.invoke(app, ["config", "--help"])
    assert result.exit_code == 0
    assert "set out_root" in result.output
