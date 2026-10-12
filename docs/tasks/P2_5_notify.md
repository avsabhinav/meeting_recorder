TASK: P2.5 Add osascript completion notification on `stop`/`toggle`

GOAL: When `mr stop` (or `mr toggle` in its stop path) finishes transcribing and writes the
transcript, post a macOS **notification** via `osascript` so the user knows the meeting is
processed. Add a focused helper `notify_complete(stamp, md_path)` in `mr/cli.py`, call it once
after a successful stop, keep it fully testable offline (mock the subprocess call), and make it
fail softly if `osascript` is unavailable.

CONTEXT:
- Repo: `meeting recorder/` (space in path — quote paths).
- `mr/cli.py` already has `stop` (`_do_stop`) and `toggle` (`_do_stop` is shared) that write the
  transcript via `_transcribe_and_write` → returns the `.md` `Path`, prints `wrote {md}`, clears
  state. This task hooks a notification call right after the successful write (only when the
  transcript was actually produced — not on "not recording", not when `ModelNotCachedError` exits 3).
- macOS notification via `osascript` (no extra deps, per PLAN.md §4.5 "osascript notification")
  using the standard SNH `display notification` idiom:
  ```
  osascript -e 'display notification "<text>" with title "mr"'
  ```
- Requirements:
  - A helper `notify_complete(stamp: str, md_path: Path) -> bool` that builds a short message
    (e.g. `Typed up "<stamp>" → <filename>` or `Recording <stamp> transcribed`) and runs
    `subprocess.run(["osascript", "-e", f'display notification "{title}" with title "mr"'])`.
    Returns True on success (returncode 0), False otherwise (e.g. osascript missing / non-zero).
  - It MUST be safe when `osascript` is absent or the notification is denied: catch `FileNotFoundError`
    and return False; never raise.
  - Escape the message so quotes/backslashes in the stamp/path cannot break the AppleScript string
    (simple approach: replace `"` with `\"`).
  - The STOP path should call it only after the transcript is written AND state cleared (i.e. after
    the existing `typer.echo(f"wrote {md}")`), and the result is not critical to exit code — the
    command still exits 0 whether or not the notification posts.
- Testability: expose `notify_complete` as module-level in `mr.cli` so tests can monkeypatch
  `subprocess.run` and assert it was invoked with an osascript invocation, and that it returns
  False when `subprocess.run` raises `FileNotFoundError`.

FILES (modify/create only):
- `mr/cli.py` (EDIT — add `notify_complete` helper + wire into the stop path once)
- `tests/test_notify_complete.py` (CREATE — or add to the existing
  `tests/test_cli_start_stop_toggle_status_doctor.py`; prefer a small dedicated file only if it
  fits, otherwise append to that file)

READ FIRST:
1. `mr/cli.py` — `stop`/`toggle`/`_do_stop` (lines ~160-197, 291-311) to see exactly where to
   hook `notify_complete`. The transcript path is the `md` variable in `_do_stop`.
2. `tests/test_cli_start_stop_toggle_status_doctor.py` — conventions (fixtures, monkeypatch of
   `mr.cli.*`, CliRunner). Reuse `_make_active_state` / `_fake_transcribe_and_write` patterns.

STEPS:
1. In `mr/cli.py`, add a module-level helper `notify_complete(stamp: str, md_path: Path) -> bool`:
   ```python
   def notify_complete(stamp: str, md_path: Path) -> bool:
       """Post a macOS notification via osascript; return True on success."""
       msg = f'Recording "{stamp}" transcribed -> {md_path.name}'
       msg = msg.replace('"', '\\"')
       try:
           r = subprocess.run(
               ["osascript", "-e", f'display notification "{msg}" with title "mr"'],
               capture_output=True, timeout=10,
           )
           return r.returncode == 0
       except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
           return False
   ```
   (Adjust the message wording/types to be clean and ruff-clean. `Path` is already imported.)
2. In `_do_stop`, after the existing `typer.echo(f"wrote {md}")` line (and after `clear_state`),
   add: `notify_complete(state.stamp, md)` — ignore its return value (fail-soft). Ensure it is NOT
   called on the "not recording" path or the `ModelNotCachedError` path.
3. Write tests (append to `tests/test_cli_start_stop_toggle_status_doctor.py` or a new file):
   - `test_notify_complete_success(monkeypatch)`: monkeypatch `subprocess.run` to a Mock returning
     returncode 0; call `notify_complete("s1", Path("/x/transcripts/s1.md"))` → True; assert
     `subprocess.run` was called with an args list starting with `"osascript"` and containing
     `-e` and a string starting with `display notification`.
   - `test_notify_complete_missing_osascript`: monkeypatch `subprocess.run` to raise
     `FileNotFoundError` → returns False (no raise).
   - `test_stop_posts_notification_on_success`: extend `test_stop_happy` (or add) using the same
     fake state + fake transcribe, monkeypatch `notify_complete` to a spy; run `stop`; assert the
     spy was called once with `(stamp, md_path)`.
   - `test_stop_does_not_notify_when_not_recording`: `read_state`→None; run `stop`; assert the
     notify spy was NOT called.
   - ~3-4 tests.
4. Run suite + ruff.

ACCEPTANCE:
- `./spike/.venv/bin/python -m pytest tests/ -q` — all pass (existing 92 + new).
- `./spike/.venv/bin/ruff check mr/cli.py tests/` — clean.
- `./spike/.venv/bin/python -c "from mr.cli import notify_complete; print(notify_complete('x', __import__('pathlib').Path('/tmp/x.md')))"`
  — on this Mac returns True (osascript exists) or False (if denied); either way NO exception and
  prints `True`/`False`.
- No new dependencies. The `stop` help and behavior otherwise unchanged (exit 0 stays 0).

OUT OF SCOPE:
- Do NOT change the transcript-writing or state-clearing logic.
- Do NOT make the notification required/blocking. Do NOT add toast/UI beyond the osascript call.
- Do NOT modify `mr/core/*`, `mr/config.py`, `mr/state.py`, pyproject.toml, or `process`.
- Do NOT commit (CTO agent owns git).

REPORT: reply with STATUS, FILES CHANGED, VERIFICATION (commands + output), NOTES.