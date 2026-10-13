TASK: MB-BG/B2 Rework `_do_stop` so `mr stop` stops the capture, clears state, and returns immediately while transcription runs in a detached background process
GOAL: `mr stop` (and `mr toggle` when stopping) must no longer block until transcription finishes. It signals the capture, waits briefly for the WAVs to flush, clears the recording state, spawns the (already-added, hidden) `mr _transcribe` command as a DETACHED background process, and returns in ~1-2 s. Transcription then runs in the background; the user can immediately start a new recording (back-to-back/long meetings). The background job owns the transcription heartbeat and completion notification (B1).
CONTEXT: Repo root `/Users/abhinavademmagari/Documents/Projects/meeting recorder` (note the space). B1 already added `_transcribe_worker` + the hidden `mr _transcribe <stamp> <out_dir> [--json]` command in `mr/cli.py`. Now rework `_do_stop` (currently lines ~180-235) from its synchronous "signal → transcribe → write → clear → notify" flow into a fast "signal → flush → clear state → spawn detached background transcription → return". The existing helpers `_spawn_capture` (now stdio-detached), `is_stale`, `read_state`, `clear_state`, `new_stamp` are all in `mr/state.py` / `mr/cli.py`. `sys` is imported at top of `cli.py`.
FILES: create/modify ONLY `mr/cli.py`, `tests/test_cli_start_stop_toggle_status_doctor.py`
READ FIRST: `mr/cli.py` lines 168-235 (`_do_stop` full body), 220 (`ModelNotCachedError` import), 356-375 (`stop`/`toggle` commands), 408-435 (`main`, config_app). Then `mr/state.py` `clear_state` (line 157) and `mr/heartbeat.py` `write/clear_transcribing_heartbeat` (lines 56-93). Then `tests/test_cli_start_stop_toggle_status_doctor.py` lines 129-251 (stop/toggle tests that will need updating) and 201-215 (`test_stop_model_not_cached_keeps_state`).
STEPS:
1. Add a private helper `_spawn_transcription(stamp: str, out_dir: str, *, json_sidecar: bool = False) -> bool` near `_spawn_capture` that spawns the DETACHED background transcription and returns True if spawned, False on error:
   ```python
   def _spawn_transcription(stamp: str, out_dir: str, *, json_sidecar: bool = False) -> bool:
       """Spawn ``mr _transcribe`` as a detached background process (MB-BG).

       The worker outlives this CLI process (own session, stdio discarded) and
       owns the transcription heartbeat + completion notification. Returns
       True if the child was spawned, False if spawning failed.
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
   ```
2. Rewrite `_do_stop(cfg, json_sidecar)`:
   - Read state; if None → `typer.echo("not recording")`; return (unchanged).
   - If not stale: `os.kill(state.pid, signal.SIGINT)` (guarded by ProcessLookupError); wait up to 15 s for `mic.wav`/`system.wav`/`meta.json` (the current `while time.monotonic() < deadline ...` loop) — UNCHANGED.
   - If files are missing → `clear_state(cfg.out_root)` + `typer.echo("recorded files missing for <stamp>; cleared stale recording state")`; return (unchanged).
   - Spawn the background transcription: `spawned = _spawn_transcription(state.stamp, state.out_dir, json_sidecar=json_sidecar)`.
   - `clear_state(cfg.out_root)` (clear REGARDLESS of spawn result, so a new recording is always possible).
   - Echo: if `spawned`: `typer.echo(f"stopped recording {state.stamp} — transcribing in the background")`. If not spawned: `typer.echo("stopped recording; error: could not start background transcription", err=True)`.
   - Do NOT write or clear the heartbeat here (the background `_transcribe` job owns it), and do NOT call `notify_complete` here (the worker does). Remove the heartbeat/`notify_complete`/WAV-cleanup code from `_do_stop` — that responsibility moved to `_transcribe_worker` (B1).
   - Keep the `keep_audio` behavior: the background `_transcribe_worker` already removes WAVs when `cfg.keep_audio` is False, so `_do_stop` no longer does it.
   - Update `_do_stop`'s docstring to describe the new async flow and note that ModelNotCachedError is now handled by the background worker (exit 3 there), not by `mr stop`.
3. Update the `stop` command docstring (line ~361) and `toggle` docstring (line ~367) to say transcription continues in the background and `mr stop` returns immediately.
ACCEPTANCE:
1. `_do_stop` no longer calls `_transcribe_and_write` and no longer calls `notify_complete`/`write_transcribing_heartbeat`/`clear_transcribing_heartbeat` inline. Grep `mr/cli.py` `_do_stop` body: it calls `_spawn_transcription`, `clear_state`, and returns; the transcription/timeout-path (exit 3 on model-not-cached) has been removed from `_do_stop`.
2. Update existing Python tests to the new async contract and add coverage:
   - `test_stop_happy`: after stop, state is cleared, the capture PID was signalled, `_spawn_transcription` WAS called with the right stamp/out_dir, output contains "transcribing in the background", and NO `_transcribe_and_write`/`notify_complete` call. Patch `_spawn_transcription` to record args and return True. Remove the `wrote transcripts/s1.md` assertion (no longer produced synchronously) — instead assert the `.md` is NOT created by stop.
   - `test_stop_missing_files_clears_state_without_transcribing`: unchanged intent — patch `_spawn_transcription` to assert it is NOT called when files are missing.
   - `test_stop_model_not_cached_keeps_state`: REWRITE. With async stop the model is no longer pre-checked in `_do_stop`; this test should become `test_stop_spawns_background_transcription`: patch `_spawn_transcription` (records args, returns True), patch `_spawn_transcription` NOT to check the model, assert stop exits 0, clears state, and does not call `_transcribe_and_write`. (The model-not-cached exit-3 behaviour is now covered by the B1 `_transcribe_worker` tests.)
   - `test_stop_writes_heartbeat_during_transcription`, `test_stop_clears_heartbeat_on_model_not_cached`, `test_stop_posts_notification_on_success`, `test_stop_does_not_notify_on_model_not_cached`: these asserted synchronous-stop heartbeat/notification behavior. REWRITE/REPLACE to the new contract: stop does NOT write a heartbeat and does NOT post a notification (those belong to the worker). For example `test_stop_does_not_write_heartbeat_or_notify`: patch heartbeat writes + `notify_complete` + `_spawn_transcription`; assert none called by `_do_stop`. (The B1 `_transcribe_worker` tests already cover heartbeat+notify in the worker.)
   - Add `test_spawn_transcription_detached`: patch `subprocess.Popen` to record kwargs and return a stub; call `_spawn_transcription("s1", "/tmp/out", json_sidecar=True)`; assert argv == `[ANY, "-m", "mr.cli", "_transcribe", "s1", "/tmp/out", "--json"]`, `stdin is DEVNULL`, `stdout is DEVNULL`, `stderr is DEVNULL`, `start_new_session is True`, returns True. And a failure variant where `Popen` raises `OSError` → returns False.
   - Keep `test_toggle_active_stops` consistent: patch `_spawn_transcription` (return True) and assert output/clear; remove the `wrote` + notification assertions that no longer hold.
   - `test_stop_not_recording` (line 129), `test_stop_does_not_notify_when_not_recording` unchanged (they test the "not recording" early return).
3. `cd "meeting recorder" && ./spike/.venv/bin/python -m pytest tests/ -q` → green. `./spike/.venv/bin/ruff check mr tests` → clean.
4. `git diff` touches ONLY `mr/cli.py` and `tests/test_cli_start_stop_toggle_status_doctor.py`.
OUT OF SCOPE: Swift menu-bar, README/docs (B3), `mr/state.py`/`mr/heartbeat.py`/`mr/core/*`, changing `_transcribe_worker`/`_transcribe` (B1), changing `_spawn_capture`, adding daemon/service infra.
REPORT: reply with STATUS, FILES CHANGED, VERIFICATION (pytest tail + ruff + the final `_do_stop` body + a snippet of `_spawn_transcription`), and NOTES.