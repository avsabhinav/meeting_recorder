# MB-PY6 — `mr stop` must clear the pid when the recording files are gone, not crash

## TASK: MB-PY6 — Make `_do_stop` clear state when the recording files are missing (no traceback)

**GOAL:** When the recording pidfile exists but the recorded WAV files are gone (deleted by the user, or the capture crashed before flushing), `mr stop` must NOT crash with a `LibsndfileError` traceback. It should clear the pidfile and finish cleanly with a short "nothing to transcribe" note.

**CONTEXT:**

The user deleted the recording files for a leftover session (`~/Documents/Meetings mr/recordings/2026-10-12_2038/mic.wav`, `system.wav`, `meta.json` were removed) but a stale pidfile still points at that session. Running `mr stop` then crashed:

```
LibsndfileError: Error opening '.../recordings/2026-10-12_2038/mic.wav': System error.
```

Root cause: `_do_stop` in `mr/cli.py` unconditionally calls `_transcribe_and_write(...)`, which → `transcribe_audio` → `sf.read(...)` raises an uncaught `soundfile.LibsndfileError` when a WAV is missing. The pidfile is never cleared, so every subsequent `mr stop` errors the same way.

Current `_do_stop` (mr/cli.py lines 180-225):

```python
def _do_stop(cfg: Config, json_sidecar: bool) -> None:
    state = read_state(cfg.out_root)
    if state is None:
        typer.echo("not recording")
        return

    if not is_stale(state):
        try:
            os.kill(state.pid, signal.SIGINT)
        except ProcessLookupError:
            pass
        # Give the helper up to ~15 s to flush its WAVs + meta.json.
        needed = ("mic.wav", "system.wav", "meta.json")
        deadline = time.monotonic() + 15.0
        while time.monotonic() < deadline and not all(
            (Path(state.out_dir) / name).is_file() for name in needed
        ):
            time.sleep(0.25)

    utc_now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    write_transcribing_heartbeat(cfg.out_root, state.stamp, utc_now)
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
    notify_complete(state.stamp, md)
```

`clear_state`, `read_state`, `is_stale` are imported from `mr.state` (already at the top of `mr/cli.py`). `_transcribe_and_write` only needs the two WAVs (`mic.wav`, `system.wav`); it does not need `meta.json`.

**Intended new behaviour:** Add a guard AFTER the signal/flush-wait block and BEFORE the heartbeat/transcribe step. If the recording is not transcribable — the recording directory `state.out_dir` no longer exists, OR either of `mic.wav`/`system.wav` is missing — then the recorded files are gone: clear the pidfile, print a short clean note, and return. Do not write the transcribing heartbeat, do not attempt transcription, do not raise.

Suggested shape (right after the `if not is_stale(state): ... while ...` block, before `utc_now = ...`):

```python
    out_path = Path(state.out_dir)
    if not out_path.is_dir() or not all(
        (out_path / name).is_file() for name in ("mic.wav", "system.wav")
    ):
        # Recorded files are gone (deleted, or a crash before they flushed):
        # nothing to transcribe — clear the stale pid and finish cleanly.
        clear_state(cfg.out_root)
        typer.echo(f"recorded files missing for {state.stamp}; cleared stale recording state")
        return
```

Preserve the existing `ModelNotCachedError` path exactly: when the WAVs ARE present but the model is not cached, state is deliberately LEFT in place (exit 3) so `mr stop` can be retried. The new guard must only trigger when files are actually missing.

**FILES:**
- `mr/cli.py` (only `_do_stop`)
- `tests/test_cli_start_stop_toggle_status_doctor.py` (only the `stop`/`toggle` tests area)

**READ FIRST:**
- `mr/cli.py` lines 180-225 (`_do_stop`; `clear_state`/`read_state`/`is_stale` imported at line 45)
- `tests/test_cli_start_stop_toggle_status_doctor.py` lines 121-127 (`_make_active_state` helper: creates `mic.wav`/`system.wav`/`meta.json`) and lines 140-173 (`test_stop_happy`, `test_stop_model_not_cached_keeps_state`)

**STEPS:**
1. Edit `_do_stop`: insert the guard described above immediately after the `if not is_stale(state): ... while ...` flush-wait block and before `utc_now = datetime.now(UTC)...`.
2. Keep everything else in `_do_stop` unchanged (the `ModelNotCachedError` exit-3 path and `clear_transcribing_heartbeat` in `finally`).
3. Add a new test `test_stop_missing_files_clears_state_without_transcribing` (mirroring `test_stop_happy`): build a state whose `out_dir` exists as a directory but contains NO `mic.wav`/`system.wav` (create the dir only). Monkeypatch `mr.cli.read_state` to return it and `mr.cli.clear_state` to record the call. Monkeypatch `mr.cli._transcribe_and_write` to a lambda that appends to a list and returns `Path("/never")` so you can assert it is NOT called. Invoke `runner.invoke(app, ["stop"])`. Assert:
   - exit_code == 0 and no traceback in output,
   - cleared == [cfg.out_root] (state cleared),
   - the transcribe fake was NOT called (list still empty),
   - output contains the "missing"/"cleared" message you wrote (match a stable substring, e.g. "missing").
4. Also assert in the same (or a sibling) test that nothing is posted to `notify_complete` (monkeypatch it to record calls; assert empty) — no notification when nothing was transcribed.

**ACCEPTANCE:**
- `./spike/.venv/bin/python -m pytest tests/test_cli_start_stop_toggle_status_doctor.py -q` → all pass.
- `./spike/.venv/bin/python -m pytest tests/ -q` → 137 pass (136 existing + 1 new).
- `./spike/.venv/bin/ruff check mr tests` → clean.

**OUT OF SCOPE:**
- Do NOT change `clear_state`/`read_state`/`is_stale`/`is_clear` in `mr/state.py`, or `toggle`.
- Do NOT alter the `ModelNotCachedError` exit-3 behaviour (state kept when files are present but model uncached) — keep it fully intact.
- Do NOT change `status()`, any other command, or the Swift app.
- Do NOT over-engineer partial-recovery or corrupt-file handling: only the "files missing" case is in scope.
- No dependency upgrades, refactors, renames, or formatting of untouched code.

**REPORT:** Reply with STATUS (done/failed), FILES CHANGED, VERIFICATION (the commands above and their output), and NOTES.
