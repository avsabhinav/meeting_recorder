"""`mr` command-line interface (typer app).

Exposes the full captured pipeline from the terminal:

- ``process``: transcribe an existing ``--mic``/``--system`` WAV pair and
  write the attributed Markdown transcript (plus optional JSON sidecar).
- ``start``: spawn ``mr-capture`` (long-lived; outlives this command) and
  record the pidfile state.
- ``status``: is a capture active? plus the most recent transcript.
- ``stop``: SIGINT the capture, wait for its WAVs, transcribe + merge,
  write ``transcripts/<stamp>.md``, then clear state.
- ``toggle``: start if idle/stale, else stop.
- ``doctor``: environment check (macOS version, helper binary, model cache);
  ``--fetch-model`` pre-downloads the Whisper model.

The long-lived spawn in ``start`` deliberately does NOT use
``RecordSession`` (its ``__exit__`` reaps/signals the child); instead the
binary is spawned via ``subprocess.Popen`` and only the PID is persisted.
"""

from __future__ import annotations

import os
import platform
import signal
import subprocess
import time
from datetime import datetime
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


def _spawn_capture(out_dir: str, binary: str, aec: bool) -> int:
    """Spawn the (long-lived) ``mr-capture`` helper and return its PID.

    The child must outlive this short-lived CLI process, so it is started
    with ``subprocess.Popen`` and not reaped here; the PID is persisted to
    the state pidfile by the caller.
    """
    p = subprocess.Popen([binary, "--out", out_dir] + ([] if aec else ["--no-aec"]))
    return p.pid


def _recordings_dir(cfg: Config) -> Path:
    """Root directory holding per-session recording dirs."""
    return Path(cfg.out_root) / "recordings"


def _transcripts_dir(cfg: Config) -> Path:
    """Directory holding the final ``<stamp>.md`` transcripts."""
    return Path(cfg.out_root) / "transcripts"


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
    merged = merge_transcripts(
        list(you.segments), list(them.segments), dedup_threshold=cfg.dedup_threshold
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


def _do_start(cfg: Config, aec: bool) -> None:
    """Start a capture (shared by ``start`` and ``toggle``)."""
    if not is_clear(cfg.out_root):
        state = read_state(cfg.out_root)
        stamp = state.stamp if state is not None else "?"
        out_dir = state.out_dir if state is not None else "?"
        typer.echo(f"already recording (stamp {stamp}, out_dir {out_dir})")
        return

    stamp = new_stamp()
    out_dir = _recordings_dir(cfg) / stamp
    out_dir.mkdir(parents=True, exist_ok=True)
    binary = assert_capture_bin()
    pid = _spawn_capture(str(out_dir), binary, aec)
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
    """Stop the capture, transcribe, write the transcript, clear state.

    Shared by ``stop`` and ``toggle``. On :class:`ModelNotCachedError` the
    state pidfile is deliberately LEFT in place (exit code 3) so ``mr stop``
    can be retried once the model is cached.
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

    # Heartbeat: visible to the menu-bar app while transcribing; cleared in
    # ``finally`` so both success and the ModelNotCachedError path (exit 3)
    # remove it.
    write_transcribing_heartbeat(cfg.out_root, state.stamp, datetime.now().isoformat())
    try:
        md = _transcribe_and_write(cfg, state.stamp, state.out_dir, json_sidecar=json_sidecar)
    except ModelNotCachedError as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(code=3) from e
    finally:
        clear_transcribing_heartbeat(cfg.out_root, state.stamp)

    if not cfg.keep_audio:
        for name in ("mic.wav", "system.wav"):
            (Path(state.out_dir) / name).unlink(missing_ok=True)

    clear_state(cfg.out_root)
    typer.echo(f"wrote {md}")
    notify_complete(state.stamp, md)  # fail-soft; never blocks or raises


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


@app.command()
def start(
    aec: Annotated[
        bool, typer.Option("--aec/--no-aec", help="Enable AEC on the capture helper")
    ] = True,
) -> None:
    """Start recording (spawns ``mr-capture``; it keeps running after exit)."""
    _do_start(load_config(), aec)


@app.command()
def status() -> None:
    """Show whether a capture is active and the most recent transcript."""
    cfg = load_config()
    state = read_state(cfg.out_root)
    if state is None:
        typer.echo("recording: no")
    else:
        typer.echo("recording: yes")
        typer.echo(f"pid: {state.pid}")
        typer.echo(f"out_dir: {state.out_dir}")
        typer.echo(f"stamp: {state.stamp}")
        typer.echo(f"started_at: {state.started_at}")
        if is_stale(state):
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
    """Stop the capture, transcribe it, and write the attributed transcript."""
    _do_stop(load_config(), json)


@app.command()
def toggle(
    aec: Annotated[bool, typer.Option("--aec/--no-aec", help="AEC when starting")] = True,
    json: Annotated[bool, typer.Option("--json", help="JSON sidecar when stopping")] = False,
) -> None:
    """Start recording if idle, otherwise stop it and write the transcript."""
    cfg = load_config()
    state = read_state(cfg.out_root)
    if state is None or is_clear(cfg.out_root) or is_stale(state):
        _do_start(cfg, aec)
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


def main() -> None:
    app()


if __name__ == "__main__":
    main()
