"""Tests for mr.state: pidfile read/write, stamp format, stale detection."""

import json
import os
import re
import time
from pathlib import Path

from mr.state import (
    STATE_VERSION,
    RecordingState,
    clear_state,
    is_clear,
    is_stale,
    new_stamp,
    read_state,
    state_dir,
    state_path,
    write_state,
)


def test_state_paths() -> None:
    root = "/tmp/mr-test-root"
    assert state_dir(root) == Path(root) / ".state"
    assert state_path(root) == Path(root) / ".state" / "recording.json"


def test_new_stamp_format() -> None:
    stamp = new_stamp()
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}_\d{4}", stamp) is not None


def test_write_and_read_roundtrip(tmp_path) -> None:
    out_dir = str(tmp_path / "recordings" / "2026-08-24_1432")
    write_state(str(tmp_path), 4242, out_dir, "2026-08-24_1432", "2026-08-24T14:32:00Z")
    assert (tmp_path / ".state").is_dir()
    assert state_path(str(tmp_path)).is_file()
    s = read_state(str(tmp_path))
    assert s == RecordingState(
        version=STATE_VERSION,
        pid=4242,
        out_dir=out_dir,
        stamp="2026-08-24_1432",
        started_at="2026-08-24T14:32:00Z",
    )
    assert s is not None and s.version == 1
    on_disk = json.loads(state_path(str(tmp_path)).read_text())
    assert on_disk == {
        "version": 1,
        "pid": 4242,
        "out_dir": out_dir,
        "stamp": "2026-08-24_1432",
        "started_at": "2026-08-24T14:32:00Z",
    }


def test_read_missing_returns_none(tmp_path) -> None:
    assert read_state(str(tmp_path)) is None
    assert is_clear(str(tmp_path))


def test_read_malformed_returns_none(tmp_path) -> None:
    d = state_dir(str(tmp_path))
    d.mkdir()
    p = state_path(str(tmp_path))
    p.write_text("this is not json {")
    assert read_state(str(tmp_path)) is None

    p.write_text(json.dumps({"version": 999, "pid": 1, "out_dir": "x",
                            "stamp": "s", "started_at": "t"}))
    assert read_state(str(tmp_path)) is None

    p.write_text(json.dumps({"pid": 1, "out_dir": "x", "stamp": "s", "started_at": "t"}))
    assert read_state(str(tmp_path)) is None

    p.write_text(json.dumps({"version": 1, "pid": "nope", "out_dir": "x",
                            "stamp": "s", "started_at": "t"}))
    assert read_state(str(tmp_path)) is None


def test_read_does_not_auto_clear(tmp_path) -> None:
    p = state_path(str(tmp_path))
    p.parent.mkdir(parents=True)
    p.write_text("garbage")
    assert read_state(str(tmp_path)) is None
    assert p.exists()  # still there for diagnostics; clear_state() removes it


def test_is_clear(tmp_path) -> None:
    assert is_clear(str(tmp_path)) is True
    write_state(str(tmp_path), 1234, str(tmp_path / "r"), "2026-01-01_0000",
                "2026-01-01T00:00:00Z")
    assert is_clear(str(tmp_path)) is False
    clear_state(str(tmp_path))
    assert is_clear(str(tmp_path)) is True


def test_clear_state(tmp_path) -> None:
    p = state_path(str(tmp_path))
    write_state(str(tmp_path), 1234, str(tmp_path / "r"), "2026-01-01_0000",
                "2026-01-01T00:00:00Z")
    assert p.is_file()
    clear_state(str(tmp_path))
    assert not p.exists()
    assert not (tmp_path / ".state").exists()
    # clearing again is a no-op
    clear_state(str(tmp_path))
    # unrelated files in .state keep the dir
    (tmp_path / ".state").mkdir()
    (tmp_path / ".state" / "other.json").write_text("{}")
    clear_state(str(tmp_path))
    assert (tmp_path / ".state").is_dir()
    assert (tmp_path / ".state" / "other.json").exists()


def test_is_stale() -> None:
    dead = 2**31 - 1  # 2147483647 — no sane process uses this PID
    assert is_stale(RecordingState(1, dead, "/x", "s", "t")) is True
    assert is_stale(RecordingState(1, os.getpid(), "/x", "s", "t")) is False


def test_write_is_overwrite_and_no_leftover_temp(tmp_path) -> None:
    d = state_dir(str(tmp_path))
    write_state(str(tmp_path), 1, str(tmp_path / "a"), "2026-01-01_0000", "t1")
    time.sleep(1.1)  # new minute → new stamp, so overwrite is visible
    write_state(str(tmp_path), 2, str(tmp_path / "b"), "2026-01-01_0001", "t2")
    s = read_state(str(tmp_path))
    assert s is not None and s.pid == 2 and s.out_dir.endswith("/b")
    leftovers = [f for f in d.iterdir() if f.name != "recording.json"]
    assert leftovers == []
