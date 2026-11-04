"""Transcription heartbeat for meeting-recorder.

While ``mr stop`` is transcribing, the CLI records a small JSON heartbeat at
``<out_root>/.state/transcribing.json`` (see ``docs/architecture.md`` §6). The
menu-bar app reads this file (lazily, on dropdown open) to show a
"Transcribing…" section; a crashed transcription therefore must not linger
forever — :func:`read_transcribing_heartbeat` treats a heartbeat older than
``max_age_seconds`` as effectively absent (stale sweep) but does not delete it.

Version 2 of the payload adds a ``pid`` field: the PID of the worker process
that owns the heartbeat, so ``mr stop-transcribe`` can signal exactly that
process, and a worker starting after a cancelled predecessor can clear the
stale heartbeat by PID.

This is a DIFFERENT file from the recording pidfile (``recording.json``, see
:mod:`mr.state`); both live in the same ``.state`` directory. Writes are
atomic: a temp file in the same directory is ``os.replace``d over the target
(best-effort ``fsync``), so readers never see a partial file.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

#: Bumped if the JSON schema changes.
HEARTBEAT_VERSION = 2

#: Fixed filename inside the ``.state`` directory.
HEARTBEAT_FILENAME = "transcribing.json"

#: Default staleness bound: a heartbeat older than this is treated as absent.
DEFAULT_MAX_AGE_SECONDS = 300.0


def heartbeat_path(out_root: str) -> Path:
    """Path of the heartbeat file: ``<out_root>/.state/transcribing.json``."""
    return Path(out_root) / ".state" / HEARTBEAT_FILENAME


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


def write_transcribing_heartbeat(
    out_root: str, stamp: str, started_at: str, pid: int | None = None
) -> None:
    """Record "transcribing session ``stamp``": mkdir ``.state`` + atomic write.

    Overwrites any existing heartbeat (a new transcription replaces the old
    one). ``started_at`` is an ISO8601 timestamp — the caller should pass a
    UTC-aware, ``Z``-suffixed value (e.g. ``datetime.now(UTC).isoformat()``
    with ``+00:00``→``Z``) so the Swift ``ISO8601DateFormatter`` (which
    requires a zone) can parse it. ``pid`` is the owning worker PID: what
    ``mr stop-transcribe`` signals and what a later worker's clear matches on.
    """
    path = heartbeat_path(out_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": HEARTBEAT_VERSION,
        "stamp": stamp,
        "out_root": str(Path(out_root).resolve()),
        "started_at": started_at,
        # Owning worker PID: what `mr stop-transcribe` signals. Recorded by the
        # worker itself (whoever holds the heartbeat is who must be killed).
        "pid": pid,
        # Liveness: refreshed by the worker (see touch_transcribing_heartbeat).
        # Staleness is judged from this, not started_at, so a long run is not
        # reported idle after DEFAULT_MAX_AGE_SECONDS.
        "updated_at": started_at,
    }
    _atomic_write(path, json.dumps(payload, indent=2) + "\n")


def _utc_now_z() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def touch_transcribing_heartbeat(
    out_root: str, stamp: str, pid: int | None = None, *, now: str | None = None
) -> bool:
    """Refresh ``updated_at`` of the heartbeat owned by ``stamp``/``pid``.

    Only rewrites a heartbeat whose stamp matches (and whose pid matches, when
    ``pid`` is given), so a dying worker never revives a heartbeat a newer
    worker owns, and a cleared heartbeat is never recreated. Returns ``True``
    if the file was refreshed. Never raises.
    """
    path = heartbeat_path(out_root)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return False
    if not isinstance(data, dict) or data.get("stamp") != stamp:
        return False
    if pid is not None and data.get("pid") != pid:
        return False
    data["updated_at"] = now or _utc_now_z()
    try:
        _atomic_write(path, json.dumps(data, indent=2) + "\n")
    except OSError:
        return False
    return True


def clear_transcribing_heartbeat(out_root: str, stamp: str, pid: int | None = None) -> None:
    """Remove the heartbeat file — only if it exists AND its stamp or PID matches.

    Missing file is a no-op; a heartbeat for a DIFFERENT stamp (and a
    different PID, when ``pid`` is supplied) is left in place (two concurrent
    transcriptions of different sessions must not clobber each other's clear).

    Matching on ``pid`` handles the race where a cancelled worker's ``finally``
    runs *after* a freshly spawned worker (a re-transcribe or a new stop) has
    already written a new heartbeat for the SAME stamp: the PID match lets the
    dying worker still clean up after itself instead of leaving a heartbeat
    that reports "transcribing…" for the full staleness window.
    """
    path = heartbeat_path(out_root)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return
    if not isinstance(data, dict):
        return
    matches_stamp = data.get("stamp") == stamp
    matches_pid = (
        pid is not None
        and isinstance(data.get("pid"), int)
        and not isinstance(data.get("pid"), bool)
        and data.get("pid") == pid
    )
    if matches_stamp or matches_pid:
        try:
            path.unlink()
        except OSError:
            pass


def read_transcribing_heartbeat(
    out_root: str, *, max_age_seconds: float = DEFAULT_MAX_AGE_SECONDS
) -> dict | None:
    """Return the fresh heartbeat dict, or ``None`` if absent/stale/invalid.

    ``None`` when: the file is missing, is malformed JSON, has the wrong
    version, or the liveness timestamp is unparseable or older than
    ``max_age_seconds`` (stale). The liveness timestamp is ``updated_at`` when
    present (refreshed by the worker), else ``started_at`` (older writers). A
    stale file is treated as absent but NOT deleted here.
    """
    path = heartbeat_path(out_root)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict) or data.get("version") != HEARTBEAT_VERSION:
        return None
    stamp = data.get("stamp")
    out_root_val = data.get("out_root")
    started_at = data.get("started_at")
    if not isinstance(stamp, str) or not isinstance(out_root_val, str):
        return None
    if not isinstance(started_at, str):
        return None
    updated_at = data.get("updated_at")
    live_at = updated_at if isinstance(updated_at, str) else started_at
    # py<3.11 cannot parse a trailing 'Z'; 3.12 can. Normalize for both.
    ts = live_at
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    try:
        started = datetime.fromisoformat(ts)
    except ValueError:
        return None
    now = datetime.now(UTC if started.tzinfo is not None else None)
    if (now - started).total_seconds() > max_age_seconds:
        return None
    return data
