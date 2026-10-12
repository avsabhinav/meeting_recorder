"""Offline tests for ``mr.cli`` start/stop/toggle/status/doctor.

Everything that would touch the real world (spawn, transcribe, HF cache,
``os.kill``, state writes) is monkeypatched; no subprocess, no whisper, no
network.
"""

from __future__ import annotations

import os
import re
import signal
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

import mr.cli
from mr.cli import app, notify_complete
from mr.config import Config
from mr.core.transcribe import ModelNotCachedError
from mr.heartbeat import heartbeat_path, read_transcribing_heartbeat
from mr.state import RecordingState

runner = CliRunner()


@pytest.fixture()
def cfg(tmp_path, monkeypatch) -> Config:
    """Config rooted at ``tmp_path``; ``load_config`` patched to return it."""
    c = Config(
        out_root=str(tmp_path),
        model="org/model",
        language="en",
        dedup_threshold=0.6,
        keep_audio=True,
    )
    monkeypatch.setattr(mr.cli, "load_config", lambda: c)
    return c


def test_start_happy(cfg, monkeypatch) -> None:
    monkeypatch.setattr(mr.cli, "_spawn_capture", lambda out_dir, binary, aec: 5566)
    monkeypatch.setattr(mr.cli, "assert_capture_bin", lambda: "/x/mr-capture")
    writes: list[tuple[int, str, str]] = []
    monkeypatch.setattr(
        mr.cli,
        "write_state",
        lambda out_root, pid, out_dir, stamp, started_at: writes.append((pid, out_dir, stamp)),
    )
    result = runner.invoke(app, ["start"])
    assert result.exit_code == 0, result.output
    m = re.search(r"recording started \(stamp (\S+)\)", result.output)
    assert m is not None, result.output
    stamp = m.group(1)
    assert writes == [(5566, str(Path(cfg.out_root) / "recordings" / stamp), stamp)]
    assert (Path(cfg.out_root) / "recordings" / stamp).is_dir()
    assert "out_dir:" in result.output


def test_start_already_recording(cfg, monkeypatch) -> None:
    monkeypatch.setattr(mr.cli, "is_clear", lambda out_root: False)
    spawned: list[object] = []
    monkeypatch.setattr(mr.cli, "_spawn_capture", lambda *a: spawned.append(a))
    result = runner.invoke(app, ["start"])
    assert result.exit_code == 0, result.output
    assert "already recording" in result.output
    assert spawned == []


def test_status_idle(cfg, monkeypatch) -> None:
    monkeypatch.setattr(mr.cli, "read_state", lambda out_root: None)
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0, result.output
    assert "recording: no" in result.output
    assert "no transcript yet" in result.output


def test_status_active(cfg, monkeypatch) -> None:
    state = RecordingState(
        1, 5566, "/tmp/x/recordings/s", "2026-01-01_0000", "2026-01-01T00:00:00Z"
    )
    monkeypatch.setattr(mr.cli, "read_state", lambda out_root: state)
    tdir = Path(cfg.out_root) / "transcripts"
    tdir.mkdir(parents=True)
    (tdir / "2025-12-31_1200.md").write_text("# older\n", encoding="utf-8")
    (tdir / "2026-01-01_0000.md").write_text("# newer\n", encoding="utf-8")
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0, result.output
    assert "recording: yes" in result.output
    assert "5566" in result.output
    assert "2026-01-01_0000" in result.output
    assert "2026-01-01_0000.md" in result.output


def test_status_active_but_transcripts_dir_empty(cfg, monkeypatch) -> None:
    state = RecordingState(
        1, 5566, "/tmp/x/recordings/s", "2026-01-01_0000", "2026-01-01T00:00:00Z"
    )
    monkeypatch.setattr(mr.cli, "read_state", lambda out_root: state)
    # transcripts dir exists but holds no *.md files -> must not IndexError.
    tdir = Path(cfg.out_root) / "transcripts"
    tdir.mkdir(parents=True)
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0, result.output
    assert "recording: yes" in result.output
    assert "no transcript yet" in result.output


def test_stop_not_recording(cfg, monkeypatch) -> None:
    monkeypatch.setattr(mr.cli, "read_state", lambda out_root: None)
    cleared: list[object] = []
    monkeypatch.setattr(mr.cli, "clear_state", lambda out_root: cleared.append(out_root))
    result = runner.invoke(app, ["stop"])
    assert result.exit_code == 0, result.output
    assert "not recording" in result.output
    assert cleared == []


def _make_active_state(cfg, tmp_path) -> RecordingState:
    out_dir = Path(cfg.out_root) / "recordings" / "s1"
    out_dir.mkdir(parents=True)
    (out_dir / "mic.wav").write_bytes(b"stub")
    (out_dir / "system.wav").write_bytes(b"stub")
    (out_dir / "meta.json").write_text("{}", encoding="utf-8")
    return RecordingState(1, os.getpid(), str(out_dir), "s1", "2026-01-01T00:00:00")


def _fake_transcribe_and_write(cfg, tmp_path):
    def _fake(cfg_: Config, stamp: str, out_dir: str, *, json_sidecar: bool = False) -> Path:
        p = Path(cfg_.out_root) / "transcripts" / f"{stamp}.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"# Meeting — {stamp}\n", encoding="utf-8")
        return p

    return _fake


def test_stop_happy(cfg, tmp_path, monkeypatch) -> None:
    state = _make_active_state(cfg, tmp_path)
    monkeypatch.setattr(mr.cli, "read_state", lambda out_root: state)
    kills: list[tuple[int, int]] = []
    monkeypatch.setattr(mr.cli.os, "kill", lambda pid, sig: kills.append((pid, sig)))
    monkeypatch.setattr(mr.cli, "_transcribe_and_write", _fake_transcribe_and_write(cfg, tmp_path))
    cleared: list[str] = []
    monkeypatch.setattr(mr.cli, "clear_state", lambda out_root: cleared.append(out_root))
    monkeypatch.setattr(mr.cli, "notify_complete", lambda stamp, md: True)
    result = runner.invoke(app, ["stop"])
    assert result.exit_code == 0, result.output
    assert (os.getpid(), signal.SIGINT) in kills
    assert "wrote" in result.output and "transcripts/s1.md" in result.output
    assert (Path(cfg.out_root) / "transcripts" / "s1.md").is_file()
    assert cleared == [cfg.out_root]
    # keep_audio=True in the fixture: WAVs are left in place
    assert (Path(state.out_dir) / "mic.wav").exists()


def test_stop_model_not_cached_keeps_state(cfg, tmp_path, monkeypatch) -> None:
    state = _make_active_state(cfg, tmp_path)
    monkeypatch.setattr(mr.cli, "read_state", lambda out_root: state)
    monkeypatch.setattr(mr.cli.os, "kill", lambda pid, sig: None)

    def _boom(*args: object, **kwargs: object) -> Path:
        raise ModelNotCachedError("model not cached")

    monkeypatch.setattr(mr.cli, "_transcribe_and_write", _boom)
    cleared: list[str] = []
    monkeypatch.setattr(mr.cli, "clear_state", lambda out_root: cleared.append(out_root))
    result = runner.invoke(app, ["stop"])
    assert result.exit_code == 3
    assert "not cached" in result.output
    assert cleared == []  # state left in place for retry


def test_toggle_idle_starts(cfg, monkeypatch) -> None:
    monkeypatch.setattr(mr.cli, "read_state", lambda out_root: None)
    monkeypatch.setattr(mr.cli, "is_clear", lambda out_root: True)
    spawned: list[tuple[str, str, bool]] = []
    def _spawn(out_dir: str, binary: str, aec: bool) -> int:
        spawned.append((out_dir, binary, aec))
        return 5566

    monkeypatch.setattr(mr.cli, "_spawn_capture", _spawn)
    monkeypatch.setattr(mr.cli, "assert_capture_bin", lambda: "/x/mr-capture")
    monkeypatch.setattr(mr.cli, "write_state", lambda *a, **k: None)
    result = runner.invoke(app, ["toggle"])
    assert result.exit_code == 0, result.output
    assert "recording started" in result.output
    assert len(spawned) == 1
    assert spawned[0][1] == "/x/mr-capture"
    assert spawned[0][2] is True  # aec default


def test_toggle_active_stops(cfg, tmp_path, monkeypatch) -> None:
    state = _make_active_state(cfg, tmp_path)
    monkeypatch.setattr(mr.cli, "read_state", lambda out_root: state)
    monkeypatch.setattr(mr.cli, "is_clear", lambda out_root: False)
    kills: list[tuple[int, int]] = []
    monkeypatch.setattr(mr.cli.os, "kill", lambda pid, sig: kills.append((pid, sig)))
    monkeypatch.setattr(mr.cli, "_transcribe_and_write", _fake_transcribe_and_write(cfg, tmp_path))
    cleared: list[str] = []
    monkeypatch.setattr(mr.cli, "clear_state", lambda out_root: cleared.append(out_root))
    monkeypatch.setattr(mr.cli, "notify_complete", lambda stamp, md: True)
    result = runner.invoke(app, ["toggle"])
    assert result.exit_code == 0, result.output
    assert (os.getpid(), signal.SIGINT) in kills
    assert "wrote" in result.output and "transcripts/s1.md" in result.output
    assert cleared == [cfg.out_root]


# ---------------------------------------------------------------------------
# P2.5: osascript completion notification on stop/toggle
# ---------------------------------------------------------------------------


def test_notify_complete_success(monkeypatch) -> None:
    calls: list[object] = []

    def _fake_run(cmd: object, **kwargs: object) -> object:
        calls.append((cmd, kwargs))

        class _P:
            returncode = 0

        return _P()

    monkeypatch.setattr(mr.cli.subprocess, "run", _fake_run)

    assert notify_complete("s1", Path("/x/transcripts/s1.md")) is True
    assert len(calls) == 1
    cmd, kwargs = calls[0]
    assert list(cmd)[:2] == ["osascript", "-e"]
    assert cmd[2].startswith('display notification "')
    assert cmd[2].endswith('with title "mr"')
    assert kwargs.get("timeout") == 10


def test_notify_complete_missing_osascript(monkeypatch) -> None:
    def _boom(*args: object, **kwargs: object) -> object:
        raise FileNotFoundError("osascript not found")

    monkeypatch.setattr(mr.cli.subprocess, "run", _boom)

    assert notify_complete("s1", Path("/x/transcripts/s1.md")) is False


def test_notify_complete_timeout(monkeypatch) -> None:
    def _boom(*args: object, **kwargs: object) -> object:
        raise subprocess.TimeoutExpired(cmd="osascript", timeout=10)

    monkeypatch.setattr(mr.cli.subprocess, "run", _boom)

    assert notify_complete("s1", Path("/x/transcripts/s1.md")) is False


def test_notify_complete_escapes_quotes(monkeypatch) -> None:
    captured: list[object] = []

    def _fake_run(cmd: object, **kwargs: object) -> object:
        captured.append(cmd)

        class _P:
            returncode = 0

        return _P()

    monkeypatch.setattr(mr.cli.subprocess, "run", _fake_run)

    assert notify_complete('a "quoted" stamp', Path("/x/transcripts/s1.md")) is True
    script = captured[0][2]
    assert '\\"quoted\\"' in script


def test_stop_posts_notification_on_success(cfg, tmp_path, monkeypatch) -> None:
    state = _make_active_state(cfg, tmp_path)
    monkeypatch.setattr(mr.cli, "read_state", lambda out_root: state)
    monkeypatch.setattr(mr.cli.os, "kill", lambda pid, sig: None)
    monkeypatch.setattr(mr.cli, "_transcribe_and_write", _fake_transcribe_and_write(cfg, tmp_path))
    monkeypatch.setattr(mr.cli, "clear_state", lambda out_root: None)
    notified: list[tuple[str, Path]] = []
    monkeypatch.setattr(
        mr.cli, "notify_complete", lambda stamp, md: notified.append((stamp, md)) or True
    )
    result = runner.invoke(app, ["stop"])
    assert result.exit_code == 0, result.output
    md_path = Path(cfg.out_root) / "transcripts" / "s1.md"
    assert notified == [(state.stamp, md_path)]


def test_stop_does_not_notify_when_not_recording(cfg, monkeypatch) -> None:
    monkeypatch.setattr(mr.cli, "read_state", lambda out_root: None)
    notified: list[object] = []
    monkeypatch.setattr(
        mr.cli, "notify_complete", lambda stamp, md: notified.append((stamp, md))
    )
    result = runner.invoke(app, ["stop"])
    assert result.exit_code == 0, result.output
    assert "not recording" in result.output
    assert notified == []


def test_stop_does_not_notify_on_model_not_cached(cfg, tmp_path, monkeypatch) -> None:
    state = _make_active_state(cfg, tmp_path)
    monkeypatch.setattr(mr.cli, "read_state", lambda out_root: state)
    monkeypatch.setattr(mr.cli.os, "kill", lambda pid, sig: None)

    def _boom(*args: object, **kwargs: object) -> Path:
        raise ModelNotCachedError("model not cached")

    monkeypatch.setattr(mr.cli, "_transcribe_and_write", _boom)
    notified: list[object] = []
    monkeypatch.setattr(
        mr.cli, "notify_complete", lambda stamp, md: notified.append((stamp, md))
    )
    result = runner.invoke(app, ["stop"])
    assert result.exit_code == 3
    assert notified == []


# ---------------------------------------------------------------------------
# MB-PY3: transcription heartbeat — written before transcription, cleared
# (via finally) on success AND on the model-not-cached path. Real mr.heartbeat
# file I/O against ``cfg.out_root`` (tmp_path).
# ---------------------------------------------------------------------------


def test_stop_writes_heartbeat_during_transcription(cfg, tmp_path, monkeypatch) -> None:
    state = _make_active_state(cfg, tmp_path)
    monkeypatch.setattr(mr.cli, "read_state", lambda out_root: state)
    monkeypatch.setattr(mr.cli.os, "kill", lambda pid, sig: None)
    observed: dict[str, object] = {}

    def _fake(cfg_: Config, stamp: str, out_dir: str, *, json_sidecar: bool = False) -> Path:
        # While transcribing, the heartbeat for this stamp must be present.
        observed["during"] = read_transcribing_heartbeat(cfg_.out_root)
        p = Path(cfg_.out_root) / "transcripts" / f"{stamp}.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"# Meeting — {stamp}\n", encoding="utf-8")
        return p

    monkeypatch.setattr(mr.cli, "_transcribe_and_write", _fake)
    monkeypatch.setattr(mr.cli, "clear_state", lambda out_root: None)
    monkeypatch.setattr(mr.cli, "notify_complete", lambda stamp, md: True)
    result = runner.invoke(app, ["stop"])
    assert result.exit_code == 0, result.output
    during = observed["during"]
    assert during is not None and during["stamp"] == state.stamp
    assert during["out_root"] == str(Path(cfg.out_root).resolve())
    # After stop completes, the heartbeat is cleared (file gone).
    assert read_transcribing_heartbeat(cfg.out_root) is None
    assert not heartbeat_path(cfg.out_root).exists()


def test_stop_clears_heartbeat_on_model_not_cached(cfg, tmp_path, monkeypatch) -> None:
    state = _make_active_state(cfg, tmp_path)
    monkeypatch.setattr(mr.cli, "read_state", lambda out_root: state)
    monkeypatch.setattr(mr.cli.os, "kill", lambda pid, sig: None)

    def _boom(*args: object, **kwargs: object) -> Path:
        raise ModelNotCachedError("model not cached")

    monkeypatch.setattr(mr.cli, "_transcribe_and_write", _boom)
    monkeypatch.setattr(mr.cli, "clear_state", lambda out_root: None)
    result = runner.invoke(app, ["stop"])
    assert result.exit_code == 3
    assert "not cached" in result.output
    # finally must have cleared the heartbeat even on the error path.
    assert read_transcribing_heartbeat(cfg.out_root) is None
    assert not heartbeat_path(cfg.out_root).exists()


def test_stop_not_recording_writes_no_heartbeat(cfg, monkeypatch) -> None:
    monkeypatch.setattr(mr.cli, "read_state", lambda out_root: None)
    writes: list[object] = []
    monkeypatch.setattr(
        mr.cli, "write_transcribing_heartbeat", lambda *a, **k: writes.append((a, k))
    )
    result = runner.invoke(app, ["stop"])
    assert result.exit_code == 0, result.output
    assert "not recording" in result.output
    assert writes == []
    assert read_transcribing_heartbeat(cfg.out_root) is None


def test_doctor_offline(cfg, monkeypatch) -> None:
    monkeypatch.setattr(mr.cli.platform, "mac_ver", lambda: ("14.2.0", "", ""))
    monkeypatch.setattr(mr.cli, "_model_cached", lambda model: False)
    monkeypatch.setattr(mr.cli, "assert_capture_bin", lambda: "/x/mr-capture")
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0, result.output
    assert "14.2.0" in result.output
    assert "/x/mr-capture" in result.output
    assert "org/model" in result.output
    assert "model cached: no" in result.output


def test_doctor_fetch_model_not_cached(cfg, monkeypatch) -> None:
    monkeypatch.setattr(mr.cli.platform, "mac_ver", lambda: ("14.2.0", "", ""))
    monkeypatch.setattr(mr.cli, "_model_cached", lambda model: False)
    monkeypatch.setattr(mr.cli, "assert_capture_bin", lambda: "/x/mr-capture")
    fetched: list[str] = []
    monkeypatch.setattr(mr.cli, "_fetch_model", lambda model: fetched.append(model))
    result = runner.invoke(app, ["doctor", "--fetch-model"])
    assert result.exit_code == 0, result.output
    assert "fetched org/model" in result.output
    assert fetched == ["org/model"]


def test_doctor_fetch_model_cached(cfg, monkeypatch) -> None:
    monkeypatch.setattr(mr.cli.platform, "mac_ver", lambda: ("14.2.0", "", ""))
    monkeypatch.setattr(mr.cli, "_model_cached", lambda model: True)
    monkeypatch.setattr(mr.cli, "assert_capture_bin", lambda: "/x/mr-capture")
    fetched: list[str] = []
    monkeypatch.setattr(mr.cli, "_fetch_model", lambda model: fetched.append(model))
    result = runner.invoke(app, ["doctor", "--fetch-model"])
    assert result.exit_code == 0, result.output
    assert "already cached" in result.output
    assert fetched == []  # no download attempted
