"""Tests for ``mr.cli`` (the ``process`` subcommand, transcription monkeypatched)."""

from __future__ import annotations

import numpy as np
import pytest
import soundfile as sf
from typer.testing import CliRunner

import mr.cli
from mr.cli import app
from mr.core.schema import Segment, TranscriptionResult
from mr.core.transcribe import ModelNotCachedError

runner = CliRunner()


def _result(track: str, speaker: str) -> TranscriptionResult:
    text = "hello there" if speaker == "You" else "hey, hi!"
    return TranscriptionResult(
        track=track,
        speaker=speaker,
        model="m",
        audio_seconds=1.2,
        wall_seconds=0.1,
        settings={},
        segments=(Segment(speaker=speaker, text=text, start=0.0, end=1.2),),
    )


def _fake_transcribe(path: str, *, speaker: str, **kwargs: object) -> TranscriptionResult:
    track = "mic" if speaker == "You" else "system"
    return _result(track, speaker)


@pytest.fixture()
def wav_pair(tmp_path):
    """Tiny 16 kHz mono WAVs; content is irrelevant (transcribe is monkeypatched)."""
    mic = tmp_path / "mic.wav"
    system = tmp_path / "system.wav"
    for p in (mic, system):
        sf.write(p, np.zeros(1600, dtype=np.float32), 16000)
    return mic, system


def test_process_happy_path(wav_pair, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(mr.cli, "transcribe_audio", _fake_transcribe)
    mic, system = wav_pair
    out = tmp_path / "out"
    args = ["process", "--mic", str(mic), "--system", str(system), "--out-dir", str(out)]
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    md = out / "system.md"
    assert md.is_file()
    text = md.read_text(encoding="utf-8")
    assert "# Meeting — system" in text
    assert "**You (" in text
    assert "**Them (" in text
    assert not (out / "system.json").exists()


def test_process_json_sidecar(wav_pair, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(mr.cli, "transcribe_audio", _fake_transcribe)
    mic, system = wav_pair
    out = tmp_path / "out"
    args = ["process", "--mic", str(mic), "--system", str(system), "--out-dir", str(out), "--json"]
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    json_path = out / "system.json"
    assert json_path.is_file()
    import json

    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["stamp"] == "system"
    assert len(data["segments"]) == 2


def test_process_model_not_cached(wav_pair, tmp_path, monkeypatch) -> None:
    def _boom(*args: object, **kwargs: object) -> TranscriptionResult:
        raise ModelNotCachedError(
            "model mlx-community/whisper-large-v3-turbo is not cached (offline mode). "
            "Run `mr doctor --fetch-model` to download it first."
        )

    monkeypatch.setattr(mr.cli, "transcribe_audio", _boom)
    mic, system = wav_pair
    args = [
        "process",
        "--mic", str(mic),
        "--system", str(system),
        "--out-dir", str(tmp_path / "out"),
    ]
    result = runner.invoke(app, args)
    assert result.exit_code == 3
    assert "fetch-model" in (result.output + result.stderr)


def test_process_missing_file(tmp_path, wav_pair, monkeypatch) -> None:
    monkeypatch.setattr(mr.cli, "transcribe_audio", _fake_transcribe)
    mic, system = wav_pair
    result = runner.invoke(
        app, ["process", "--mic", str(tmp_path / "nope.wav"), "--system", str(system)]
    )
    assert result.exit_code == 2
    assert "not found" in result.output


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences so assertions are robust to rich's terminal
    rendering (newer rich versions colour the --help output, breaking substring
    checks on the raw output)."""
    import re

    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def test_help_lists_process_and_options(wav_pair) -> None:
    result = runner.invoke(app, ["process", "--help"])
    assert result.exit_code == 0
    assert "--mic" in _strip_ansi(result.output)
    assert "--system" in _strip_ansi(result.output)
    top = runner.invoke(app, ["--help"])
    assert top.exit_code == 0
    assert "process" in _strip_ansi(top.output)
