"""Tests for `mr retranscribe` (mr.cli._do_retranscribe)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import mr.cli as cli
from mr.config import Config
from mr.heartbeat import write_transcribing_heartbeat

STAMP = "2026-10-22_1440"


def _cfg(tmp_path) -> Config:
    return Config(
        out_root=str(tmp_path),
        model="m",
        language="en",
        dedup_threshold=0.6,
        keep_audio=True,
    )


def _recording(tmp_path, stamp: str = STAMP, *, system_wav: bool = True) -> Path:
    rec = tmp_path / "recordings" / stamp
    rec.mkdir(parents=True)
    (rec / "mic.wav").write_bytes(b"RIFF")
    if system_wav:
        (rec / "system.wav").write_bytes(b"RIFF")
    return rec


def _fresh_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class _Spawn:
    """Fake `_spawn_transcription`: records calls, returns a fixed bool."""

    def __init__(self, ok: bool = True) -> None:
        self.ok = ok
        self.calls: list[tuple[object, object, object]] = []

    def __call__(self, stamp: str, out_dir: str, *, json_sidecar: bool = False) -> bool:
        self.calls.append((stamp, out_dir, json_sidecar))
        return self.ok


def test_happy_path(tmp_path, capsys, monkeypatch) -> None:
    spawn = _Spawn(ok=True)
    monkeypatch.setattr(cli, "_spawn_transcription", spawn)
    rec = _recording(tmp_path)
    code = cli._do_retranscribe(_cfg(tmp_path), STAMP)
    out = capsys.readouterr().out
    assert code == 0
    assert f"retranscribing {STAMP}" in out
    assert spawn.calls == [(STAMP, str(rec), False)]


def test_json_sidecar_forwarded(tmp_path, capsys, monkeypatch) -> None:
    spawn = _Spawn(ok=True)
    monkeypatch.setattr(cli, "_spawn_transcription", spawn)
    rec = _recording(tmp_path)
    code = cli._do_retranscribe(_cfg(tmp_path), STAMP, json_sidecar=True)
    assert code == 0
    assert spawn.calls == [(STAMP, str(rec), True)]


def test_unknown_stamp(tmp_path, capsys, monkeypatch) -> None:
    spawn = _Spawn(ok=True)
    monkeypatch.setattr(cli, "_spawn_transcription", spawn)
    code = cli._do_retranscribe(_cfg(tmp_path), "1999-01-01_0000")
    captured = capsys.readouterr()
    assert code == 1
    assert str(tmp_path / "recordings" / "1999-01-01_0000") in captured.err
    assert spawn.calls == []


def test_missing_system_wav(tmp_path, capsys, monkeypatch) -> None:
    spawn = _Spawn(ok=True)
    monkeypatch.setattr(cli, "_spawn_transcription", spawn)
    _recording(tmp_path, system_wav=False)
    code = cli._do_retranscribe(_cfg(tmp_path), STAMP)
    captured = capsys.readouterr()
    assert code == 1
    assert "no audio left" in captured.err
    assert spawn.calls == []


def test_existing_transcript_preserved(tmp_path, capsys, monkeypatch) -> None:
    spawn = _Spawn(ok=True)
    monkeypatch.setattr(cli, "_spawn_transcription", spawn)
    _recording(tmp_path)
    tdir = tmp_path / "transcripts"
    tdir.mkdir()
    md = tdir / f"{STAMP}.md"
    md.write_text("old transcript\n")
    code = cli._do_retranscribe(_cfg(tmp_path), STAMP)
    assert code == 0
    assert md.is_file()
    assert md.read_text() == "old transcript\n"


def test_duplicate_guard(tmp_path, capsys, monkeypatch) -> None:
    spawn = _Spawn(ok=True)
    monkeypatch.setattr(cli, "_spawn_transcription", spawn)
    _recording(tmp_path)
    write_transcribing_heartbeat(str(tmp_path), STAMP, _fresh_iso(), pid=12345)
    code = cli._do_retranscribe(_cfg(tmp_path), STAMP)
    captured = capsys.readouterr()
    assert code == 1
    assert f"{STAMP} is already transcribing" in captured.err
    assert spawn.calls == []


def test_spawn_failure(tmp_path, capsys, monkeypatch) -> None:
    spawn = _Spawn(ok=False)
    monkeypatch.setattr(cli, "_spawn_transcription", spawn)
    _recording(tmp_path)
    code = cli._do_retranscribe(_cfg(tmp_path), STAMP)
    captured = capsys.readouterr()
    assert code == 1
    assert "could not start background transcription" in captured.err
