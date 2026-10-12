TASK: P1.6 Create `mr/core/capture.py` — Python wrapper around `mr-capture`

GOAL: A `RecordSession` context-manager/helper that spawns the `mr-capture` binary into a given output dir, forwards Ctrl-C (SIGINT) / SIGTERM to the child, waits for it to finish, and then parses its `meta.json` into a `CaptureMeta` (from `mr.core.schema`). This is Phase 1: it must work against the existing spike-built binary so the pipeline can be driven end-to-end before P2.1 productionizes the Swift capture.

CONTEXT:
- Repo: `meeting recorder/` (account for the space in the path everywhere).
- Python 3.12+, stdlib only in this module (subprocess, os, signal, json, pathlib, time, dataclasses). No typer needed here — that's for `cli.py` (P1.7). No new dependencies.
- The Swift helper contract (already proven, see `spike/SPIKE_RESULTS.md`): `mr-capture --out <dir> [--no-aec]` runs until it receives SIGINT or SIGTERM, then writes `mic.wav`, `system.wav` (16 kHz mono s16le, incremental) and `meta.json` into `<dir>`, and exits 0. When stopped, `mic.wav`/`system.wav`/`meta.json` all exist in `<dir>`.
- `meta.json` schema is parsed by the existing function `from_capture_dict(d: dict) -> CaptureMeta` in `mr/core/schema.py` (raise ValueError if `mic`/`system` keys missing). Do NOT reimplement the parsing; import and call `from_capture_dict`.
- The current working binary lives at `spike/capture/.build/release/mr-capture`. It is a throwaway/spike artifact. For Phase 1 the wrapper must find it via an env var override `MR_CAPTURE_BIN`, defaulting to that relative path. P2.1 will productionize the real binary; keep the env-var override so the wrapper works unchanged later.
- The output dir is created by caller. The wrapper should create it if missing (makedirs(parents=True, exist_ok=True)) before spawning, so a missing dir doesn't fail the subprocess.
- Refer to how the reference spike drives capture if useful: `spike/capture/` (Swift) — read-only, do not modify.

FILES (create only):
- `mr/core/capture.py`
- `tests/test_capture.py`

READ FIRST:
1. `mr/core/schema.py` — read `StreamMeta`, `CaptureMeta`, `from_capture_dict` (lines ~46–97) for the exact parse contract to call.
2. `spike/capture/.build/release/mr-capture` — not source; just confirm it exists (it does).
3. `examples/manual/driver.py` — see how the pipeline is currently driven manually (the wrapper will become its programmatic replacement).

STEPS:
1. Define a module-level default for the binary path. `DEFAULT_CAPTURE_BIN` env: if `MR_CAPTURE_BIN` env var is set, use it; else use the relative path `"spike/capture/.build/release/mr-capture"`. (Do not `os.path.exists` at import time — resolve lazily.)
2. Add a function `assert_capture_bin() -> str` that resolves the binary path (env override or default), checks it exists and is executable, and raises `FileNotFoundError` with a helpful message ("install mr-capture (MR_CAPTURE_BIN) or build the Swift package") otherwise. Return the resolved path.
3. Define a frozen dataclass `CaptureResult` with fields: `out_dir: str` (absolute), `meta: CaptureMeta | None` (parsed from meta.json), `returncode: int`. `meta` is `None` if meta.json is missing/invalid.
4. Implement a class `RecordSession` used as a context manager:
   - `__init__(self, out_dir: str, *, aec: bool = True, capture_bin: str | None = None)`. Store fields; compute the absolute out_dir via `Path(out_dir).resolve()`.
   - `__enter__(self) -> RecordSession`: resolve the binary (raise `FileNotFoundError` if not found), `makedirs` the out_dir, then `self.proc = subprocess.Popen([bin, "--out", out_dir] + ([] if aec else ["--no-aec"]))`. Store `self.proc`. Return self.
   - `__exit__(self, exc_type, exc, tb) -> bool`: if `self.proc` is still running (`poll() is None`), send SIGINT (`os.kill(pid, signal.SIGINT)`) when `exc_type` is `KeyboardInterrupt`, otherwise SIGTERM (`os.kill(pid, signal.SIGTERM)`). Then `self.proc.wait()`. Read out_dir/meta.json (if present) into `self.meta` via `from_capture_dict`. Re-raise nothing (return False) so KeyboardInterrupt still propagates after cleanup. Set `self.returncode`.
   - Handle the case where the child already exited (`poll()` non-None): just `wait()` and read meta.
   - On a non-zero child exit, do NOT raise in `__exit__` (the caller can inspect `self.returncode`); but if meta.json can't be parsed due to an explicit stop-then-parse error, leave `meta` as `None` rather than raising.
5. Keep the context manager safe: catch `subprocess.TimeoutExpired` is not needed (we use `wait()` without timeout, since SIGINT makes the child exit promptly). Guard `os.kill` with `try/except ProcessLookupError`.
6. Write `tests/test_capture.py` using only stdlib mocking (monkeypatch via pytest's `monkeypatch` fixture and `unittest.mock`):
   - `test_bin_resolution_from_env`: set `MR_CAPTURE_BIN` to a temp script; `assert_capture_bin()` returns it.
   - `test_bin_resolution_default`: unset `MR_CAPTURE_BIN`; default relative path returned when it exists (the repo has the spike binary — guard the assertion so the test passes even if the binary is absent by asserting the function raises `FileNotFoundError` when the default doesn't exist, or returns a path whose `.exists()` matches reality; keep it robust).
   - `test_missing_bin_raises`: point `MR_CAPTURE_BIN` at a nonexistent path; enter context and expect `FileNotFoundError`.
   - `test_enter_creates_outdir_and_spawns`: monkeypatch `subprocess.Popen` to a Mock that records args (assert the arg list ends in `["--out", str(abs_outdir)]` and contains `--no-aec` when `aec=False`); confirm the out_dir gets created.
   - `test_meta_parse`: write a valid `meta.json` into a temp dir (a minimal dict with the exact keys `macos_version/aec/started_at/duration_seconds/mic/system` each stream having `device_name/native_sample_rate/native_channels/first_sample_seconds/samples_written`); call `from_capture_dict` on it via the module path you expose, or construct a small helper — the key requirement is that a valid meta.json round-trips to a `CaptureMeta` and an invalid one yields `meta is None`.
   - Where the child pseudo-behaviour matters (signalling on `__exit__`), monkeypatch `Popen` with a fake object exposing `poll`, `kill`-style calls, and `wait`, and drive the `KeyboardInterrupt` path by invoking `__exit__(KeyboardInterrupt, ...)` and asserting the fake's SIGINT-ish method was called. Keep it simple.
   - Aim for ~6–8 focused tests. They must run offline with no network, no real subprocess, and no heavy imports (never import mlx_whisper in tests).
7. Run the test file and the full suite; make ruff green.

ACCEPTANCE:
- `./spike/.venv/bin/python -m pytest tests/ -q` — all tests pass (including the existing 42).
- `./spike/.venv/bin/ruff check mr/core/capture.py tests/test_capture.py` — no issues.
- Optionally verify import: `./spike/.venv/bin/python -c "from mr.core.capture import RecordSession, CaptureResult; print('ok')"` → prints ok.
- The module must import nothing that pulls in mlx_whisper or typer at top level.

OUT OF SCOPE:
- Do NOT modify `mr/core/schema.py`, `transcribe.py`, `merge.py`, `output.py`, `cli.py`, or any spike/ file.
- Do NOT add new dependencies.
- Do NOT implement signalling with kill-groups or job control beyond a direct `os.kill(pid, SIG)` on the single child PID (pass `start_new_session=False` default).
- Do NOT write the CLI (`cli.py`) here — that is P1.7.

REPORT: reply with STATUS, FILES CHANGED, VERIFICATION (the commands above and their output), and NOTES.
