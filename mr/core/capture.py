"""Python wrapper around the ``mr-capture`` recording helper.

Phase 1: drives the spike-built ``mr-capture`` binary (Swift, macOS-only) so the
pipeline can be exercised end-to-end before P2.1 productionizes capture.

Binary contract (see ``spike/SPIKE_RESULTS.md``):
``mr-capture --out <dir>`` records until it receives SIGINT or
SIGTERM, then writes ``mic.wav`` / ``system.wav`` (16 kHz mono s16le) and
``meta.json`` into ``<dir>`` and exits 0.

Stdlib only; imports nothing that pulls in mlx_whisper or typer.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
from dataclasses import dataclass
from pathlib import Path

from mr.core.schema import CaptureMeta, from_capture_dict

#: Repo root (this file lives at <root>/mr/core/capture.py).
_MR_ROOT = Path(__file__).resolve().parent.parent.parent

#: Default location of the spike-built binary (absolute, anchored at the repo root).
DEFAULT_CAPTURE_BIN = str(_MR_ROOT / "capture" / ".build" / "release" / "mr-capture")

#: Env var override for the binary location (P2.1 will point this at the real build).
BIN_ENV_VAR = "MR_CAPTURE_BIN"


def assert_capture_bin() -> str:
    """Resolve the ``mr-capture`` binary path and verify it is usable.

    Uses ``MR_CAPTURE_BIN`` if set, otherwise :data:`DEFAULT_CAPTURE_BIN`.
    Raises ``FileNotFoundError`` with a helpful message if the binary is
    missing or not executable.
    """
    path = os.environ.get(BIN_ENV_VAR) or DEFAULT_CAPTURE_BIN
    if not os.path.isfile(path) or not os.access(path, os.X_OK):
        raise FileNotFoundError(
            f"mr-capture binary not found or not executable: {path!r} "
            "(install mr-capture (MR_CAPTURE_BIN) or build the Swift package)"
        )
    return path


@dataclass(frozen=True)
class CaptureResult:
    """Outcome of a finished :class:`RecordSession`.

    ``meta`` is ``None`` if ``meta.json`` is missing or invalid.
    """

    out_dir: str  # absolute path
    meta: CaptureMeta | None
    returncode: int


class RecordSession:
    """Context manager that spawns ``mr-capture`` and reaps it on exit.

    Usage::

        with RecordSession("out/rec1") as session:
            ...  # record; Ctrl-C or SIGTERM ends capture gracefully

        session.returncode  # int exit status of the child
        session.meta        # CaptureMeta | None, parsed from meta.json
        session.result()    # CaptureResult(out_dir, meta, returncode)

    KeyboardInterrupt and other exceptions propagate unchanged after the child
    is signalled and waited on (``__exit__`` returns ``False``).
    """

    def __init__(
        self,
        out_dir: str,
        *,
        capture_bin: str | None = None,
    ) -> None:
        self.out_dir = str(Path(out_dir).resolve())
        self.capture_bin = capture_bin
        self.proc: subprocess.Popen[bytes] | None = None
        self.meta: CaptureMeta | None = None
        self.returncode: int = -1

    def __enter__(self) -> RecordSession:
        if self.capture_bin is not None:
            bin_path = self.capture_bin
            if not (os.path.isfile(bin_path) and os.access(bin_path, os.X_OK)):
                raise FileNotFoundError(
                    f"mr-capture binary not found or not executable: {bin_path!r} "
                    "(install mr-capture (MR_CAPTURE_BIN) or build the Swift package)"
                )
        else:
            bin_path = assert_capture_bin()
        os.makedirs(self.out_dir, exist_ok=True)
        cmd = [bin_path, "--out", self.out_dir]
        self.proc = subprocess.Popen(cmd)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: object,
    ) -> bool:
        assert self.proc is not None
        if self.proc.poll() is None:
            sig = signal.SIGINT if exc_type is KeyboardInterrupt else signal.SIGTERM
            try:
                os.kill(self.proc.pid, sig)
            except ProcessLookupError:
                pass  # child already gone between poll() and kill()
        self.returncode = self.proc.wait()
        self.meta = self._read_meta()
        return False  # never swallow the exception (e.g. KeyboardInterrupt)

    def _read_meta(self) -> CaptureMeta | None:
        try:
            with open(os.path.join(self.out_dir, "meta.json"), encoding="utf-8") as f:
                d = json.load(f)
            return from_capture_dict(d)
        except (OSError, ValueError):
            # meta.json missing, unreadable, malformed, or missing stream keys.
            return None

    def result(self) -> CaptureResult:
        """Snapshot the finished session as a :class:`CaptureResult`."""
        return CaptureResult(
            out_dir=self.out_dir,
            meta=self.meta,
            returncode=self.returncode,
        )
