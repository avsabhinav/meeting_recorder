TASK: P2.1 Productionize `capture/` Swift package (move spike -> top-level, install flow)

GOAL: The proven spike Swift capture helper moves from `spike/capture/` to a top-level
`capture/` SwiftPM package that builds the same `mr-capture` binary with a production
Info.plist (proper bundle id / usage strings) and an install step that places the binary
where the P1.6 Python wrapper (`mr/core/capture.py`) finds it. The CLI contract
`--out <dir> [--no-aec]` and the SIGINT/SIGTERM->finalize behavior must be byte-identical,
so `mr process` and the future `mr toggle` keep working. Existing `spike/capture/` stays
untouched as the throwaway reference.

CONTEXT:
- Repo: `meeting recorder/` (space in path).
- The spike helper is fully proven (manual test PASSED; see `docs/manual-test-result.md`).
  The Swift source is byte-for-byte what we ship — this task is relocation +
  production packaging, NOT rewriting capture logic.
- Structure in `spike/capture/`: `Package.swift` (swift-tools 5.9, macOS 14.2,
  executable `mr-capture`), `build.sh` (embeds Info.plist via `-sectcreate`, adhoc codesign),
  `Info.plist` (currently `CFBundleIdentifier = local.spike.mr-capture`,
  NSMicrophoneUsageDescription, NSAudioCaptureUsageDescription, LSUIElement), and
  `Sources/mr-capture/{main,MicCapture,SystemTap,Resample,Wav}.swift`.
- Production location per `docs/architecture.md`: top-level `capture/` package. The repo
  root already has `mr/`, `tests/`, `examples/`, `docs/`, `pyproject.toml`.
- The P1.6 wrapper default binary path is `"spike/capture/.build/release/mr-capture"` with
  env override `MR_CAPTURE_BIN` (`mr/core/capture.py`, `assert_capture_bin()`). This task
  should make the *default* point at the production build (`capture/.build/release/mr-capture`)
  so `RecordSession` and `mr process`/`mr toggle` use the production binary with no manual
  env var. The `MR_CAPTURE_BIN` override stays for testing/P2.4.

FILES (create/modify/delete only):
- CREATE: `capture/Package.swift`, `capture/build.sh`, `capture/install.sh`, `capture/Info.plist`
- CREATE: `capture/Sources/mr-capture/main.swift`, `MicCapture.swift`, `SystemTap.swift`,
  `Resample.swift`, `Wav.swift` (copied verbatim from spike, unchanged)
- EDIT: `mr/core/capture.py` (only the `DEFAULT_CAPTURE_BIN` constant)
- EDIT: `tests/test_capture.py` (only the `test_bin_resolution_default` robustness guard if needed)
- do NOT touch any file under `spike/` (reference stays), and no other `mr/`/`tests/` files.

READ FIRST (all read-only):
1. `spike/capture/Sources/mr-capture/` — all 5 Swift files, verbatim source to copy.
2. `spike/capture/build.sh` and `spike/capture/Info.plist` — the build recipe and plist to adapt.
3. `spike/capture/Package.swift` — the package manifest to reproduce at top level.
4. `mr/core/capture.py` — `DEFAULT_CAPTURE_BIN` constant and `assert_capture_bin()` (lines ~23-38).
5. `tests/test_capture.py` — `test_bin_resolution_default` (it asserts the current default path).

STEPS:
1. Create `capture/` mirroring `spike/capture/`:
   - `capture/Package.swift` — copy of the spike manifest exactly
     (name `mr-capture`, platforms macOS 14.2, executable target `mr-capture`,
     path `Sources/mr-capture`).
   - `capture/Info.plist` — copy, but set `CFBundleIdentifier` from
     `local.spike.mr-capture` to a production value, e.g. `com.local.mr-capture`
     (or `local.mr-capture` — keep it clearly non-spike). Keep the two usage strings,
     `CFBundle*Version`, `LSUIElement`. Do not add any new permission keys beyond the
     existing `NSMicrophoneUsageDescription` + `NSAudioCaptureUsageDescription`.
   - `capture/Sources/mr-capture/*.swift` — copy all 5 files from `spike/capture/`
     byte-for-byte (no edits; the logic is already proven and locked).
   - `capture/build.sh` — copy of the spike recipe, adjusted only for the new path
     (builds `capture/.build/release/mr-capture`, embeds `capture/Info.plist`, adhoc
     codesign). Keep `--disable-sandbox` and the otool/codesign verification steps.
2. Create `capture/install.sh` (new, executable): runs `../capture/build.sh` (or `./build.sh`),
   then installs `capture/.build/release/mr-capture` to a stable, versioned destination the
   production wrapper points at. Two acceptable destinations — pick ONE and document it:
   (a) keep in-repo `capture/.build/release/mr-capture` and just make the wrapper default
   there (no system copy), or (b) `~/bin/mr-capture` (or `/usr/local/bin`). Prefer (a) for
   this task (repo-local, no sudo) and have the wrapper default point at
   `capture/.build/release/mr-capture`. The install script prints where it installed and
   reminds the user to set `MR_CAPTURE_BIN` if they choose a system location.
3. EDIT `mr/core/capture.py`: change the module default from
   `DEFAULT_CAPTURE_BIN = "spike/capture/.build/release/mr-capture"`
   to
   `DEFAULT_CAPTURE_BIN = "capture/.build/release/mr-capture"`.
   Do not touch `assert_capture_bin()`, `RecordSession`, or anything else.
4. EDIT `tests/test_capture.py` ONLY if the `test_bin_resolution_default` guard references
   the old path and would break. It asserts "if the default exists, return it and it's
   executable; else raise FileNotFoundError", driven by `DEFAULT_CAPTURE_BIN` — so after
   you build `capture/`, the default exists (built) and the test should pass unchanged.
   Only adjust it if ruff or the test fails, and keep the change minimal and robust to a
   not-yet-built binary.
5. Build: run `capture/build.sh` (or `swift build` from `capture/`) and confirm
   `capture/.build/release/mr-capture` exists and is executable, and that
   `mr-capture --help`/`--out` still prints the expected usage (exit 2 with the usage line)
   exactly like the spike binary.
6. Add an integration/regression sanity note: run `./spike/.venv/bin/python -c
   "from mr.core.capture import assert_capture_bin, RecordSession; print(assert_capture_bin())"`
   and confirm it now resolves `capture/.build/release/mr-capture`.
7. Run the full suite + ruff.

ACCEPTANCE:
- `./spike/.venv/bin/python -m pytest tests/ -q` — all 56 tests still pass (no regressions;
  test_capture's default-resolution test must stay green with the new default).
- `./spike/.venv/bin/ruff check mr/core/capture.py tests/test_capture.py` — clean.
- `capture/build.sh` runs and produces `capture/.build/release/mr-capture` (executable);
  `capture/.build/release/mr-capture --out` prints the usage line and exits 2
  (smoke: run it with no valid args; it should print `usage: mr-capture --out ... [--no-aec]`
  and exit 2 — do NOT start a real recording).
- `./spike/.venv/bin/python -c "from mr.core.capture import assert_capture_bin; print(assert_capture_bin())"`
  prints `capture/.build/release/mr-capture`.
- `git status` shows only the intended new `capture/` files + the `mr/core/capture.py`
  DEFAULT constant edit (+ optional test edit). No files under `spike/` modified.

OUT OF SCOPE:
- Do NOT rewrite the Swift capture logic (copy verbatim). No new permission keys.
- Do NOT implement `mr doctor` (P2.4). Do NOT add `config.py`/`state.py` (P2.2/P2.3).
- Do NOT remove or rename anything in `spike/`.
- Do NOT change `RecordSession`, `assert_capture_bin` (except the DEFAULT constant), or any
  other `mr/` module. Do NOT touch pyproject.toml.
- Do NOT commit anything (the CTO agent owns git).

REPORT: reply with STATUS, FILES CHANGED, VERIFICATION (commands + output, including the
build and the resolved binary path), and NOTES (which install location you chose and why).