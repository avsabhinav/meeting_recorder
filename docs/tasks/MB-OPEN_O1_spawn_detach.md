TASK: MB-OPEN/O1 Detach `mr-capture` stdio in `_spawn_capture` so `mr start` no longer holds the pipe open
GOAL: Make `mr start` return promptly from the menu-bar app's perspective. The long-lived `mr-capture` helper must NOT inherit `mr start`'s standard streams, so the pipe the menu-bar reads (`readDataToEndOfFile`) closes the moment `mr start` exits — ending the main-thread block that kept the dropdown from opening while recording.
CONTEXT: In `mr/cli.py`, `_do_start` (which `mr start` and `mr toggle` call) invokes `_spawn_capture(out_dir, binary)`. Today `_spawn_capture` does `subprocess.Popen([binary, "--out", out_dir])` with NO stdio redirection. The child therefore inherits the parent CLI's stdout/stderr file descriptors. When the menu-bar app runs `mr start` via its `ProcessRunner` (which connects the CLI process stdout to a pipe and blocks on `readDataToEndOfFile()`), the SPIKE is: `mr start` exits, but `mr-capture` — the long-lived child — still holds the write end of that pipe open, so `readDataToEndOfFile()` keeps blocking for the ENTIRE recording (until `mr-capture` exits). That wedges the menu-bar main thread. The fix belongs in Python: detach the child's stdio. Your working directory is the repo root `/Users/abhinavademmagari/Documents/Projects/meeting recorder` (note the space).
FILES: create/modify ONLY `mr/cli.py`, `tests/test_cli_start_stop_toggle_status_doctor.py`
READ FIRST: `mr/cli.py` lines 61-69 (`_spawn_capture`) and 143-158 (`_do_start`). Then `tests/test_cli_start_stop_toggle_status_doctor.py` line 44 (`test_start_happy` patches `_spawn_capture`) — that patch stays valid.
STEPS:
1. In `mr/cli.py`, change `_spawn_capture` to open a per-session log file and pass it as the child's `stdout` and `stderr`, AND pass `start_new_session=True` (full process-session detach). Specifically, before `Popen`, compute `log_path = Path(out_dir) / ".capture.log"` (reuse the already-created `out_dir`; `out_dir` is an absolute path equal to `_recordings_dir` / stamp, already mkdir'd by `_do_start`). Open it in `"a"`-append mode (so a re-spawn into the same dir wouldn't truncate). Then:
   ```python
   def _spawn_capture(out_dir: str, binary: str, log_path: Path | None = None) -> int:
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
   ```
   Keep the same signature behaviour for callers (`_do_start` passes `(str(out_dir), binary)` — that still works because `log_path` defaults). Provide the optional `log_path` param so tests can point at a tmp path, but do NOT require callers to change. Ensure `out_dir` exists before `open(...)` (it does: `_do_start` mkdir's it first). Close the Python-side file handle immediately after `Popen` so `mr start` does not itself hold the fd.
   - IMPORTANT: do not change the `RecordSession` class in `mr/core/capture.py` — out of scope. Only the CLI's `_spawn_capture`.
2. Update the `_spawn_capture` docstring briefly to state that the child's stdio is redirected to `<out_dir>/.capture.log` and it is detached with `start_new_session=True`, so `mr start` never blocks on the child's pipes.
3. In `tests/test_cli_start_stop_toggle_status_doctor.py`, add ONE new test `test_spawn_capture_detaches_stdio(cfg, tmp_path, monkeypatch)` that verifies the child process is spawned with `stdout`/`stderr` as (opened) file objects (not inherited/piped) and `start_new_session=True`. Approach: monkeypatch `subprocess.Popen` to record `kwargs` and return a stub object with `.pid = 5566`; call `mr.cli._spawn_capture(str(tmp_path), "/x/mr-capture")`; assert `kwargs["start_new_session"] is True`, `kwargs["stdout"] is kwargs["stderr"]`, and the child got a file handle (assert it has `.fileno()` and reads as text). Also assert a `.capture.log` content placeholder is not required. Keep the existing `test_start_happy` (which monkeypatches `_spawn_capture`) unchanged.
ACCEPTANCE:
1. `_spawn_capture` passes `stdout=`/`stderr=` (the log file) and `start_new_session=True` to `subprocess.Popen` — verified by the new test and by reading the diff.
2. `cd "meeting recorder" && ./spike/.venv/bin/python -m pytest tests/ -q` → all green (existing + the new test), no failures.
3. `./spike/.venv/bin/ruff check mr tests` → clean.
4. `git diff` touches ONLY `mr/cli.py` and `tests/test_cli_start_stop_toggle_status_doctor.py` and shows only the intended additions.
OUT OF SCOPE: `mr/core/capture.py` (`RecordSession`), the Swift `mrBar` (task O2), `_do_stop`/transcription behaviour (epic MB-BG), README/docs, reformatting unrelated lines, dependency changes.
REPORT: reply with STATUS, FILES CHANGED, VERIFICATION (pytest tail + ruff result + the `_spawn_capture` diff hunk), and NOTES.