"""Tests for mr.core.capture: binary resolution and RecordSession context manager.

Offline, stdlib-only mocking (no real subprocess, no heavy imports).
"""

import json
import os
import signal
from pathlib import Path
from unittest.mock import Mock

import pytest

import mr.core.capture as capture
from mr.core.capture import (
    BIN_ENV_VAR,
    DEFAULT_CAPTURE_BIN,
    RecordSession,
    assert_capture_bin,
)
from mr.core.schema import CaptureMeta

SAMPLE_META = {
    "macos_version": "27.0.1",
    "aec": True,
    "started_at": "2026-01-15T14:30:00+00:00",
    "duration_seconds": 12.0,
    "mic": {
        "device_name": "MacBook Pro Microphone",
        "native_sample_rate": 48000,
        "native_channels": 1,
        "first_sample_seconds": 1.5,
        "samples_written": 1000,
    },
    "system": {
        "device_name": "Aggregate (system tap)",
        "native_sample_rate": 48000,
        "native_channels": 9,
        "first_sample_seconds": 1.6,
        "samples_written": 9000,
    },
}


def _make_fake_bin(tmp_path: Path) -> str:
    """Create a tiny executable script to stand in for mr-capture."""
    script = tmp_path / "fake-mr-capture"
    script.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    script.chmod(0o755)
    return str(script)


def test_bin_resolution_from_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _make_fake_bin(tmp_path)
    monkeypatch.setenv(BIN_ENV_VAR, fake)
    assert assert_capture_bin() == fake


def test_bin_resolution_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(BIN_ENV_VAR, raising=False)
    default = DEFAULT_CAPTURE_BIN
    if Path(default).is_file():
        # Resolved default exists: return it and it must be executable.
        assert assert_capture_bin() == default
        assert os.access(default, os.X_OK)
    else:
        with pytest.raises(FileNotFoundError, match="mr-capture"):
            assert_capture_bin()


def test_missing_bin_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(BIN_ENV_VAR, str(tmp_path / "no-such-binary"))
    with pytest.raises(FileNotFoundError, match="mr-capture"):
        with RecordSession(str(tmp_path / "out")):
            pass  # not reached: __enter__ raises


def test_enter_creates_outdir_and_spawns(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(BIN_ENV_VAR, _make_fake_bin(tmp_path))
    popen = Mock(return_value=Mock())
    monkeypatch.setattr(capture.subprocess, "Popen", popen)

    out_dir = tmp_path / "nested" / "rec1"
    assert not out_dir.exists()
    session = RecordSession(str(out_dir))
    with session:
        pass

    args = popen.call_args[0][0]
    abs_outdir = str(Path(out_dir).resolve())
    assert args[0].endswith("fake-mr-capture")
    assert args[1:3] == ["--out", abs_outdir]
    assert out_dir.is_dir()
    assert session.out_dir == abs_outdir


def test_enter_args_plain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(BIN_ENV_VAR, _make_fake_bin(tmp_path))
    popen = Mock(return_value=Mock())
    monkeypatch.setattr(capture.subprocess, "Popen", popen)

    with RecordSession(str(tmp_path / "rec")):
        pass
    args = popen.call_args[0][0]
    assert args[1:3] == ["--out", str(Path(tmp_path / "rec").resolve())]
    assert len(args) == 3


class FakeProc:
    """Stand-in for subprocess.Popen: reports still-running or already-exited."""

    def __init__(self, returncode: int = 0, running: bool = True) -> None:
        self.pid = 4242
        self.returncode = None if running else returncode
        self._running = running
        self.wait_called = False

    def poll(self) -> int | None:
        return None if self._running else self.returncode

    def wait(self) -> int:
        self.wait_called = True
        self._running = False
        return 0


def test_keyboardinterrupt_sends_sigint_and_propagates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(BIN_ENV_VAR, _make_fake_bin(tmp_path))
    proc = FakeProc()
    monkeypatch.setattr(capture.subprocess, "Popen", lambda *a, **k: proc)
    kills: list[tuple[int, int]] = []
    monkeypatch.setattr(capture.os, "kill", lambda pid, sig: kills.append((pid, sig)))

    session = RecordSession(str(tmp_path / "out"))
    with pytest.raises(KeyboardInterrupt):
        with session:
            raise KeyboardInterrupt
    assert kills == [(4242, signal.SIGINT)]
    assert proc.wait_called
    assert session.returncode == 0
    # meta.json absent -> meta is None, no raise
    assert session.meta is None
    assert session.result().out_dir == str(Path(tmp_path / "out").resolve())


def test_normal_exit_sends_sigterm(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(BIN_ENV_VAR, _make_fake_bin(tmp_path))
    proc = FakeProc()
    monkeypatch.setattr(capture.subprocess, "Popen", lambda *a, **k: proc)
    kills: list[tuple[int, int]] = []
    monkeypatch.setattr(capture.os, "kill", lambda pid, sig: kills.append((pid, sig)))

    with pytest.raises(RuntimeError):
        with RecordSession(str(tmp_path / "out")):
            raise RuntimeError("stop")
    assert kills == [(4242, signal.SIGTERM)]


def test_meta_parse_valid_and_invalid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(BIN_ENV_VAR, _make_fake_bin(tmp_path))
    monkeypatch.setattr(
        capture.subprocess, "Popen", lambda *a, **k: FakeProc(running=False)
    )

    # valid meta.json round-trips to CaptureMeta
    valid = tmp_path / "valid"
    valid.mkdir()
    (valid / "meta.json").write_text(json.dumps(SAMPLE_META), encoding="utf-8")
    s2 = RecordSession(str(valid))
    with s2:
        pass  # child already exited: no signal sent
    assert isinstance(s2.meta, CaptureMeta)
    assert s2.meta.mic.device_name == "MacBook Pro Microphone"
    assert s2.meta.duration_seconds == pytest.approx(12.0)
    assert s2.result().meta is s2.meta

    # invalid meta.json -> meta is None, no raise
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "meta.json").write_text(json.dumps({"aec": True}), encoding="utf-8")
    s3 = RecordSession(str(bad))
    with s3:
        pass
    assert s3.meta is None
    assert s3.returncode == 0


def test_process_lookup_error_on_kill_is_ignored(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(BIN_ENV_VAR, _make_fake_bin(tmp_path))
    proc = FakeProc()
    monkeypatch.setattr(capture.subprocess, "Popen", lambda *a, **k: proc)

    def kill(pid: int, sig: int) -> None:
        raise ProcessLookupError(pid)

    monkeypatch.setattr(capture.os, "kill", kill)
    with RecordSession(str(tmp_path / "out")):
        pass  # must not raise
    assert proc.wait_called
