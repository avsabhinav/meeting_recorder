"""Offline tests for ``mr.cli`` start/stop/toggle/status/doctor.

Everything that would touch the real world (spawn, transcribe, HF cache,
``os.kill``, state writes) is monkeypatched; no subprocess, no whisper, no
network.
"""

from __future__ import annotations

import dataclasses
import os
import re
import signal
import subprocess
import sys
from pathlib import Path

import pytest
import typer
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
    monkeypatch.setattr(mr.cli, "_spawn_capture", lambda out_dir, binary: 5566)
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


def test_spawn_capture_detaches_stdio(cfg, tmp_path, monkeypatch) -> None:
    """MB-OPEN/O1: the child must NOT inherit ``mr start``'s stdio.

    ``mr-capture`` is long-lived; if it kept the parent's stdout/stderr pipe
    open, a blocking read (e.g. the menu-bar app) would stay blocked for the
    whole recording. So ``_spawn_capture`` must redirect the child's stdio
    to a per-session log file and detach it into its own process session.
    """
    recorded: dict[str, object] = {}

    class _StubPopen:
        pid = 5566

        def __init__(self, argv: object, **kwargs: object) -> None:
            recorded["argv"] = argv
            recorded.update(kwargs)
            # Capture the fd while it is still open (Popen dup's it into the child).
            recorded["fileno_at_spawn"] = kwargs["stdout"].fileno()

    monkeypatch.setattr(mr.cli.subprocess, "Popen", _StubPopen)

    pid = mr.cli._spawn_capture(str(tmp_path), "/x/mr-capture")

    assert pid == 5566
    assert recorded["argv"] == ["/x/mr-capture", "--out", str(tmp_path)]
    assert recorded["start_new_session"] is True
    out = recorded["stdout"]
    assert out is recorded["stderr"]
    assert callable(out.fileno)
    assert recorded["fileno_at_spawn"] >= 0
    assert out.encoding == "utf-8"  # text stream, not raw bytes
    assert (tmp_path / ".capture.log").is_file()


def test_start_with_context_json(cfg, tmp_path, monkeypatch) -> None:
    """CAL-P1: ``--context-json`` persists meeting context into the recording dir."""
    monkeypatch.setattr(mr.cli, "_spawn_capture", lambda out_dir, binary: 5566)
    monkeypatch.setattr(mr.cli, "assert_capture_bin", lambda: "/x/mr-capture")
    monkeypatch.setattr(mr.cli, "write_state", lambda *a, **k: None)
    payload = '{"title": "Standup", "attendees": ["Alice", "Bob"]}'
    tmpctx = tmp_path / "meeting.json"
    tmpctx.write_text(payload, encoding="utf-8")
    result = runner.invoke(app, ["start", "--context-json", str(tmpctx)])
    assert result.exit_code == 0, result.output
    m = re.search(r"recording started \(stamp (\S+)\)", result.output)
    assert m is not None, result.output
    stamp = m.group(1)
    ctx_path = Path(cfg.out_root) / "recordings" / stamp / "meeting_context.json"
    assert ctx_path.is_file()
    assert ctx_path.read_text(encoding="utf-8") == payload


def test_start_with_invalid_context_json(cfg, tmp_path, monkeypatch) -> None:
    """CAL-P1: a missing/non-JSON ``--context-json`` path is rejected with exit 2."""
    monkeypatch.setattr(mr.cli, "_spawn_capture", lambda out_dir, binary: 5566)
    monkeypatch.setattr(mr.cli, "assert_capture_bin", lambda: "/x/mr-capture")
    monkeypatch.setattr(mr.cli, "write_state", lambda *a, **k: None)
    missing = tmp_path / "nope.json"
    result = runner.invoke(app, ["start", "--context-json", str(missing)])
    assert result.exit_code == 2, result.output
    assert "--context-json file not found or invalid" in result.output


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
    monkeypatch.setattr(mr.cli, "is_stale", lambda state: False)
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
    monkeypatch.setattr(mr.cli, "is_stale", lambda state: False)
    # transcripts dir exists but holds no *.md files -> must not IndexError.
    tdir = Path(cfg.out_root) / "transcripts"
    tdir.mkdir(parents=True)
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0, result.output
    assert "recording: yes" in result.output
    assert "no transcript yet" in result.output


def test_status_stale_prints_no(cfg, monkeypatch) -> None:
    state = RecordingState(
        1, 5566, "/tmp/x/recordings/s", "2026-01-01_0000", "2026-01-01T00:00:00Z"
    )
    monkeypatch.setattr(mr.cli, "read_state", lambda out_root: state)
    monkeypatch.setattr(mr.cli, "is_stale", lambda state: True)
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0, result.output
    assert "recording: no" in result.output
    assert "pid:" in result.output
    assert "out_dir:" in result.output
    assert "stamp:" in result.output
    assert "started_at:" in result.output
    assert "stale pidfile" in result.stderr


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


def test_spawn_transcription_detached(monkeypatch) -> None:
    """MB-BG/B2: the worker must outlive ``mr stop`` and not hold its stdio."""
    recorded: dict[str, object] = {}

    class _StubPopen:
        def __init__(self, argv: object, **kwargs: object) -> None:
            recorded["argv"] = argv
            recorded.update(kwargs)

    monkeypatch.setattr(mr.cli.subprocess, "Popen", _StubPopen)

    assert mr.cli._spawn_transcription("s1", "/tmp/out", json_sidecar=True) is True
    # argv ends with the `mr _transcribe` invocation (sys.executable first).
    assert recorded["argv"][1:] == [
        "-m", "mr.cli", "_transcribe", "s1", "/tmp/out", "--json"
    ]
    assert recorded["stdin"] is subprocess.DEVNULL
    assert recorded["stdout"] is subprocess.DEVNULL
    assert recorded["stderr"] is subprocess.DEVNULL
    assert recorded["start_new_session"] is True


def test_spawn_transcription_frozen_no_module_prefix(monkeypatch) -> None:
    """PKG-BUNDLE/4: a frozen binary must NOT prepend `-m mr.cli` when
    re-spawning the background _transcribe worker."""
    recorded: dict[str, object] = {}

    class _StubPopen:
        def __init__(self, argv: object, **kwargs: object) -> None:
            recorded["argv"] = argv
            recorded.update(kwargs)

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(mr.cli.subprocess, "Popen", _StubPopen)

    assert mr.cli._spawn_transcription("s1", "/tmp/out") is True
    assert recorded["argv"] == [sys.executable, "_transcribe", "s1", "/tmp/out"]


def test_spawn_transcription_failure_returns_false(monkeypatch) -> None:
    def _boom(*args: object, **kwargs: object) -> object:
        raise OSError("spawn failed")

    monkeypatch.setattr(mr.cli.subprocess, "Popen", _boom)
    assert mr.cli._spawn_transcription("s1", "/tmp/out") is False


def test_stop_happy(cfg, tmp_path, monkeypatch) -> None:
    state = _make_active_state(cfg, tmp_path)
    monkeypatch.setattr(mr.cli, "read_state", lambda out_root: state)
    kills: list[tuple[int, int]] = []
    monkeypatch.setattr(mr.cli.os, "kill", lambda pid, sig: kills.append((pid, sig)))
    spawns: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def _spawn(stamp: str, out_dir: str, *, json_sidecar: bool = False) -> bool:
        spawns.append(((stamp, out_dir), {"json_sidecar": json_sidecar}))
        return True

    monkeypatch.setattr(mr.cli, "_spawn_transcription", _spawn)
    transcribed: list[object] = []
    monkeypatch.setattr(
        mr.cli, "_transcribe_and_write", lambda *a, **k: transcribed.append(a)
    )
    cleared: list[str] = []
    monkeypatch.setattr(mr.cli, "clear_state", lambda out_root: cleared.append(out_root))
    result = runner.invoke(app, ["stop"])
    assert result.exit_code == 0, result.output
    assert (os.getpid(), signal.SIGINT) in kills
    assert "transcribing in the background" in result.output
    assert spawns == [((state.stamp, state.out_dir), {"json_sidecar": False})]
    # Transcription must NOT run synchronously inside ``mr stop``.
    assert transcribed == []
    assert not (Path(cfg.out_root) / "transcripts" / "s1.md").exists()
    # State is cleared so a new recording can start immediately.
    assert cleared == [cfg.out_root]


def test_stop_missing_files_clears_state_without_transcribing(cfg, tmp_path, monkeypatch) -> None:
    # out_dir exists as a directory but holds NO mic.wav/system.wav.
    out_dir = Path(cfg.out_root) / "recordings" / "s2"
    out_dir.mkdir(parents=True)
    state = RecordingState(1, 5566, str(out_dir), "s2", "2026-01-01T00:00:00")
    monkeypatch.setattr(mr.cli, "read_state", lambda out_root: state)
    monkeypatch.setattr(mr.cli, "is_stale", lambda state: True)  # skip flush-wait
    spawned: list[object] = []
    monkeypatch.setattr(
        mr.cli, "_spawn_transcription", lambda *a, **k: spawned.append((a, k)) or True
    )
    cleared: list[str] = []
    monkeypatch.setattr(mr.cli, "clear_state", lambda out_root: cleared.append(out_root))
    result = runner.invoke(app, ["stop"])
    assert result.exit_code == 0, result.output
    assert "Traceback" not in result.output
    assert "missing" in result.output
    assert cleared == [cfg.out_root]
    assert spawned == []  # no background transcription spawned


def test_stop_spawns_background_transcription(cfg, tmp_path, monkeypatch) -> None:
    """MB-BG/B2: the sync exit-3 path is gone — stop spawns and returns 0.

    The worker's exit-3-on-model-not-cached is covered by the B1
    ``_transcribe_worker`` tests below.
    """
    state = _make_active_state(cfg, tmp_path)
    monkeypatch.setattr(mr.cli, "read_state", lambda out_root: state)
    monkeypatch.setattr(mr.cli.os, "kill", lambda pid, sig: None)
    spawned: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def _spawn(stamp: str, out_dir: str, *, json_sidecar: bool = False) -> bool:
        spawned.append(((stamp, out_dir), {"json_sidecar": json_sidecar}))
        return True

    monkeypatch.setattr(mr.cli, "_spawn_transcription", _spawn)
    transcribed: list[object] = []
    monkeypatch.setattr(
        mr.cli, "_transcribe_and_write", lambda *a, **k: transcribed.append(a)
    )
    cleared: list[str] = []
    monkeypatch.setattr(mr.cli, "clear_state", lambda out_root: cleared.append(out_root))
    result = runner.invoke(app, ["stop"])
    assert result.exit_code == 0
    assert "Traceback" not in result.output
    assert "transcribing in the background" in result.output
    assert spawned == [((state.stamp, state.out_dir), {"json_sidecar": False})]
    assert transcribed == []  # no synchronous transcription
    assert cleared == [cfg.out_root]  # state cleared so a new recording is possible


def test_toggle_idle_starts(cfg, monkeypatch) -> None:
    monkeypatch.setattr(mr.cli, "read_state", lambda out_root: None)
    monkeypatch.setattr(mr.cli, "is_clear", lambda out_root: True)
    spawned: list[tuple[str, str]] = []
    def _spawn(out_dir: str, binary: str) -> int:
        spawned.append((out_dir, binary))
        return 5566

    monkeypatch.setattr(mr.cli, "_spawn_capture", _spawn)
    monkeypatch.setattr(mr.cli, "assert_capture_bin", lambda: "/x/mr-capture")
    monkeypatch.setattr(mr.cli, "write_state", lambda *a, **k: None)
    result = runner.invoke(app, ["toggle"])
    assert result.exit_code == 0, result.output
    assert "recording started" in result.output
    assert len(spawned) == 1
    assert spawned[0][1] == "/x/mr-capture"


def test_toggle_active_stops(cfg, tmp_path, monkeypatch) -> None:
    state = _make_active_state(cfg, tmp_path)
    monkeypatch.setattr(mr.cli, "read_state", lambda out_root: state)
    monkeypatch.setattr(mr.cli, "is_clear", lambda out_root: False)
    kills: list[tuple[int, int]] = []
    monkeypatch.setattr(mr.cli.os, "kill", lambda pid, sig: kills.append((pid, sig)))
    spawned: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def _spawn(stamp: str, out_dir: str, *, json_sidecar: bool = False) -> bool:
        spawned.append(((stamp, out_dir), {"json_sidecar": json_sidecar}))
        return True

    monkeypatch.setattr(mr.cli, "_spawn_transcription", _spawn)
    cleared: list[str] = []
    monkeypatch.setattr(mr.cli, "clear_state", lambda out_root: cleared.append(out_root))
    result = runner.invoke(app, ["toggle"])
    assert result.exit_code == 0, result.output
    assert (os.getpid(), signal.SIGINT) in kills
    assert "transcribing in the background" in result.output
    assert spawned == [((state.stamp, state.out_dir), {"json_sidecar": False})]
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


# ---------------------------------------------------------------------------
# MB-PY3: transcription heartbeat — written before transcription, cleared
# (via finally) on success AND on the model-not-cached path. Real mr.heartbeat
# file I/O against ``cfg.out_root`` (tmp_path).
# ---------------------------------------------------------------------------


def test_stop_does_not_write_heartbeat_or_notify(cfg, tmp_path, monkeypatch) -> None:
    """MB-BG/B2: the heartbeat + notification are owned by the worker, not stop.

    (The worker-side heartbeat/notify behaviour is covered by the B1
    ``_transcribe_worker`` / ``_transcribe`` tests below.)
    """
    state = _make_active_state(cfg, tmp_path)
    monkeypatch.setattr(mr.cli, "read_state", lambda out_root: state)
    monkeypatch.setattr(mr.cli.os, "kill", lambda pid, sig: None)
    hb_writes: list[tuple[tuple[object, ...], dict[str, object]]] = []
    monkeypatch.setattr(
        mr.cli,
        "write_transcribing_heartbeat",
        lambda *a, **k: hb_writes.append(((a), k)),
    )
    hb_clears: list[tuple[tuple[object, ...], dict[str, object]]] = []
    monkeypatch.setattr(
        mr.cli,
        "clear_transcribing_heartbeat",
        lambda *a, **k: hb_clears.append(((a), k)),
    )
    notified: list[tuple[str, Path]] = []
    monkeypatch.setattr(
        mr.cli, "notify_complete", lambda stamp, md: notified.append((stamp, md)) or True
    )
    transcribed: list[object] = []
    monkeypatch.setattr(
        mr.cli, "_transcribe_and_write", lambda *a, **k: transcribed.append(a)
    )
    monkeypatch.setattr(mr.cli, "clear_state", lambda out_root: None)
    result = runner.invoke(app, ["stop"])
    assert result.exit_code == 0, result.output
    assert "Traceback" not in result.output
    assert "transcribing in the background" in result.output
    # None of these are the stop command's job any more — the worker does them.
    assert hb_writes == []
    assert hb_clears == []
    assert notified == []
    assert transcribed == []
    # No heartbeat file was ever created on disk either.
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


# ---------------------------------------------------------------------------
# MB-BG/B1: ``mr _transcribe`` hidden background worker — same
# heartbeat/write/clear contract as ``_do_stop``, invoked directly.
# ---------------------------------------------------------------------------


def test_transcribe_worker_writes_and_clears_heartbeat(cfg, tmp_path, monkeypatch) -> None:
    out_dir = tmp_path / "recordings" / "s1"
    out_dir.mkdir(parents=True)
    observed: dict[str, object] = {}

    def _fake(cfg_: Config, stamp: str, out_dir_: str, *, json_sidecar: bool = False) -> Path:
        # While transcribing, the heartbeat for this stamp must be present.
        hb = read_transcribing_heartbeat(cfg_.out_root)
        assert hb is not None
        assert hb["stamp"] == "s1"
        observed["during"] = hb
        p = Path(cfg_.out_root) / "transcripts" / f"{stamp}.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"# Meeting — {stamp}\n", encoding="utf-8")
        return p

    monkeypatch.setattr(mr.cli, "_transcribe_and_write", _fake)
    md = mr.cli._transcribe_worker(cfg, "s1", str(out_dir))
    assert md == Path(cfg.out_root) / "transcripts" / "s1.md"
    assert md.is_file()
    # The timestamp must be UTC-aware and Z-suffixed (Swift ISO8601DateFormatter).
    assert observed["during"]["started_at"].endswith("Z")
    # After the worker returns, the heartbeat is cleared (file gone).
    assert read_transcribing_heartbeat(cfg.out_root) is None
    assert not heartbeat_path(cfg.out_root).exists()


def test_transcribe_worker_model_not_cached_clears_heartbeat(cfg, tmp_path, monkeypatch) -> None:
    out_dir = tmp_path / "recordings" / "s1"
    out_dir.mkdir(parents=True)

    def _boom(*args: object, **kwargs: object) -> Path:
        raise ModelNotCachedError("model not cached")

    monkeypatch.setattr(mr.cli, "_transcribe_and_write", _boom)
    with pytest.raises(typer.Exit) as excinfo:
        mr.cli._transcribe_worker(cfg, "s1", str(out_dir))
    assert excinfo.value.exit_code == 3
    # finally must have cleared the heartbeat even on the error path.
    assert read_transcribing_heartbeat(cfg.out_root) is None
    assert not heartbeat_path(cfg.out_root).exists()


def test_transcribe_worker_removes_wavs_when_keep_audio_false(cfg, tmp_path, monkeypatch) -> None:
    cfg = dataclasses.replace(cfg, keep_audio=False)
    out_dir = tmp_path / "recordings" / "s1"
    out_dir.mkdir(parents=True)
    (out_dir / "mic.wav").write_bytes(b"RIFF")
    (out_dir / "system.wav").write_bytes(b"RIFF")

    def _fake(cfg_: Config, stamp: str, out_dir_: str, *, json_sidecar: bool = False) -> Path:
        p = Path(cfg_.out_root) / "transcripts" / f"{stamp}.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"# Meeting — {stamp}\n", encoding="utf-8")
        return p

    monkeypatch.setattr(mr.cli, "_transcribe_and_write", _fake)
    mr.cli._transcribe_worker(cfg, "s1", str(out_dir))
    assert not (out_dir / "mic.wav").exists()
    assert not (out_dir / "system.wav").exists()


def test_transcribe_command_happy_path(cfg, tmp_path, monkeypatch) -> None:
    out_dir = tmp_path / "recordings" / "s1"
    out_dir.mkdir(parents=True)

    def _fake(cfg_: Config, stamp: str, out_dir_: str, *, json_sidecar: bool = False) -> Path:
        p = Path(cfg_.out_root) / "transcripts" / f"{stamp}.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"# Meeting — {stamp}\n", encoding="utf-8")
        return p

    monkeypatch.setattr(mr.cli, "_transcribe_and_write", _fake)
    notified: list[tuple[str, Path]] = []
    monkeypatch.setattr(
        mr.cli, "notify_complete", lambda stamp, md: notified.append((stamp, md)) or True
    )
    result = runner.invoke(app, ["_transcribe", "s1", str(out_dir)])
    assert result.exit_code == 0, result.output
    assert "wrote" in result.output
    assert (Path(cfg.out_root) / "transcripts" / "s1.md").is_file()
    assert notified == [("s1", Path(cfg.out_root) / "transcripts" / "s1.md")]
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
