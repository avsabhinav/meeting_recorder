"""`mr` command-line interface (typer app).

Exposes the full captured pipeline from the terminal:

- ``process``: transcribe an existing ``--mic``/``--system`` WAV pair and
  write the attributed Markdown transcript (plus optional JSON sidecar).
- ``start``: spawn ``mr-capture`` (long-lived; outlives this command) and
  record the pidfile state.
- ``status``: is a capture active? plus the most recent transcript.
- ``stop``: SIGINT the capture, wait briefly for its WAVs, clear state,
  and spawn ``mr _transcribe`` as a detached background process
  (transcription + notification happen after ``mr stop`` returns).
- ``toggle``: start if idle/stale, else stop.
- ``doctor``: environment check (macOS version, helper binary, model cache);
  ``--fetch-model`` pre-downloads the Whisper model.

The long-lived spawn in ``start`` deliberately does NOT use
``RecordSession`` (its ``__exit__`` reaps/signals the child); instead the
binary is spawned via ``subprocess.Popen`` and only the PID is persisted.
"""

from __future__ import annotations

import json
import os
import platform
import signal
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer

from mr.config import Config, load_config, set_out_root
from mr.core.capture import assert_capture_bin
from mr.core.merge import merge_transcripts
from mr.core.output import (
    render_transcript_json,
    render_transcript_md,
    write_json,
    write_transcript,
)
from mr.core.transcribe import DEFAULT_MODEL, ModelNotCachedError, transcribe_audio
from mr.heartbeat import clear_transcribing_heartbeat, write_transcribing_heartbeat
from mr.state import clear_state, is_clear, is_stale, new_stamp, read_state, write_state

app = typer.Typer(help="Local-first meeting recorder: capture and transcribe 1:1 calls.")


@app.callback()
def _root() -> None:
    """Keep the app multi-command (typer collapses single-command apps)."""
    return None


# ---------------------------------------------------------------------------
# Private helpers (shared by the start/stop/toggle commands; monkeypatchable)
# ---------------------------------------------------------------------------


def _spawn_capture(out_dir: str, binary: str, log_path: Path | None = None) -> int:
    """Spawn the (long-lived) ``mr-capture`` helper and return its PID.

    The child must outlive this short-lived CLI process, so it is started
    with ``subprocess.Popen`` and not reaped here; the PID is persisted to
    the state pidfile by the caller.

    The child's stdio is redirected to ``<out_dir>/.capture.log`` and the
    process is detached with ``start_new_session=True``, so ``mr start``
    never blocks on the child's pipes (a menu-bar app reading ``mr start``'s
    stdout sees EOF as soon as ``mr start`` exits, even though
    ``mr-capture`` keeps running).
    """
    log_path = log_path or (Path(out_dir) / ".capture.log")
    log_fh = open(log_path, "a", encoding="utf-8")
    p = subprocess.Popen(
        [binary, "--out", out_dir],
        stdout=log_fh,
        stderr=log_fh,
        start_new_session=True,
    )
    log_fh.close()  # Popen dup'd the fd into the child
    return p.pid


def _spawn_transcription(stamp: str, out_dir: str, *, json_sidecar: bool = False) -> bool:
    """Spawn ``mr _transcribe`` as a detached background process (MB-BG/B2).

    The child runs in its own session (``start_new_session=True``) with all
    stdio discarded, so it outlives this short-lived CLI and ``mr stop``
    returns immediately. The worker owns the transcription heartbeat and the
    completion notification. Returns ``True`` if the process was spawned.
    """
    args = [sys.executable, "-m", "mr.cli", "_transcribe", stamp, out_dir]
    if json_sidecar:
        args.append("--json")
    try:
        subprocess.Popen(
            args,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError:
        return False
    return True


def _recordings_dir(cfg: Config) -> Path:
    """Root directory holding per-session recording dirs."""
    return Path(cfg.out_root) / "recordings"


def _transcripts_dir(cfg: Config) -> Path:
    """Directory holding the final ``<stamp>.md`` transcripts."""
    return Path(cfg.out_root) / "transcripts"


def _system_vs_mic_offset(out_dir: str) -> float | None:
    """Seconds by which the system (speaker) stream lags the mic stream's start,
    from meta.json (mic.first_sample_seconds vs system.first_sample_seconds).
    None when meta.json is missing/unparseable or lacks the fields."""
    try:
        meta = json.loads((Path(out_dir) / "meta.json").read_text(encoding="utf-8"))
        m, s = meta["mic"], meta["system"]
        return float(s["first_sample_seconds"]) - float(m["first_sample_seconds"])
    except (OSError, KeyError, ValueError, TypeError):
        return None


def _transcribe_and_write(
    cfg: Config, stamp: str, out_dir: str, *, json_sidecar: bool = False
) -> Path:
    """Transcribe both WAVs in ``out_dir``, merge, and write the transcript.

    Returns the path of the written ``transcripts/<stamp>.md``.
    Raises :class:`~mr.core.transcribe.ModelNotCachedError` when the model
    is not cached (callers decide the exit code / state handling).
    """
    o = Path(out_dir)
    you = transcribe_audio(
        str(o / "mic.wav"), speaker="You", model=cfg.model, language=cfg.language
    )
    them = transcribe_audio(
        str(o / "system.wav"), speaker="Them", model=cfg.model, language=cfg.language
    )
    echo_lag = _system_vs_mic_offset(out_dir)
    merged = merge_transcripts(
        list(you.segments),
        list(them.segments),
        dedup_threshold=cfg.dedup_threshold,
        echo_lag_s=echo_lag,
    )
    duration = max((s.end for s in list(you.segments) + list(them.segments)), default=0.0)
    md_path = _transcripts_dir(cfg) / f"{stamp}.md"
    write_transcript(
        md_path,
        render_transcript_md(
            stamp=stamp,
            source_dir=f"recordings/{stamp}",
            segments=merged,
            duration_seconds=duration,
        ),
    )
    if json_sidecar:
        write_json(md_path.with_suffix(".json"), render_transcript_json(merged, stamp=stamp))
    return md_path


def _transcribe_worker(
    cfg: Config, stamp: str, out_dir: str, *, json_sidecar: bool = False
) -> Path:
    """Transcribe ``out_dir`` with a heartbeat around it (MB-BG background worker).

    Writes the transcription heartbeat, transcribes + writes
    ``transcripts/<stamp>.md`` (plus optional JSON sidecar), and clears the
    heartbeat in ``finally`` — so the success path AND the
    :class:`~mr.core.transcribe.ModelNotCachedError` path (exit 3) remove it.
    When ``cfg.keep_audio`` is false the WAVs are deleted afterwards.
    """
    utc_now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    write_transcribing_heartbeat(cfg.out_root, stamp, utc_now)
    try:
        md = _transcribe_and_write(cfg, stamp, out_dir, json_sidecar=json_sidecar)
    except ModelNotCachedError as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(code=3) from e
    finally:
        clear_transcribing_heartbeat(cfg.out_root, stamp)

    if not cfg.keep_audio:
        for name in ("mic.wav", "system.wav"):
            (Path(out_dir) / name).unlink(missing_ok=True)

    return md


def _fetch_model(model: str) -> None:
    """Download ``model`` into the standard HF hub cache (network allowed).

    ``huggingface_hub`` is imported lazily, only on this path.
    """
    import huggingface_hub  # lazy: only used with `doctor --fetch-model`

    huggingface_hub.snapshot_download(repo_id=model)


def _model_cached(model: str) -> bool:
    """Best-effort check that ``model`` is present in the local HF cache.

    Prefers ``huggingface_hub.scan_cache_dir`` (guarded import); falls back
    to checking for ``models--<repo with '/'→'--'>`` under
    ``~/.cache/huggingface/hub`` when the package is absent.
    """
    try:
        from huggingface_hub import scan_cache_dir

        return any(repo.repo_id == model for repo in scan_cache_dir().repos)
    except ImportError:
        repo_dir = "models--" + model.replace("/", "--")
        return (Path.home() / ".cache" / "huggingface" / "hub" / repo_dir).is_dir()


def _do_start(cfg: Config, context_json: Path | None = None) -> None:
    """Start a capture (shared by ``start`` and ``toggle``).

    ``context_json`` is an optional path to a JSON file (title/attendees/
    notes) whose raw text is persisted as ``meeting_context.json`` inside the
    freshly-created recording dir, so a later transcription step can read it.
    """
    if not is_clear(cfg.out_root):
        state = read_state(cfg.out_root)
        stamp = state.stamp if state is not None else "?"
        out_dir = state.out_dir if state is not None else "?"
        typer.echo(f"already recording (stamp {stamp}, out_dir {out_dir})")
        return

    stamp = new_stamp()
    out_dir = _recordings_dir(cfg) / stamp
    out_dir.mkdir(parents=True, exist_ok=True)
    if context_json is not None:
        msg = f"--context-json file not found or invalid: {context_json}"
        try:
            raw = context_json.read_text(encoding="utf-8")
        except OSError as e:
            raise typer.BadParameter(msg) from e
        try:
            json.loads(raw)
        except json.JSONDecodeError as e:
            raise typer.BadParameter(msg) from e
        (out_dir / "meeting_context.json").write_text(raw, encoding="utf-8")
    binary = assert_capture_bin()
    pid = _spawn_capture(str(out_dir), binary)
    write_state(cfg.out_root, pid, str(out_dir), stamp, datetime.now().isoformat())
    typer.echo(f"recording started (stamp {stamp})\nout_dir: {out_dir}")


def notify_complete(stamp: str, md_path: Path) -> bool:
    """Post a macOS completion notification via ``osascript`` (fail-soft).

    Returns ``True`` when the notification was posted (``osascript`` exited
    0), ``False`` otherwise (binary missing, timeout, OS error). Never
    raises — a notification is never blocking or required.
    """
    msg = f'Recording "{stamp}" transcribed -> {md_path.name}'.replace('"', '\\"')
    try:
        proc = subprocess.run(
            ["osascript", "-e", f'display notification "{msg}" with title "mr"'],
            capture_output=True,
            timeout=10,
        )
        return proc.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


def _do_stop(cfg: Config, json_sidecar: bool) -> None:
    """Stop the capture, clear state, and transcribe in the background.

    Shared by ``stop`` and ``toggle``. Signals ``mr-capture`` (SIGINT),
    waits briefly for its WAVs to flush, clears the recording state, spawns
    the hidden ``mr _transcribe`` worker as a detached background process,
    and returns immediately (~1-2 s). The background worker owns the
    transcription heartbeat and the completion notification; on
    :class:`ModelNotCachedError` it exits with code 3, while ``mr stop``
    itself stays exit 0 so a new recording can start right away.
    """
    state = read_state(cfg.out_root)
    if state is None:
        typer.echo("not recording")
        return

    if not is_stale(state):
        try:
            os.kill(state.pid, signal.SIGINT)
        except ProcessLookupError:
            pass  # child already gone between is_stale() and kill()
        # Give the helper up to ~15 s to flush its WAVs + meta.json.
        needed = ("mic.wav", "system.wav", "meta.json")
        deadline = time.monotonic() + 15.0
        while time.monotonic() < deadline and not all(
            (Path(state.out_dir) / name).is_file() for name in needed
        ):
            time.sleep(0.25)

    out_path = Path(state.out_dir)
    if not out_path.is_dir() or not all(
        (out_path / name).is_file() for name in ("mic.wav", "system.wav")
    ):
        # Recorded files are gone (deleted, or a crash before they flushed):
        # nothing to transcribe — clear the stale pid and finish cleanly.
        clear_state(cfg.out_root)
        typer.echo(f"recorded files missing for {state.stamp}; cleared stale recording state")
        return

    # Transcription runs in a detached background process: the worker owns
    # the heartbeat and the completion notification (and exits 3 on
    # ModelNotCachedError), so this command never blocks on it.
    spawned = _spawn_transcription(state.stamp, state.out_dir, json_sidecar=json_sidecar)
    # Clear state ALWAYS — a new recording must be possible even if the
    # background spawn failed.
    clear_state(cfg.out_root)
    if spawned:
        typer.echo(f"stopped recording {state.stamp} — transcribing in the background")
    else:
        typer.echo("stopped recording; error: could not start background transcription", err=True)


def _do_config_set(key: str, value: str) -> None:
    """Apply ``config set <key> <value>`` (v1.1: only ``out_root``).

    Raises :class:`typer.BadParameter` for an unsupported key or an invalid
    value (typer reports it and exits 2).
    """
    if key != "out_root":
        raise typer.BadParameter(f"unsupported config key: {key!r}")
    try:
        new_root = set_out_root(value)
    except ValueError as e:
        raise typer.BadParameter(str(e)) from e
    typer.echo(f"out_root: {new_root}")


def _do_config_get(key: str) -> None:
    """Print ``config get <key>`` (v1.1: only ``out_root``).

    Raises :class:`typer.BadParameter` for an unsupported key (typer reports
    it and exits 2).
    """
    if key != "out_root":
        raise typer.BadParameter(f"unsupported config key: {key!r}")
    cfg = load_config()
    typer.echo(cfg.out_root)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


@app.command()
def process(
    mic: Annotated[Path, typer.Option("--mic", help="You-side 16 kHz mono mic WAV")],
    system: Annotated[
        Path, typer.Option("--system", help="Them-side 16 kHz mono system WAV")
    ],
    model: Annotated[str, typer.Option(help="HF model id")] = DEFAULT_MODEL,
    language: Annotated[str, typer.Option(help="Language code")] = "en",
    dedup_threshold: Annotated[
        float, typer.Option("--dedup-threshold", min=0.0, max=1.0)
    ] = 0.6,
    json: Annotated[bool, typer.Option("--json", help="Also write a JSON sidecar")] = False,
    stamp: Annotated[str, typer.Option(help="Stamp/label for the transcript")] = "",
    out_dir: Annotated[
        Path | None, typer.Option("--out-dir", help="Directory for transcript.md/json")
    ] = None,
) -> None:
    """Transcribe both WAVs, merge with echo dedup, and write the transcript."""
    for label, path in (("--mic", mic), ("--system", system)):
        if not path.is_file():
            raise typer.BadParameter(f"{label} file not found: {path}")

    try:
        you = transcribe_audio(str(mic), speaker="You", model=model, language=language)
        them = transcribe_audio(str(system), speaker="Them", model=model, language=language)
    except ModelNotCachedError as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(code=3) from e

    merged = merge_transcripts(
        list(you.segments), list(them.segments), dedup_threshold=dedup_threshold
    )
    duration = max((s.end for s in list(you.segments) + list(them.segments)), default=0.0)

    out = out_dir or system.parent
    stamp = stamp or system.stem
    md_path = out / f"{stamp}.md"
    write_transcript(
        md_path,
        render_transcript_md(
            stamp=stamp,
            source_dir=f"recordings/{stamp}",
            segments=merged,
            duration_seconds=duration,
        ),
    )
    typer.echo(f"wrote {md_path}")
    if json:
        json_path = out / f"{stamp}.json"
        write_json(json_path, render_transcript_json(merged, stamp=stamp))
        typer.echo(f"wrote {json_path}")
    typer.echo(f"kept {len(merged)} segments")


@app.command(hidden=True, name="_transcribe")
def transcribe_worker(
    stamp: Annotated[str, typer.Argument(help="Recording stamp (folder name)")],
    out_dir: Annotated[str, typer.Argument(help="Recording dir holding mic.wav/system.wav")],
    json: Annotated[bool, typer.Option("--json", help="Also write a JSON sidecar")] = False,
) -> None:
    """Internal: transcribe a recording dir in the background (MB-BG)."""
    cfg = load_config()
    md = _transcribe_worker(cfg, stamp, out_dir, json_sidecar=json)
    typer.echo(f"wrote {md}")
    notify_complete(stamp, md)  # fail-soft; never blocks or raises


@app.command()
def start(
    context_json: Annotated[
        Path | None,
        typer.Option(
            "--context-json",
            help=(
                "JSON file with meeting context (title/attendees/notes) "
                "to persist with this recording"
            ),
        ),
    ] = None,
) -> None:
    """Start recording (spawns ``mr-capture``; it keeps running after exit)."""
    _do_start(load_config(), context_json=context_json)


@app.command()
def status() -> None:
    """Show whether a capture is active and the most recent transcript."""
    cfg = load_config()
    state = read_state(cfg.out_root)
    if state is None:
        typer.echo("recording: no")
    else:
        recording = not is_stale(state)
        typer.echo(f"recording: {'yes' if recording else 'no'}")
        typer.echo(f"pid: {state.pid}")
        typer.echo(f"out_dir: {state.out_dir}")
        typer.echo(f"stamp: {state.stamp}")
        typer.echo(f"started_at: {state.started_at}")
        if not recording:
            typer.echo("stale pidfile; run `mr stop` to clear", err=True)
    tdir = _transcripts_dir(cfg)
    if tdir.is_dir():
        mds = sorted(tdir.glob("*.md"), key=lambda p: (p.stat().st_mtime, p.name))
        if mds:
            typer.echo(f"last transcript: {mds[-1]}")
        else:
            typer.echo("no transcript yet")
    else:
        typer.echo("no transcript yet")


@app.command()
def stop(
    json: Annotated[bool, typer.Option("--json", help="Also write a JSON sidecar")] = False,
) -> None:
    """Stop the capture and transcribe it in the background.

    Returns immediately (~1-2 s): transcription continues in a detached
    background process and posts a completion notification when done.
    """
    _do_stop(load_config(), json)


@app.command()
def toggle(
    json: Annotated[bool, typer.Option("--json", help="JSON sidecar when stopping")] = False,
) -> None:
    """Start recording if idle, otherwise stop it (transcribing in the background)."""
    cfg = load_config()
    state = read_state(cfg.out_root)
    if state is None or is_clear(cfg.out_root) or is_stale(state):
        _do_start(cfg)
    else:
        _do_stop(cfg, json)


@app.command()
def doctor(
    fetch_model: Annotated[
        bool, typer.Option("--fetch-model", help="Download the model if not cached")
    ] = False,
) -> None:
    """Check the environment: macOS version, helper binary, model cache."""
    cfg = load_config()
    typer.echo(f"macOS: {platform.mac_ver()[0] or platform.platform()}")
    typer.echo(f"out_root: {cfg.out_root}")
    try:
        typer.echo(f"helper: {assert_capture_bin()}")
    except FileNotFoundError:
        typer.echo("helper: MISSING (build capture/ or set MR_CAPTURE_BIN)")
    typer.echo(f"model: {cfg.model}")
    cached = _model_cached(cfg.model)
    typer.echo(f"model cached: {'yes' if cached else 'no'}")

    if fetch_model:
        if cached:
            typer.echo("already cached")
        else:
            try:
                _fetch_model(cfg.model)
            except Exception as e:  # network / HF errors — report, exit non-zero
                typer.echo(f"error: failed to fetch model {cfg.model}: {e}", err=True)
                raise typer.Exit(code=1) from e
            typer.echo(f"fetched {cfg.model}")


config_app = typer.Typer(help="Inspect or update mr configuration.")
app.add_typer(config_app, name="config")


@config_app.command("set")
def config_set(
    key: Annotated[str, typer.Argument(help="Config key (v1.1: out_root)")],
    value: Annotated[str, typer.Argument(help="New value")],
) -> None:
    """Set a config value (v1.1: ``mr config set out_root <dir>``)."""
    _do_config_set(key, value)


@config_app.command("get")
def config_get(
    key: Annotated[str, typer.Argument(help="Config key (v1.1: out_root)")],
) -> None:
    """Print the current value of a config key (v1.1: out_root)."""
    _do_config_get(key)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
