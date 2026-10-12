"""Recording state (pidfile) for meeting-recorder.

The CLI owns recording state via a small JSON "pidfile" at
``<out_root>/.state/recording.json`` (see ``docs/architecture.md`` §6 and
``PLAN.md`` §5). This module is pure and offline: no process spawning, no
config loading, no CLI — only file I/O plus an ``os.kill(pid, 0)`` liveness
probe for stale detection (single-user macOS, no ``/proc``).

Writes are atomic: a temp file in the same directory is ``os.replace``d over
the state path (best-effort ``fsync``), so readers never see a partial file.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

#: Bumped if the JSON schema changes.
STATE_VERSION = 1

#: Fixed filename inside the ``.state`` directory.
STATE_FILENAME = "recording.json"

#: Directory name (relative to ``out_root``) holding recording state.
STATE_DIRNAME = ".state"


@dataclass(frozen=True)
class RecordingState:
    """The currently-active (or last-seen) capture, as recorded in the pidfile.

    ``out_dir`` is the absolute path of the recording directory (wavs +
    ``meta.json``); ``stamp`` is the local ``YYYY-MM-DD_HHMM`` used to name it.
    """

    version: int
    pid: int
    out_dir: str
    stamp: str
    started_at: str  # ISO8601


def state_dir(out_root: str) -> Path:
    """Directory holding recording state: ``<out_root>/.state``."""
    return Path(out_root) / STATE_DIRNAME


def state_path(out_root: str) -> Path:
    """Path of the pidfile: ``<out_root>/.state/recording.json``."""
    return state_dir(out_root) / STATE_FILENAME


def new_stamp() -> str:
    """A fresh local-time stamp, e.g. ``2026-08-24_1432`` (``YYYY-MM-DD_HHMM``)."""
    return datetime.now().strftime("%Y-%m-%d_%H%M")


def _atomic_write(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` atomically (temp file + ``os.replace``)."""
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())  # best-effort durability before the rename
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def write_state(
    out_root: str, pid: int, out_dir: str, stamp: str, started_at: str
) -> None:
    """Record an active capture: mkdir ``.state`` + atomically write the pidfile.

    Overwrites any existing state (a new capture replaces the old one).
    """
    d = state_dir(out_root)
    d.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": STATE_VERSION,
        "pid": pid,
        "out_dir": out_dir,
        "stamp": stamp,
        "started_at": started_at,
    }
    _atomic_write(state_path(out_root), json.dumps(payload, indent=2) + "\n")


def read_state(out_root: str) -> RecordingState | None:
    """Read the pidfile, or ``None`` if missing/malformed/version mismatch.

    Never auto-clears: a stale file is reported via :func:`is_stale` and
    removed explicitly via :func:`clear_state`.
    """
    try:
        raw = state_path(out_root).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or data.get("version") != STATE_VERSION:
        return None
    pid, out_dir, stamp, started_at = (
        data.get("pid"),
        data.get("out_dir"),
        data.get("stamp"),
        data.get("started_at"),
    )
    if not isinstance(pid, int) or isinstance(pid, bool):
        return None
    if not isinstance(out_dir, str) or not isinstance(stamp, str):
        return None
    if not isinstance(started_at, str):
        return None
    return RecordingState(
        version=STATE_VERSION,
        pid=pid,
        out_dir=out_dir,
        stamp=stamp,
        started_at=started_at,
    )


def is_clear(out_root: str) -> bool:
    """``True`` if there is no state file (nothing recorded / nothing to stop)."""
    return not state_path(out_root).exists()


def is_stale(state: RecordingState) -> bool:
    """``True`` if the recorded PID no longer exists.

    Uses ``os.kill(pid, 0)`` (probe only, no signal sent): a
    ``ProcessLookupError`` means the process is gone → stale. Any other
    outcome (including ``PermissionError``) is treated conservatively as
    "still alive".
    """
    try:
        os.kill(state.pid, 0)
    except ProcessLookupError:
        return True
    except OSError:
        return False
    return False


def clear_state(out_root: str) -> None:
    """Remove the pidfile (and, if now empty, the ``.state`` dir; best-effort)."""
    d = state_dir(out_root)
    try:
        state_path(out_root).unlink(missing_ok=True)
    except OSError:
        pass
    try:
        d.rmdir()  # succeeds only if empty
    except OSError:
        pass
