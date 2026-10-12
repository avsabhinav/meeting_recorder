TASK: P2.4 Extend `mr/cli.py` — `start` `stop` `toggle` `status` `doctor`

GOAL: Add four typer subcommands to the existing `mr` CLI so the full captured pipeline is
driven from the terminal: `start` (spawn `mr-capture` via `RecordSession`, write state),
`status` (report whether a capture is active + the last transcript), `stop`/`toggle`
(stop → transcribe → write attributed `.md` → clear state), and `doctor` (report macOS
version, helper binary, model-cache status, out_root; `--fetch-model` pre-downloads the model).
Wire in `mr.config` (`Config`) + `mr.state` (`RecordingState`). Everything testable offline
(mock `RecordSession`, `transcribe_audio`, `osascript`).

CONTEXT:
- Repo: `meeting recorder/` (space in path — quote paths). `typer` 0.27 installed.
- Existing `mr/cli.py` already has: `app = typer.Typer(...)`, an empty `@app.callback()`
  (keeps multi-command), and `process` subcommand (mic/system WAVs → `.md`). `main()` +
  `__main__` guard exist. You ADD commands; do not break `process`.
- Existing modules to import (do not modify any of them):
  - `mr.config`: `Config`, `load_config()` → `.out_root` (absolute str), `.model`, `.language`,
    `.dedup_threshold`, `.keep_audio`.
  - `mr.state`: `RecordingState`, `write_state`, `read_state`, `is_clear`, `is_stale`,
    `clear_state`, `new_stamp`, `state_dir`/`state_path`.
  - `mr.core.capture`: `RecordSession(out_dir, *, aec=True, capture_bin=None)` — context
    manager; `.returncode`, `.meta`, `.result()` (returns `CaptureResult(out_dir, meta, returncode)`).
    Note: `__enter__` raises `FileNotFoundError` if the binary is missing.
  - `mr.core.transcribe`: `transcribe_audio`, `ModelNotCachedError`, `DEFAULT_MODEL`.
  - `mr.core.merge`: `merge_transcripts(you, them, *, dedup_threshold=...)`.
  - `mr.core.output`: `write_transcript`, `render_transcript_md` (stamp/source_dir/segments/
    duration_seconds).
- Recording pipeline (from `docs/architecture.md` §"Pipeline"):
  1. `start`: `stamp = new_stamp()`; `out_dir = f"{cfg.out_root}/recordings/{stamp}"`; spawn
     `RecordSession(str(out_dir), aec=...)`; write state (pid, out_dir, stamp, started_at).
     But: the state file needs the child PID. P1.6 `RecordSession.proc` is set in `__enter__`.
     So: open the recording as a `with RecordSession(...) as sess:` in a `start` command, and
     write the pidfile inside the context using `sess.proc.pid` after `__enter__`. To keep the
     capture running across subcommand invocations, `start` must NOT block inside the `with` —
     it should start the process, write state, and return immediately. Approach: spawn the
     `RecordSession`, then within the same process re-... Actually since `RecordSession` is a CM
     whose lifetime owns the child, you cannot keep it alive after `start` returns unless you
     detach. Use the real process-spawn directly: call `sess.__enter__()` to get `.proc`, write
     state, then keep the *process* alive by NOT exiting — but `start` must return.
   - RESOLUTION (important): `start` should not use `RecordSession` for the long-lived spawn,
     because its `__exit__` reaps/signals. Instead, for `start` just spawn the binary via
     `subprocess.Popen([bin, "--out", out_dir, ...])` directly (reuse `assert_capture_bin()`
     from capture.py) with `start_new_session=False`, record `p.pid` in state, and return.
     `RecordSession` remains the P2.4 `stop` signal helper and the P1.6 integration path. To
     keep ONE authoritative path, define a helper `_spawn_capture(out_dir, cfg) -> int` in
     cli.py using `subprocess.Popen` + `assert_capture_bin()`, and use it from `start`. This is
     the pragmatic, correct design for a process that must outlive the short `start` command.
  2. `status`: read state; print "recording: yes/no", pid, out_dir, stamp; if a stale pidfile
     exists (is_stale), warn and mention `mr stop` clears it. Also print the last transcript:
     scan `cfg.out_root/transcripts/` for the most recent `*.md` and print its path.
  3. `stop`: read state (if none → error "not recording"). Signal the child PID: if alive
     (`is_stale` False), `os.kill(pid, SIGINT)` so `mr-capture` finalizes. Wait for the WAVs +
     meta (poll the recording dir for `mic.wav`/`system.wav`/`meta.json` to appear, timeout ~15 s).
     Then run the transcribe+merge+output pipeline (identical to `process`) on
     `out_dir/mic.wav`, `out_dir/system.wav`, using `cfg` (model/language/dedup_threshold),
     stamp from state, output to `cfg.out_root/transcripts/{stamp}.md` (+ `.json` if keep_audio
     is irrelevant — write `.md` always; JSON only behind `--json`). Then `clear_state(cfg.out_root)`.
     If `keep_audio` is False, remove the raw `mic.wav`/`system.wav` after transcription
     (keep `meta.json` + transcript). On `ModelNotCachedError`, print to stderr + exit 3 (do
     NOT clear state? — decide: keep state so the user can retry; print a clear note).
  4. `toggle`: if `is_clear(cfg.out_root)` (or no live stdev) → `start` behavior; else → `stop`
     behavior. Implement as a thin dispatcher that calls the same internals (share logic, no
     duplication).
  5. `doctor`: print macOS version (`platform.mac_ver()[0]`), out_root (from config), helper
     binary (via `assert_capture_bin()` resolve; catch `FileNotFoundError` → "MISSING"), model
     cache status, and whether the model file exists. `--fetch-model` flag: if set and model not
     cached, call `hf_hub_download`/`snapshot_download` (lazy `import huggingface_hub`) to
     pre-download `cfg.model` into the standard HF cache (network allowed here). Print a clear
     "fetched / already cached" message. If the model IS cached, `--fetch-model` is a no-op
     ("model already cached"). Model-cache check: the HF cache path is
     `~/.cache/huggingface/hub/models--<repo with / → -->`; use `huggingface_hub.scan_cache_dir`
     (guarded import) or a filesystem existence check on that path. Prefer a guarded
     `huggingface_hub` import so `doctor` without `--fetch-model` still works offline and never
     hard-fails if the package is missing (fall back to a path-existence check).
- Exit codes: success 0; usage/error 2 (typer.BadParameter / Exit 2); transcription/model
  error 3; "already recording" for `start` → 0 with message, or 1? Choose 0 + informative
  message for idempotent-friendly behavior. Keep them consistent and document in NOTES.
- Output/notification: the `osascript` completion notification is a SEPARATE task (P2.5). For
  `stop`, just print where the transcript was written (no osascript here).

FILES (create/modify only):
- `mr/cli.py` (EDIT — add commands + helpers)
- `tests/test_cli_start_stop_toggle_status_doctor.py` (create)

READ FIRST:
1. `mr/cli.py` (full) — existing `process`, `app`, callback, imports, style.
2. `mr/state.py` (full) — the state API you call.
3. `mr/config.py` — `Config` fields.
4. `mr/core/capture.py` — `RecordSession` + `assert_capture_bin` + `CaptureResult`.
5. `mr/core/output.py` + `transcribe.py` + `merge.py` — the pipeline helpers (already used by `process`).
6. `tests/test_cli_process.py` — existing CliRunner test conventions (monkeypatch style).

STEPS:
1. Edit `mr/cli.py` to add imports: `import os, platform, subprocess`, `from datetime import datetime`,
   `from pathlib import Path`, `import signal`; keep existing imports. Add `from mr.config import load_config`,
   `from mr.state import (new_stamp, write_state, read_state, is_clear, is_stale, clear_state)`,
   `from mr.core.capture import assert_capture_bin`. Reuse the already-imported transcribe/merge/output.
2. Add a private helper `_spawn_capture(out_dir: str, binary: str, aec: bool) -> int` that does
   `subprocess.Popen([binary, "--out", out_dir] + ([] if aec else ["--no-aec"]))` and returns `p.pid`
   (use `assert_capture_bin()` to resolve `binary`; propagate its `FileNotFoundError`).
   Also a private `_recordings_dir(cfg)` / `_transcripts_dir(cfg)` helper returning Paths.
   And `_write_transcript_file(cfg, stamp, out_dir) -> Path` encapsulating the transcribe→merge→
   write `.md` (+ optional JSON via a `--json` param) used by both `stop` and `toggle`.
3. Add `start` command: `@app.command()` with `--aec` defaulting to `True` (mirror `process`).
   Load config; if `not is_clear(cfg.out_root)` and not stale → echo "already recording" (pid/stamp)
   and exit 0. Else: stamp + out_dir; mkdir; `pid = _spawn_capture(out_dir, cfg, aec)`; write state
   (pid, out_dir, stamp, ISO now); echo "recording started (stamp ..., out_dir ...)". Return immediately.
4. Add `status` command: load config; read state. Echo a few lines: "recording: yes/no"; if yes,
   pid, out_dir, stamp, started_at, stale? (if `is_stale` → warn "stale pidfile; run `mr stop` to
   clear"). Then locate the most recent `*.md` under transcripts dir and print its path (or "no
   transcript yet"). Exit 0.
5. Add `stop` command: load config; `state = read_state(cfg.out_root)`; if None or clear → echo
   "not recording" (+ note if a stale pidfile was just noted), exit 0 or 2 — pick 0 with message.
   If state present and not stale → `os.kill(state.pid, signal.SIGINT)` (guard `ProcessLookupError`).
   Wait (poll up to ~15 s) for `mic.wav`+`system.wav`+`meta.json` in `state.out_dir`. Then
   `_write_transcript_file(cfg, state.stamp, state.out_dir, json=...)`. If `keep_audio` is False,
   remove `mic.wav`/`system.wav` (leave `meta.json`). `clear_state(cfg.out_root)`. Echo transcript path.
   Handle `ModelNotCachedError` from `_write_transcript_file`: stderr message + exit 3, do NOT clear
   state (so retry possible).
6. Add `toggle` command: delegate — if `is_clear(cfg.out_root)` or `read_state(...)` is None/stale →
   call the `start` path; else call the `stop` path. Keep it a thin wrapper (share via a small
   `_do_start()`/`_do_stop()` helper or add `_run_start(cfg)`/`_run_stop(cfg)` functions that both
   the standalone commands and toggle call).
7. Add `doctor` command: `--fetch-model` flag (bool). Load config. Print OS (`platform.mac_ver()[0]`),
   out_root, helper binary (try `assert_capture_bin()` → path or "MISSING"), model id + cache status.
   For cache status use a helper `_model_cached(model) -> bool` that (a) tries `huggingface_hub.scan_cache_dir`
   guarded, else (b) checks `os.path.isdir(hf_cache_path(model))`. `--fetch-model`: if not cached,
   `import huggingface_hub` and `snapshot_download(repo_id=cfg.model)` (allow network), echo "fetched";
   else echo "already cached". Wrap exceptions with a clear message. Keep `--help` and all existing
   subcommands working.
8. Write `tests/test_cli_start_stop_toggle_status_doctor.py` (offline; monkeypatch so no real
   subprocess / no real whisper / no network):
   - Mock `_spawn_capture` (or `subprocess.Popen`) and `write_state` for `start`; assert exit 0,
     state written with pid, "recording started" in output.
   - `start` when already recording (monkeypatch `is_clear`→False, `read_state`→a fake state) →
     "already recording", exit 0, no spawn.
   - `status` idle (monkeypatch read_state→None) → "recording: no".
   - `status` active (fake state) → "recording: yes" + contains pid/stamp.
   - `stop` when not recording → "not recording", exit 0.
   - `stop` happy path: fake state (pid=os.getpid() or a live pid), monkeypatch `os.kill` (record SIGINT),
     create stub `mic.wav/system.wav/meta.json` in a tmp out_dir, monkeypatch `_write_transcript_file`
     to write a real md, monkeypatch `clear_state`; run `stop`; assert SIGINT sent, transcript reported,
     clear_state called.
   - `toggle` idle → behaves like start (spawn called); `toggle` active → behaves like stop (kill + clear).
   - `doctor` offline: monkeypatch `platform.mac_ver`→("14.2.0","","") and `_model_cached`→False and
     `assert_capture_bin`→a path; assert exit 0 and it prints OS + helper + model lines. For
     `--fetch-model`, monkeypatch `snapshot_download` (a stub in cli module) to a fake path; assert
     "fetched" (no real network).
   - ~8-10 tests. Ensure no heavy imports (never import mlx_whisper).
9. Run suite + ruff; fix anything that breaks in existing tests (do not change other tests).

ACCEPTANCE:
- `./spike/.venv/bin/python -m pytest tests/ -q` — all pass (existing 79 + new).
- `./spike/.venv/bin/ruff check mr/cli.py tests/test_cli_start_stop_toggle_status_doctor.py` — clean.
- `./spike/.venv/bin/python -m mr.cli --help` shows commands: process, start, status, stop, toggle, doctor.
- `./spike/.venv/bin/python -m mr.cli start --help` and `doctor --help` render (no crash).
- `./spike/.venv/bin/python -m mr.cli doctor` (offline) runs and prints OS + helper (resolve or MISSING)
  + model lines; if run on this Mac with the helper built it prints the `capture/.build/...` path.
- A full off-the-record `mr status` prints "recording: no" (no state) without error.

OUT OF SCOPE:
- Do NOT implement the osascript completion notification (P2.5). Just print where the transcript is.
- Do NOT modify any `mr/core/*`, `mr/config.py`, `mr/state.py`, `pyproject.toml`, or existing tests.
- Do NOT add new dependencies. Do NOT change the `process` subcommand behavior.
- Do NOT auto-clear state inside `read_state` (P2.3 contract) — clearing is always explicit via
  `clear_state` in `stop`/`toggle`.
- Do NOT commit (CTO agent owns git).

REPORT: reply with STATUS, FILES CHANGED, VERIFICATION (commands + output), NOTES (esp. the exit-code
choices and how `start` keeps the child alive after the command returns).