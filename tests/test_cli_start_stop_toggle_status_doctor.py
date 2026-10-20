"""Offline tests for ``mr.cli`` start/stop/toggle/status/doctor.

Everything that would touch the real world (spawn, transcribe, HF cache,
``os.kill``, state writes) is monkeypatched; no subprocess, no whisper, no
network.
"""

from __future__ import annotations

import dataclasses
import json
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
from mr.cli import app
from mr.config import Config
from mr.core.schema import Segment, TranscriptionResult
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


def test_spawn_transcription_detached(tmp_path, monkeypatch) -> None:
    """MB-BG/B2: the worker must outlive ``mr stop`` and not hold its stdio.

    Its output goes to ``<out_dir>/.transcribe.log`` rather than being
    discarded: a detached worker that dies must leave a trace.
    """
    recorded: dict[str, object] = {}

    class _StubPopen:
        def __init__(self, argv: object, **kwargs: object) -> None:
            recorded["argv"] = argv
            recorded.update(kwargs)
            # Capture the fd while it is still open (Popen dup's it into the child).
            recorded["fileno_at_spawn"] = kwargs["stdout"].fileno()

    monkeypatch.setattr(mr.cli.subprocess, "Popen", _StubPopen)

    assert mr.cli._spawn_transcription("s1", str(tmp_path), json_sidecar=True) is True
    # argv ends with the `mr _transcribe` invocation (sys.executable first).
    assert recorded["argv"][1:] == [
        "-m", "mr.cli", "_transcribe", "s1", str(tmp_path), "--json"
    ]
    assert recorded["stdin"] is subprocess.DEVNULL
    out = recorded["stdout"]
    assert callable(out.fileno)
    assert recorded["fileno_at_spawn"] >= 0
    assert out.encoding == "utf-8"  # text stream, not raw bytes
    assert recorded["stderr"] is subprocess.STDOUT  # merged into the same log
    assert recorded["start_new_session"] is True
    assert (tmp_path / ".transcribe.log").is_file()


def test_spawn_transcription_unwritable_out_dir_still_spawns(monkeypatch) -> None:
    """A missing/unwritable out_dir must not block transcription.

    The log is a diagnostic, not a precondition: fall back to DEVNULL.
    """
    recorded: dict[str, object] = {}

    class _StubPopen:
        def __init__(self, argv: object, **kwargs: object) -> None:
            recorded["argv"] = argv
            recorded.update(kwargs)

    monkeypatch.setattr(mr.cli.subprocess, "Popen", _StubPopen)

    assert mr.cli._spawn_transcription("s1", "/nonexistent/dir/xyz") is True
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
# Notifications are the menu-bar app's job, not the CLI's. The detached worker
# has no bundle identity, so an `osascript` notification was owned by Script
# Editor: no Oatmeal branding, and clicking it opened that app. The app now
# watches the transcripts dir and posts the notification itself
# (menu-bar/Sources/Oatmeal/TranscriptNotifier.swift).
# ---------------------------------------------------------------------------


def test_cli_has_no_notify_helper() -> None:
    """The osascript notification helper is gone for good."""
    assert not hasattr(mr.cli, "notify_complete")


def test_stop_not_recording_runs_no_osascript(cfg, monkeypatch) -> None:
    monkeypatch.setattr(mr.cli, "read_state", lambda out_root: None)
    runs: list[object] = []
    monkeypatch.setattr(mr.cli.subprocess, "run", lambda cmd, **k: runs.append(cmd))
    result = runner.invoke(app, ["stop"])
    assert result.exit_code == 0, result.output
    assert "not recording" in result.output
    assert runs == []


# ---------------------------------------------------------------------------
# MB-PY3: transcription heartbeat — written before transcription, cleared
# (via finally) on success AND on the model-not-cached path. Real mr.heartbeat
# file I/O against ``cfg.out_root`` (tmp_path).
# ---------------------------------------------------------------------------


def test_stop_does_not_write_heartbeat(cfg, tmp_path, monkeypatch) -> None:
    """MB-BG/B2: the heartbeat is owned by the worker, not stop.

    (The worker-side heartbeat behaviour is covered by the B1
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
    transcribed: list[object] = []
    monkeypatch.setattr(
        mr.cli, "_transcribe_and_write", lambda *a, **k: transcribed.append(a)
    )
    monkeypatch.setattr(mr.cli, "clear_state", lambda out_root: None)
    result = runner.invoke(app, ["stop"])
    assert result.exit_code == 0, result.output
    assert "Traceback" not in result.output
    assert "transcribing in the background" in result.output
    # Neither of these is the stop command's job any more — the worker does them.
    assert hb_writes == []
    assert hb_clears == []
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
    # ...and the failure must be visible in the transcripts dir.
    assert (Path(cfg.out_root) / "transcripts" / "s1.FAILED.md").is_file()


def test_transcribe_worker_unexpected_error_writes_failed_stub(cfg, tmp_path, monkeypatch) -> None:
    """A dying worker must leave a marker, not just an aging heartbeat."""
    out_dir = tmp_path / "recordings" / "s1"
    out_dir.mkdir(parents=True)

    def _boom(*args: object, **kwargs: object) -> Path:
        raise RuntimeError("mlx exploded")

    monkeypatch.setattr(mr.cli, "_transcribe_and_write", _boom)
    with pytest.raises(typer.Exit) as excinfo:
        mr.cli._transcribe_worker(cfg, "s1", str(out_dir))
    assert excinfo.value.exit_code == 1
    assert read_transcribing_heartbeat(cfg.out_root) is None

    stub = Path(cfg.out_root) / "transcripts" / "s1.FAILED.md"
    assert stub.is_file()
    text = stub.read_text(encoding="utf-8")
    assert "RuntimeError: mlx exploded" in text
    assert str(out_dir) in text
    assert f"mr _transcribe s1 {out_dir}" in text  # actionable retry
    # No worker log here (this worker was not spawned by _spawn_transcription),
    # so the stub must not point at a file that does not exist.
    assert ".transcribe.log" not in text


def test_failed_stub_names_log_when_it_exists(cfg, tmp_path, monkeypatch) -> None:
    """Spawned workers DO have a log; the stub points at it then."""
    out_dir = tmp_path / "recordings" / "s1"
    out_dir.mkdir(parents=True)
    (out_dir / ".transcribe.log").write_text("Traceback...\n", encoding="utf-8")

    def _boom(*args: object, **kwargs: object) -> Path:
        raise RuntimeError("mlx exploded")

    monkeypatch.setattr(mr.cli, "_transcribe_and_write", _boom)
    with pytest.raises(typer.Exit):
        mr.cli._transcribe_worker(cfg, "s1", str(out_dir))

    text = (Path(cfg.out_root) / "transcripts" / "s1.FAILED.md").read_text(encoding="utf-8")
    assert ".transcribe.log" in text


def test_transcribe_worker_keeps_wavs_on_failure(cfg, tmp_path, monkeypatch) -> None:
    """A failed run must not delete the audio — a retry still needs it."""
    cfg = dataclasses.replace(cfg, keep_audio=False)
    out_dir = tmp_path / "recordings" / "s1"
    out_dir.mkdir(parents=True)
    (out_dir / "mic.wav").write_bytes(b"RIFF")
    (out_dir / "system.wav").write_bytes(b"RIFF")

    def _boom(*args: object, **kwargs: object) -> Path:
        raise RuntimeError("mlx exploded")

    monkeypatch.setattr(mr.cli, "_transcribe_and_write", _boom)
    with pytest.raises(typer.Exit):
        mr.cli._transcribe_worker(cfg, "s1", str(out_dir))
    assert (out_dir / "mic.wav").exists()
    assert (out_dir / "system.wav").exists()


def test_transcribe_worker_success_clears_stale_failed_stub(cfg, tmp_path, monkeypatch) -> None:
    """A successful retry removes the previous run's FAILED marker."""
    out_dir = tmp_path / "recordings" / "s1"
    out_dir.mkdir(parents=True)
    stub = Path(cfg.out_root) / "transcripts" / "s1.FAILED.md"
    stub.parent.mkdir(parents=True, exist_ok=True)
    stub.write_text("# Transcription FAILED — s1\n", encoding="utf-8")

    def _fake(cfg_: Config, stamp: str, out_dir_: str, *, json_sidecar: bool = False) -> Path:
        p = Path(cfg_.out_root) / "transcripts" / f"{stamp}.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"# Meeting — {stamp}\n", encoding="utf-8")
        return p

    monkeypatch.setattr(mr.cli, "_transcribe_and_write", _fake)
    mr.cli._transcribe_worker(cfg, "s1", str(out_dir))
    assert (Path(cfg.out_root) / "transcripts" / "s1.md").is_file()
    assert not stub.exists()


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
    runs: list[object] = []
    monkeypatch.setattr(mr.cli.subprocess, "run", lambda cmd, **k: runs.append(cmd))
    result = runner.invoke(app, ["_transcribe", "s1", str(out_dir)])
    assert result.exit_code == 0, result.output
    assert "wrote" in result.output
    assert (Path(cfg.out_root) / "transcripts" / "s1.md").is_file()
    # The worker posts NO notification: an osascript one would be owned by
    # Script Editor (no branding, opens the wrong app on click). The menu-bar
    # app watches the transcripts dir and posts it instead.
    assert runs == []
    assert read_transcribing_heartbeat(cfg.out_root) is None


# ---------------------------------------------------------------------------
# _stream_start_offsets: mic and system taps do not start together, and each
# WAV begins at its own first sample, so the later stream needs pushing
# forward before the two can be compared on one timeline.
# ---------------------------------------------------------------------------


def _write_meta(out_dir: Path, mic_first: float, system_first: float) -> None:
    """Write a meta.json shaped like mr-capture's, with the two start times."""
    meta = {
        "macos_version": "27.0.1",
        "aec": False,
        "started_at": "2026-10-20T15:53:00+00:00",
        "duration_seconds": 33.7,
        "mic": {
            "device_name": "MacBook Pro Microphone",
            "native_sample_rate": 48000,
            "native_channels": 1,
            "first_sample_seconds": mic_first,
            "samples_written": 1617600,
        },
        "system": {
            "device_name": "Aggregate (system tap)",
            "native_sample_rate": 48000,
            "native_channels": 2,
            "first_sample_seconds": system_first,
            "samples_written": 1108800,
        },
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")


def test_stream_offsets_late_system_shifts_them(tmp_path) -> None:
    """The real case from recordings/2026-10-20_1553: system tap 10.49 s late."""
    _write_meta(tmp_path, mic_first=229768.83, system_first=229779.32)
    mic_offset, system_offset = mr.cli._stream_start_offsets(tmp_path)
    assert mic_offset == 0.0
    assert system_offset == pytest.approx(10.49)


def test_stream_offsets_late_mic_shifts_you(tmp_path) -> None:
    """Negative delta: the mic started later, so You moves instead of Them."""
    _write_meta(tmp_path, mic_first=1010.5, system_first=1000.0)
    mic_offset, system_offset = mr.cli._stream_start_offsets(tmp_path)
    assert mic_offset == pytest.approx(10.5)
    assert system_offset == 0.0


def test_stream_offsets_simultaneous_start_is_zero(tmp_path) -> None:
    _write_meta(tmp_path, mic_first=1234.5, system_first=1234.5)
    assert mr.cli._stream_start_offsets(tmp_path) == (0.0, 0.0)


def test_stream_offsets_missing_meta_shifts_nothing(tmp_path) -> None:
    """An unknown offset must shift nothing: a wrong shift is worse."""
    assert mr.cli._stream_start_offsets(tmp_path) == (0.0, 0.0)


def test_stream_offsets_malformed_meta_shifts_nothing(tmp_path) -> None:
    (tmp_path / "meta.json").write_text("{not json", encoding="utf-8")
    assert mr.cli._stream_start_offsets(tmp_path) == (0.0, 0.0)


def test_stream_offsets_incomplete_meta_shifts_nothing(tmp_path) -> None:
    """meta.json present but missing a stream key (or a field inside one)."""
    (tmp_path / "meta.json").write_text(json.dumps({"aec": True}), encoding="utf-8")
    assert mr.cli._stream_start_offsets(tmp_path) == (0.0, 0.0)

    partial = tmp_path / "partial"
    partial.mkdir()
    (partial / "meta.json").write_text(
        json.dumps({"mic": {"device_name": "m"}, "system": {"device_name": "s"}}),
        encoding="utf-8",
    )
    assert mr.cli._stream_start_offsets(partial) == (0.0, 0.0)


def test_transcribe_and_write_applies_offsets_to_late_track(cfg, tmp_path, monkeypatch) -> None:
    """End to end: the late system track reaches the merge already shifted."""
    out_dir = tmp_path / "recordings" / "s1"
    _write_meta(out_dir, mic_first=1000.0, system_first=1010.0)
    (out_dir / "mic.wav").write_bytes(b"")
    (out_dir / "system.wav").write_bytes(b"")

    def _fake_transcribe(path: str, *, speaker: str, model: str, language: str):
        seg = Segment(speaker=speaker, text=f"{speaker} line", start=1.0, end=3.0)
        return TranscriptionResult(
            track="mic" if speaker == "You" else "system",
            speaker=speaker,
            model=model,
            audio_seconds=3.0,
            wall_seconds=0.1,
            settings={},
            segments=(seg,),
        )

    captured: dict[str, list[Segment]] = {}

    def _fake_merge(you, them, *, dedup_threshold=0.6):
        captured["you"] = you
        captured["them"] = them
        return [*them, *you]

    monkeypatch.setattr(mr.cli, "transcribe_audio", _fake_transcribe)
    monkeypatch.setattr(mr.cli, "merge_transcripts", _fake_merge)
    mr.cli._transcribe_and_write(cfg, "s1", str(out_dir))

    # You stays put (it started first); Them is pushed forward by the delta.
    assert [(s.start, s.end) for s in captured["you"]] == [(1.0, 3.0)]
    assert [(s.start, s.end) for s in captured["them"]] == [(11.0, 13.0)]


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
