"""Transcription heartbeat for meeting-recorder.

While ``mr stop`` is transcribing, the CLI records a small JSON heartbeat at
``<out_root>/.state/transcribing.json`` (see ``docs/architecture.md`` §6). The
menu-bar app reads this file (lazily, on dropdown open) to show a
"Transcribing…" section; a crashed transcription therefore must not linger
forever — :func:`read_transcribing_heartbeat` treats a heartbeat older than
``max_age_seconds`` as effectively absent (stale sweep) but does not delete it.

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
HEARTBEAT_VERSION = 1

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


def write_transcribing_heartbeat(out_root: str, stamp: str, started_at: str) -> None:
    """Record "transcribing session ``stamp``": mkdir ``.state`` + atomic write.

    Overwrites any existing heartbeat (a new transcription replaces the old
    one). ``started_at`` is an ISO8601 timestamp (e.g. ``datetime.now().isoformat()``).
    """
    path = heartbeat_path(out_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": HEARTBEAT_VERSION,
        "stamp": stamp,
        "out_root": str(Path(out_root).resolve()),
        "started_at": started_at,
    }
    _atomic_write(path, json.dumps(payload, indent=2) + "\n")


def clear_transcribing_heartbeat(out_root: str, stamp: str) -> None:
    """Remove the heartbeat file — only if it exists AND its stamp matches.

    Missing file is a no-op; a heartbeat for a DIFFERENT stamp is left in
    place (two concurrent transcriptions of different sessions must not
    clobber each other's clear).
    """
    path = heartbeat_path(out_root)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return
    if isinstance(data, dict) and data.get("stamp") == stamp:
        try:
            path.unlink()
        except OSError:
            pass


def read_transcribing_heartbeat(
    out_root: str, *, max_age_seconds: float = DEFAULT_MAX_AGE_SECONDS
) -> dict | None:
    """Return the fresh heartbeat dict, or ``None`` if absent/stale/invalid.

    ``None`` when: the file is missing, is malformed JSON, has the wrong
    version, or ``started_at`` is unparseable or older than ``max_age_seconds``
    (stale). A stale file is treated as absent but NOT deleted here.
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
    # py<3.11 cannot parse a trailing 'Z'; 3.12 can. Normalize for both.
    ts = started_at
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
