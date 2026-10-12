"""Tests for mr.heartbeat: write/clear/read of the transcription heartbeat."""

from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from mr.heartbeat import (
    HEARTBEAT_FILENAME,
    HEARTBEAT_VERSION,
    clear_transcribing_heartbeat,
    heartbeat_path,
    read_transcribing_heartbeat,
    write_transcribing_heartbeat,
)

STAMP = "2026-08-24_1432"


def _fresh_iso() -> str:
    return datetime.now(UTC).isoformat()


def test_heartbeat_path() -> None:
    root = "/tmp/mr-test-root"
    assert heartbeat_path(root) == Path(root) / ".state" / "transcribing.json"
    assert HEARTBEAT_FILENAME == "transcribing.json"
    assert HEARTBEAT_VERSION == 1


def test_write_then_read_roundtrip(tmp_path) -> None:
    write_transcribing_heartbeat(str(tmp_path), STAMP, _fresh_iso())
    p = heartbeat_path(str(tmp_path))
    assert p.is_file()
    assert (tmp_path / ".state").is_dir()
    on_disk = json.loads(p.read_text(encoding="utf-8"))
    assert on_disk == {
        "version": 1,
        "stamp": STAMP,
        "out_root": str(Path(tmp_path).resolve()),
        "started_at": on_disk["started_at"],
    }
    got = read_transcribing_heartbeat(str(tmp_path))
    assert got is not None
    assert got["version"] == 1
    assert got["stamp"] == STAMP
    assert got["out_root"] == str(Path(tmp_path).resolve())
    assert isinstance(got["started_at"], str)


def test_out_root_stored_absolute(tmp_path) -> None:
    # Write with a relative-ish root; the stored out_root must be absolute.
    cwd = os.getcwd()
    try:
        os.chdir(tmp_path.parent)
        root_rel = tmp_path.name
        write_transcribing_heartbeat(root_rel, STAMP, _fresh_iso())
    finally:
        os.chdir(cwd)
    got = read_transcribing_heartbeat(str(tmp_path))
    assert got is not None
    assert Path(got["out_root"]).is_absolute()
    assert got["out_root"] == str(Path(tmp_path).resolve())


def test_clear_matching_stamp_removes(tmp_path) -> None:
    write_transcribing_heartbeat(str(tmp_path), STAMP, _fresh_iso())
    assert heartbeat_path(str(tmp_path)).is_file()
    clear_transcribing_heartbeat(str(tmp_path), STAMP)
    assert not heartbeat_path(str(tmp_path)).exists()


def test_clear_non_matching_stamp_leaves_file(tmp_path) -> None:
    write_transcribing_heartbeat(str(tmp_path), STAMP, _fresh_iso())
    clear_transcribing_heartbeat(str(tmp_path), "different-stamp")
    assert heartbeat_path(str(tmp_path)).is_file()
    got = read_transcribing_heartbeat(str(tmp_path))
    assert got is not None and got["stamp"] == STAMP


def test_clear_missing_file_is_noop(tmp_path) -> None:
    clear_transcribing_heartbeat(str(tmp_path), STAMP)  # must not raise
    assert not heartbeat_path(str(tmp_path)).exists()


def test_read_missing_returns_none(tmp_path) -> None:
    assert read_transcribing_heartbeat(str(tmp_path)) is None


def test_read_malformed_json_returns_none(tmp_path) -> None:
    d = tmp_path / ".state"
    d.mkdir()
    (d / "transcribing.json").write_text("this is not json {", encoding="utf-8")
    assert read_transcribing_heartbeat(str(tmp_path)) is None


def test_read_wrong_version_returns_none(tmp_path) -> None:
    d = tmp_path / ".state"
    d.mkdir()
    (d / "transcribing.json").write_text(
        json.dumps(
            {
                "version": 999,
                "stamp": STAMP,
                "out_root": str(tmp_path),
                "started_at": _fresh_iso(),
            }
        ),
        encoding="utf-8",
    )
    assert read_transcribing_heartbeat(str(tmp_path)) is None


def test_read_stale_returns_none_but_file_kept(tmp_path) -> None:
    old = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
    write_transcribing_heartbeat(str(tmp_path), STAMP, old)
    assert heartbeat_path(str(tmp_path)).is_file()
    # Default max_age (300 s): a 2 h old heartbeat is stale -> None.
    assert read_transcribing_heartbeat(str(tmp_path)) is None
    # Explicitly with a tiny max_age it is stale too; file is NOT deleted here.
    assert read_transcribing_heartbeat(str(tmp_path), max_age_seconds=1.0) is None
    assert heartbeat_path(str(tmp_path)).is_file()


def test_read_fresh_with_small_max_age(tmp_path) -> None:
    write_transcribing_heartbeat(str(tmp_path), STAMP, _fresh_iso())
    # Custom small max_age: a just-written heartbeat is fresh -> returned.
    got = read_transcribing_heartbeat(str(tmp_path), max_age_seconds=1.0)
    assert got is not None and got["stamp"] == STAMP
    # ...but one second old is stale under max_age=1.0 (with a 1.2 s sleep).
    time.sleep(1.2)
    assert read_transcribing_heartbeat(str(tmp_path), max_age_seconds=1.0) is None


def test_read_unparseable_started_at_returns_none(tmp_path) -> None:
    d = tmp_path / ".state"
    d.mkdir()
    (d / "transcribing.json").write_text(
        json.dumps(
            {
                "version": 1,
                "stamp": STAMP,
                "out_root": str(tmp_path),
                "started_at": "not-a-timestamp",
            }
        ),
        encoding="utf-8",
    )
    assert read_transcribing_heartbeat(str(tmp_path)) is None


def test_write_is_overwrite_and_no_leftover_temp(tmp_path) -> None:
    write_transcribing_heartbeat(str(tmp_path), "s1", _fresh_iso())
    write_transcribing_heartbeat(str(tmp_path), "s2", _fresh_iso())
    d = tmp_path / ".state"
    leftovers = [f.name for f in d.iterdir() if f.name != "transcribing.json"]
    assert leftovers == []
    got = read_transcribing_heartbeat(str(tmp_path))
    assert got is not None and got["stamp"] == "s2"
