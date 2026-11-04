"""Tests for `mr stop-transcribe` (mr.cli._do_stop_transcribe)."""

from __future__ import annotations

import subprocess
import sys
import time
from datetime import UTC, datetime

import mr.cli as cli
from mr.config import Config
from mr.heartbeat import heartbeat_path, write_transcribing_heartbeat

STAMP = "2026-10-22_1440"


def _cfg(tmp_path) -> Config:
    return Config(
        out_root=str(tmp_path),
        model="m",
        language="en",
        dedup_threshold=0.6,
        keep_audio=True,
    )


def _fresh_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def test_no_heartbeat(tmp_path, capsys, monkeypatch) -> None:
    monkeypatch.setattr(cli, "_notify_transcription_stopped", lambda stamp: None)
    code = cli._do_stop_transcribe(_cfg(tmp_path))
    out = capsys.readouterr().out
    assert code == 0
    assert "no transcription running" in out


def test_other_stamp(tmp_path, capsys, monkeypatch) -> None:
    monkeypatch.setattr(cli, "_notify_transcription_stopped", lambda stamp: None)
    write_transcribing_heartbeat(str(tmp_path), STAMP, _fresh_iso(), pid=None)
    code = cli._do_stop_transcribe(_cfg(tmp_path), "1999-01-01_0000")
    out = capsys.readouterr().out
    assert code == 0
    assert "no transcription running for 1999-01-01_0000" in out
    assert heartbeat_path(str(tmp_path)).is_file()


def test_live_pid(tmp_path, capsys, monkeypatch) -> None:
    monkeypatch.setattr(cli, "_notify_transcription_stopped", lambda stamp: None)
    # The worker traps SIGTERM, writes a marker, and exits: the marker file
    # is direct proof the command signalled this live worker (its exit status
    # is not observable after the command reaps it). It signals readiness
    # only AFTER installing the handler, so no SIGTERM can be lost.
    ready = tmp_path / "worker-ready"
    marker = tmp_path / "sigterm-marker"
    script = (
        "import signal, sys, time\n"
        "def _term(*_):\n"
        f"    open({str(marker)!r}, 'w').close()\n"
        "    sys.exit(143)\n"
        "signal.signal(signal.SIGTERM, _term)\n"
        f"open({str(ready)!r}, 'w').close()\n"
        "time.sleep(60)\n"
    )
    child = subprocess.Popen([sys.executable, "-c", script])
    try:
        deadline = time.monotonic() + 10
        while not ready.is_file() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert ready.is_file(), "worker never became ready"
        write_transcribing_heartbeat(str(tmp_path), STAMP, _fresh_iso(), pid=child.pid)
        code = cli._do_stop_transcribe(_cfg(tmp_path))
        out = capsys.readouterr().out
        assert code == 0
        assert f"stopped transcription of {STAMP}" in out
        assert not heartbeat_path(str(tmp_path)).is_file()
        child.wait(timeout=10)
        assert marker.is_file(), "SIGTERM was never delivered to the live worker"
    finally:
        try:
            child.kill()
        except (ChildProcessError, ProcessLookupError):
            pass
        child.wait()


def test_child_already_exited_is_already_finished(tmp_path, capsys, monkeypatch) -> None:
    monkeypatch.setattr(cli, "_notify_transcription_stopped", lambda stamp: None)
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(0.2)"])
    try:
        time.sleep(0.6)  # child has exited but is NOT reaped: a zombie
        write_transcribing_heartbeat(str(tmp_path), STAMP, _fresh_iso(), pid=child.pid)
        code = cli._do_stop_transcribe(_cfg(tmp_path))
        out = capsys.readouterr().out
        assert code == 0
        assert f"{STAMP} already finished" in out
        assert not heartbeat_path(str(tmp_path)).is_file()
    finally:
        child.wait()


def test_lingers_but_returns_for_unrelated_pid(tmp_path, capsys, monkeypatch) -> None:
    monkeypatch.setattr(cli, "_notify_transcription_stopped", lambda stamp: None)
    monkeypatch.setattr(cli, "TRANSCRIBE_LINGER_SECONDS", 0.5)
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        write_transcribing_heartbeat(str(tmp_path), STAMP, _fresh_iso(), pid=child.pid)
        start = time.monotonic()
        code = cli._do_stop_transcribe(_cfg(tmp_path))
        elapsed = time.monotonic() - start
        out = capsys.readouterr().out
        assert code == 0
        assert elapsed < 5, f"blocked {elapsed:.1f}s (full linger budget)"
        assert f"stopped transcription of {STAMP}" in out
        assert not heartbeat_path(str(tmp_path)).is_file()
    finally:
        try:
            child.kill()
        except (ChildProcessError, ProcessLookupError):
            pass
        child.wait()


def test_pid_already_gone(tmp_path, capsys, monkeypatch) -> None:
    monkeypatch.setattr(cli, "_notify_transcription_stopped", lambda stamp: None)
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait()  # exit; we reap, so the pid is truly gone
    write_transcribing_heartbeat(str(tmp_path), STAMP, _fresh_iso(), pid=child.pid)
    code = cli._do_stop_transcribe(_cfg(tmp_path))
    out = capsys.readouterr().out
    assert code == 0
    assert f"{STAMP} already finished" in out
    assert not heartbeat_path(str(tmp_path)).is_file()


def test_pid_missing(tmp_path, capsys, monkeypatch) -> None:
    monkeypatch.setattr(cli, "_notify_transcription_stopped", lambda stamp: None)
    write_transcribing_heartbeat(str(tmp_path), STAMP, _fresh_iso(), pid=None)
    code = cli._do_stop_transcribe(_cfg(tmp_path))
    captured = capsys.readouterr()
    assert code == 1
    assert f"cannot stop {STAMP}: heartbeat has no pid" in captured.err


def test_heartbeat_refresher_touches_until_stopped(tmp_path) -> None:
    import time as _time
    from datetime import UTC as _UTC
    from datetime import datetime as _dt
    from datetime import timedelta as _td

    import mr.cli as _cli
    from mr.heartbeat import (
        heartbeat_path,
        read_transcribing_heartbeat,
        write_transcribing_heartbeat,
    )

    root = str(tmp_path)
    old = (_dt.now(_UTC) - _td(seconds=1200)).isoformat().replace("+00:00", "Z")
    write_transcribing_heartbeat(root, "s", old, pid=99)
    stop = _cli._start_heartbeat_refresher(root, "s", 99, interval=0.05)
    try:
        deadline = _time.monotonic() + 2.0
        while read_transcribing_heartbeat(root) is None and _time.monotonic() < deadline:
            _time.sleep(0.02)
        assert read_transcribing_heartbeat(root) is not None
    finally:
        stop.set()
    _time.sleep(0.15)
    heartbeat_path(root).unlink()
    _time.sleep(0.15)
    assert not heartbeat_path(root).exists()  # stopped: never recreated
