# MB-SW9 — Fix `mr start failed` from the menu-bar app (CWD-relative helper binary path)

> **Root cause of a real user bug.** The menu-bar app reports "mr start failed."
> while the same command from the repo-root terminal succeeds. `DEFAULT_CAPTURE_BIN`
> is a **CWD-relative** path (`capture/.build/release/mr-capture`); macOS launches
> the `.app` bundle from a working directory that is NOT the repo root, so the
> helper resolves to nothing → `assert_capture_bin()` raises `FileNotFoundError` →
> typer exits 1 with the traceback on **stderr** (which the Swift app swallows) →
> empty stdout → the app shows "mr start failed.". Fix: make the default binary
> path absolute, anchored to the repo root, so resolution never depends on the
> process working directory.

## GOAL
`mr start` (and `mr stop`/transcribe, `doctor`, `RecordSession`) resolve the
`mr-capture` helper regardless of the working directory, so the menu-bar `.app`
can start a recording from any launch CWD.

## CONTEXT
- File: `mr/core/capture.py` (Python). Lines ~26-45:
  ```python
  DEFAULT_CAPTURE_BIN = "capture/.build/release/mr-capture"

  BIN_ENV_VAR = "MR_CAPTURE_BIN"

  def assert_capture_bin() -> str:
      path = os.environ.get(BIN_ENV_VAR) or DEFAULT_CAPTURE_BIN
      if not os.path.isfile(path) or not os.access(path, os.X_OK):
          raise FileNotFoundError(...)
      return path
  ```
- Repo layout: `mr/core/capture.py` → `Path(__file__).resolve().parent.parent.parent` is the repo root (`…/meeting recorder`), and the helper lives at `<repo>/capture/.build/release/mr-capture` (verified present).
- The `MR_CAPTURE_BIN` env override must keep working unchanged (callers may pass absolute or relative; that's their explicit choice — do not modify that branch's semantics).

## FILES
- `mr/core/capture.py` (only file)

## READ FIRST
- `mr/core/capture.py` lines 1-46 (imports, `DEFAULT_CAPTURE_BIN`, `BIN_ENV_VAR`, `assert_capture_bin`).
- `tests/test_capture.py` lines 53-68 (`test_bin_resolution_from_env`, `test_bin_resolution_default`) — these must keep passing.

## STEPS
1. At module import, compute an absolute repo-root-anchored default. Replace the module-level `DEFAULT_CAPTURE_BIN = "capture/.build/release/mr-capture"` so that it is absolute, e.g.:
   ```python
   import os
   from pathlib import Path

   _MR_ROOT = Path(__file__).resolve().parent.parent.parent
   DEFAULT_CAPTURE_BIN = str(_MR_ROOT / "capture" / ".build" / "release" / "mr-capture")
   ```
   (Add any import needed; keep `BIN_ENV_VAR` and the body of `assert_capture_bin()` unchanged.)
2. Verify `assert_capture_bin()` returns the absolute path when `MR_CAPTURE_BIN` is unset, and still returns the env override verbatim when set.
3. Run the Python test suite + lint.

## ACCEPTANCE
```sh
cd "/Users/abhinavademmagari/Documents/Projects/meeting recorder"
./spike/.venv/bin/python -m pytest tests/ -q
./spike/.venv/bin/ruff check mr tests
```
All tests pass and ruff is clean. Also run:
```sh
./spike/.venv/bin/python -c "from mr.core.capture import DEFAULT_CAPTURE_BIN, assert_capture_bin; import os; os.environ.pop('MR_CAPTURE_BIN', None); p=assert_capture_bin(); print(p); assert p.startswith('/'), p"
```
and confirm it prints an absolute path ending in `mr-capture` and does not depend on CWD (run the same from `/tmp`).

## OUT OF SCOPE
- Do NOT change the Swift app, `mr/cli.py`, `mr/config.py`, `RecordSession`, or tests.
- Do NOT change the `MR_CAPTURE_BIN` override semantics.
- No new dependencies; use only the stdlib `pathlib.Path`.

## REPORT
Reply with STATUS, FILES CHANGED, VERIFICATION (paste the pytest/ruff tail and the absolute-path check output from both `/`-rooted and `/tmp` CWDs), and NOTES.