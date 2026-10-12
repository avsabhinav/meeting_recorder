TASK: P2.3 Create `mr/state.py` — recording state (pidfile)

GOAL: A small, pure-Python state module that records the currently-active capture in a
pidfile under `<out_root>/.state/` and lets P2.4 (`start/stop/toggle/status/doctor`) query
whether a recording is active, read the active session's details, and clear the file. It also
generates a timestamp `stamp` for a recording. Must be offline, atomic (write-then-rename),
and tolerant of stale/missing state.

CONTEXT:
- Repo: `meeting recorder/` (space in path — quote paths). Python 3.12+ stdlib only
  (`json`, `os`, `pathlib`, `tempfile`, `datetime`, `dataclasses`). No new deps.
- Architecture (§6) and PLAN.md: "the CLI owns recording state via a pidfile in
  `~/Meetings/.state`". `~/Meetings` here is `cfg.out_root` (from `mr.config.Config.out_root`,
  an absolute expanded str). So the state dir is `Path(cfg.out_root) / ".state"`.
- What P2.4 will do (design contract for this module):
  - `start`: spawn `mr-capture --out <out_root>/recordings/<stamp>` (via `RecordSession`
    from `mr.core.capture`), then write the pidfile.
  - `status`: read the pidfile; know active PID, out_dir, stamp, started_at. Also detect a
    stale pidfile (the PID is no longer a live `mr-capture`/child process).
  - `stop`/`toggle`: use the pidfile to signal the running capture.
  So the pidfile must hold: `version`, `pid` (child pid of `mr-capture`), `out_dir`,
  `stamp`, `started_at` (ISO8601). Keep the schema as a frozen dataclass.
- Stale detection: a lightweight probe is enough — `os.kill(pid, 0)` in a try/except:
  if it raises `ProcessLookupError`, the process is gone (treat state as stale). If `ESRCH`/
  `EPERM` edge cases arise, treat as "alive" conservatively (raise only the lookup error).
  Do NOT read /proc; single-user macOS is fine with `os.kill(pid, 0)`.
- `stamp` format: local-time `YYYY-MM-DD_HHMM` (e.g. `2026-08-24_1432`), matching PLAN.md §5
  example filename `2026-08-24_1432.md`. Use `datetime.now().strftime("%Y-%m-%d_%H%M")`.
- Atomicity: write pidfile as `tempfile.NamedTemporaryFile`/write-to-`.tmp` then
  `os.replace` into the final path, then `fsync` the dir if easy (best-effort). This prevents
  a reader from ever seeing a half-written file.
- API (frozen dataclass + functions):
  ```python
  @dataclass(frozen=True)
  class RecordingState:
      version: int
      pid: int
      out_dir: str     # absolute path to the recording directory (contains wavs+meta)
      stamp: str       # e.g. "2026-08-24_1432"
      started_at: str  # ISO8601
  ```
  - `STATE_VERSION = 1`
  - `def state_dir(out_root: str) -> Path` — returns `Path(out_root) / ".state"`.
  - `def state_path(out_root: str) -> Path` — `state_dir(out_root) / "recording.json"`.
  - `def new_stamp() -> str` — local `YYYY-MM-DD_HHMM`.
  - `def write_state(out_root: str, pid: int, out_dir: str, stamp: str, started_at: str) -> None` —
    mkdir state_dir (parents=True, exist_ok=True), atomic write the JSON.
  - `def read_state(out_root: str) -> RecordingState | None` — None if missing/malformed/version
    mismatch; raises `FileNotFoundError` only if the dir/file is absent (return None instead).
    Do NOT auto-clear on read (let P2.4 decide).
  - `def is_clear(out_root: str) -> bool` — True if no state file.
  - `def pid_has_state(pid: int) -> bool` and/or `def is_stale(state: RecordingState) -> bool`
    returning True if `os.kill(pid, 0)` raises `ProcessLookupError`. Choose the clearest shape.
  - `def clear_state(out_root: str) -> None` — remove the pidfile if present (ignore missing),
    best-effort remove the now-empty `.state/` dir.
  Choose the exact set that keeps P2.4 simple; you may add a small convenience like
  `def load_live_state(out_root) -> tuple[RecordingState | None, bool staled]` if it helps, but
  keep the surface minimal and documented.

FILES (create only):
- `mr/state.py`
- `tests/test_state.py`

READ FIRST:
1. `mr/config.py` — `Config.out_root` (an absolute expanded str) — the state module takes
   `out_root: str` directly (do NOT import Config; keep state decoupled).
2. `docs/architecture.md` lines 45-55 — the pidfile/state design and the pipeline it serves.
3. `PLAN.md` lines 39-53 — `~/Meetings/.state`, the `YYYY-MM-DD_HHMM` stamp, and the pipeline.
4. `tests/test_config.py` — existing test conventions.

STEPS:
1. Create `mr/state.py` per the API above. Use `datetime.now().strftime("%Y-%m-%d_%H%M")` for
   `new_stamp`. JSON schema: `{"version":1, "pid":…, "out_dir":…, "stamp":…, "started_at":…}`.
   Atomic write via a temp file in the same dir + `os.replace`. All functions take
   `out_root: str` (never import `mr.config` — keeps the module decoupled and offline).
2. Write `tests/test_state.py` (offline, no network, no subprocess spawns):
   - `test_new_stamp_format`: matches `^\d{4}-\d{2}-\d{2}_\d{4}$`.
   - `test_write_and_read_roundtrip(tmp_path)`: write_state then read_state, fields match,
     state_dir/.state created.
   - `test_read_missing_returns_none(tmp_path)`: no file → None.
   - `test_read_malformed_returns_none(tmp_path)`: write invalid JSON / wrong version → None.
   - `test_is_clear(tmp_path)`: before write True, after write False, after clear True.
   - `test_clear_state(tmp_path)`: write then clear → file gone, `.state/` dir removed.
   - `test_is_stale`: craft a `RecordingState` with a pid that is not running
     (e.g. `pid=2**31-1` or a pid unlikely to exist); `is_stale` True. For the "alive" case,
     use `os.getpid()` → `is_stale` False (our own process is alive).
   - ~6-8 tests.
3. Run suite + ruff on the two files.

ACCEPTANCE:
- `./spike/.venv/bin/python -m pytest tests/ -q` — all pass (existing 69 + new).
- `./spike/.venv/bin/ruff check mr/state.py tests/test_state.py` — clean.
- `./spike/.venv/bin/python -c "from mr.state import new_stamp; print(new_stamp())"` prints a
  `YYYY-MM-DD_HHMM` string. And a smoke round-trip:
  `./spike/.venv/bin/python -c "from mr.state import write_state, read_state, clear_state; d='/tmp/mr-state-smoke'; write_state(d, 1234, d+'/recordings/x', '2026-01-01_0000', '2026-01-01T00:00:00Z'); s=read_state(d); print(s.pid, s.stamp); clear_state(d)"`
  → prints `1234 2026-01-01_0000` and leaves no file.
- No mlx_whisper / typer imports at top level.

OUT OF SCOPE:
- Do NOT spawn/stop processes or signal anything (that's P2.4 with `RecordSession`). This module
  is pure state management + PID-liveness probe only.
- Do NOT integrate with `mr/config.py`/`mr/cli.py`/`capture.py`. Do NOT modify existing files.
- Do NOT add dependencies. Do NOT implement the `mr` CLI subcommands here.
- Do NOT commit (CTO agent owns git).

REPORT: reply with STATUS, FILES CHANGED, VERIFICATION (commands + output), NOTES.