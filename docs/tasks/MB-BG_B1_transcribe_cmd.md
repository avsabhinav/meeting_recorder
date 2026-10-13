TASK: MB-BG/B1 Add an internal `mr _transcribe` subcommand that performs the synchronized background transcription (transcribe + merge + write + notify + heartbeat)
GOAL: Provide a standalone, runnable transcription worker as a hidden `mr` subcommand. `mr _transcribe <stamp> <out_dir> [--json]` writes the transcription heartbeat, transcribes both WAVs, writes `transcripts/<stamp>.md` (+ optional JSON), clears the heartbeat (always, via finally), and posts a completion notification. This is the code path the detached background job (task B2) will invoke; it must mirror the transcription logic currently inline in `_do_stop`.
CONTEXT: Repo root `/Users/abhinavademmagari/Documents/Projects/meeting recorder` (note the space). In `mr/cli.py`, the transcription work currently lives inside `_do_stop` (lines ~180-235): write heartbeat → `_transcribe_and_write(...)` → clear heartbeat in `finally` → optional WAV cleanup → clear state → `notify_complete`. B1 moves the pure transcription portion into a new hidden `_transcribe` command so a detached process (spawned by B2) can run it independent of the `mr stop` that detaches it. Reuse existing helpers exactly: `_transcribe_and_write`, `write_transcribing_heartbeat`, `clear_transcribing_heartbeat`, `notify_complete`, `ModelNotCachedError` — do not reimplement them. The timestamp helper already used in `_do_stop` is `datetime.now(UTC).isoformat().replace("+00:00", "Z")`.
FILES: create/modify ONLY `mr/cli.py`, `tests/test_cli_start_stop_toggle_status_doctor.py`
READ FIRST: `mr/cli.py` lines 82-114 (`_transcribe_and_write`), 180-235 (`_do_stop` — the transcription section to port), 44 (`write/clear_transcribing_heartbeat` imports), 161-177 (`notify_complete`). Then `mr/heartbeat.py` lines 56-93 (write/clear). Then `tests/test_cli_start_stop_toggle_status_doctor.py` lines 369-428 (heartbeat tests for stop) as style reference.
STEPS:
1. Add a private helper `_transcribe_worker(cfg: Config, stamp: str, out_dir: str, *, json_sidecar: bool = False) -> Path | None` in the "Private helpers" section that does the FULL worker sequence (this will be shared by `_do_stop`'s old inline code and the new command, but do NOT change `_do_stop` yet — that is B2):
   ```python
   def _transcribe_worker(cfg, stamp, out_dir, *, json_sidecar=False):
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
   ```
2. Add a hidden command under `# Commands` (place it near `process`), decorated so it does NOT appear in `mr --help` and its name starts with underscore. It loads config and calls the worker + notification:
   ```python
   @app.command(hidden=True, name="_transcribe")
   def transcribe_worker(
       stamp: Annotated[str, typer.Argument(...)],
       out_dir: Annotated[str, typer.Argument(...)],
       json: Annotated[bool, typer.Option("--json", ...)] = False,
   ) -> None:
       cfg = load_config()
       md = _transcribe_worker(cfg, stamp, out_dir, json_sidecar=json)
       typer.echo(f"wrote {md}")
       notify_complete(stamp, md)  # fail-soft
   ```
   Match the exact typer call style of the other commands (see `process`/`stop` for `Annotated[...]` Option usage). The underscore-prefixed name + `hidden=True` keeps it out of help.
3. Do NOT modify `_do_stop` at all in B1. The goal is only to ADD the worker helper + the hidden command + their tests. `_do_stop` keeps its current inline transcription until task B2 rewrites the stop flow to spawn this command in the background.
ACCEPTANCE:
1. `mr _transcribe` works without a live capture: unit tests prove `_transcribe_worker` writes the heartbeat during transcription, writes the `.md`, clears the heartbeat afterwards, and (when `keep_audio=False`) removes the WAVs.
2. Add tests in `tests/test_cli_start_stop_toggle_status_doctor.py`: (a) `test_transcribe_worker_writes_and_clears_heartbeat` using the existing `_fake_transcribe_and_write` pattern to assert heartbeat present DURING transcription and cleared after; (b) `test_transcribe_worker_model_not_cached_clears_heartbeat` mirroring `test_stop_clears_heartbeat_on_model_not_cached` (exit 3, heartbeat cleared); (c) `test_transcribe_worker_removes_wavs_when_keep_audio_false`. Existing `_do_stop` tests must STILL pass unchanged (stop is not reworked yet in B1).
3. `cd "meeting recorder" && ./spike/.venv/bin/python -m pytest tests/ -q` → green (existing + new). `./spike/.venv/bin/ruff check mr tests` → clean.
4. `git diff` touches ONLY `mr/cli.py` and `tests/test_cli_start_stop_toggle_status_doctor.py`.
OUT OF SCOPE: making `mr stop` async (task B2), Swift menu-bar, README/docs (B3), `mr/core/*`, changing `_transcribe_and_write`/`notify_complete`/heartbeat modules, reworking `_do_stop`'s stop/signal/clear-state flow.
REPORT: reply with STATUS, FILES CHANGED, VERIFICATION (pytest tail + ruff + a snippet of the new `_transcribe_worker` and the `_transcribe` command), and NOTES.