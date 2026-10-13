# MR Backlog — Production Build (Phase 1 → Phase 2 → MB Epic: menu-bar app)

> Single source of truth for the production `mr` build. Lead (CTO agent) maintains
> this file and the mirrored `todo_write`. Statuses: `todo → in-progress → review →
> done | blocked | failed`. Each row = one focused task dispatched via `dev_task`.
> Briefs live in `docs/tasks/<epic>_<n>_<slug>.md`; workers reply with STATUS/FILES/
> VERIFICATION/NOTES. **Do not change shared contracts without updating dependents.**

## Context / state

- Phase 0 spike **GO**; Phase 1 Core **DONE**; Epic P2 (capture + control) **DONE**.
- Live simulated-conversation test **PASSED** (2026-10-12): production `mr toggle`
  → real capture → transcribe → attributed `.md` end-to-end. 106 tests pass; ruff clean.
- **This session: Epic MB** — a macOS menu-bar app ("mrBar") that starts/stops
  recording and shows in-progress transcriptions, per `docs/tasks/MB_1_menubar_app.md`
  (the user-authored feature brief; guiding contract locked in `PLAN.md` §3).

## Environment facts (re-confirmed this session)

- Working dir (HAS A SPACE): `/Users/abhinavademmagari/Documents/Projects/meeting recorder`
- Python for all checks: `./spike/.venv/bin/python` (3.12.13).
  - Tests: `./spike/.venv/bin/python -m pytest tests/ -q`  ·  Lint: `./spike/.venv/bin/ruff check mr tests`
- **`mr` is NOT on `PATH` in this checkout** and `spike/.venv/bin` has no `mr` console
  script. The CLI is invoked as `./spike/.venv/bin/python -m mr.cli <cmd>`. The menu-bar
  app's Process wrapper MUST therefore resolve `mr` robustly: try `shutil.which("mr")`
  first, then a fallback (env hint + configurable). Swift side sequences candidates in order.
- Swift 6.4 / macOS SDK 27 toolchain present. `swift build` inside the DSH sandbox needs
  workspace-local caches: `TMPDIR`, `CLANG_MODULE_CACHE_PATH` and `--disable-sandbox`
  (the `capture/build.sh` pattern). Verified `import AppKit` compiles with those settings.
- System = macOS 27.0.1 (menu bar + system-audio TCC apply).

## Paths / naming

- `menu-bar/` — new SwiftPM package (sibling to `capture/`): executable target `mrBar`.
- Python: `mr/config.py` (add `set_out_root`), `mr/cli.py` (add `config set out_root`).
- Heartbeat: `<out_root>/.state/transcribing.json` (written by `_do_stop`, cleared on done;
  read by the menu bar only when the dropdown opens). Max age for stale-sweep = 300 s.
- Config: `~/.config/mr/config.toml`. State: `<out_root>/.state/recording.json`.

## Shared contracts (LOCKED — dependents assume these)

**`out_root` config** — `mr.config`:
```python
def set_out_root(path: str, *, config_path: str | Path | None = None) -> str:
    """Validate+absolutize `path`, atomically rewrite out_root in the TOML,
    PRESERVING all other keys/values/types, and return the resolved string.
    Rewrites the value as a TOML string. If the config file doesn't exist,
    create it with the user's other defaults plus out_root. Raises ValueError
    on an empty/non-str path."""
```
- Must not disturb unknown keys, comments are not required to be preserved (TOML rewrite
  is fine as long as every existing key keeps its value; default to rebuilding the table).
- CLI: `mr config set out_root <dir>` (typer command under a `config` group).
  Prints the new resolved `out_root`; exit 0 on success, typer.BadParameter/exit 2 on a
  bad path.

**Heartbeat** (`transcribing.json`) — `mr/cli.py` (+ a tiny reader, see task):
```python
# written at the START of transcription inside _do_stop, removed on completion/failure-clear
# shape: {"version":1, "stamp":"<stamp>", "out_root":"<abs>", "started_at":"<ISO8601>"}
# path: <out_root>/.state/transcribing.json
def _heartbeat_path(out_root: str) -> Path ...            # <out_root>/.state/transcribing.json
def write_transcribing_heartbeat(out_root: str, stamp: str, started_at: str) -> None  # atomic
def clear_transcribing_heartbeat(out_root: str, stamp: str) -> None    # remove file when it's ours
def read_transcribing_heartbeat(out_root: str) -> dict | None         # None if missing/malformed/version!=1
```
- `_do_stop`, around `_transcribe_and_write`, writes a heartbeat before transcribing and
  clears it after (in a `finally`, and on `ModelNotCachedError` too). Keep the atomic-write
  correctness bar (same as `mr.state._atomic_write`; reuse or duplicate a local helper).

**Swift → `mr` invocation** — the app NEVER spawns `mr-capture` itself and never writes the
  pidfile/heartbeat. It shells out to `mr` via `Process`. Candidate commands (resolved in
  order at runtime, first available wins):
  1. `mr start` / `mr stop` / `mr status` / `mr config set out_root <dir>` — if `mr` on PATH.
  2. fallback: `python -m mr.cli <cmd>` — with the python resolved from an env hint
     (`MR_PYTHON`), defaulting to trying `python3`, then a doc-configured absolute path.
  The wrapper is centralized in `MRCLI.swift` so only one place sequences the fallback.

## Epics / Tasks (execution order)

### Epic MB-PY — Python backend (menu-bar dependencies; pure + fully unit-tested)
| id | Task | Status | Depends |
|----|------|--------|---------|
| MB-PY1 | `mr.config.set_out_root` atomic+validated write (preserves other keys) + tests | done | — |
| MB-PY2 | `mr config set out_root <dir>` CLI command (+ tests) | done | MB-PY1 |
| MB-PY3 | transcription heartbeat write/clear in `_do_stop` + reader + tests | done | — |
| MB-PY4 | `mr config get out_root` CLI command (+ tests) — lets Swift learn the current root for folder-open/heartbeat base | done | MB-PY2 |

### Epic MB-SW — Swift menu-bar app ("mrBar")
| id | Task | Status | Depends |
|----|------|--------|---------|
| MB-SW1 | `menu-bar/` SwiftPM package scaffold, `mrBar` executable target, `AppInfo.swift` (resolve `mr`/python candidates), `build.sh`, `.gitignore` update | done | — |
| MB-SW2 | `MRCLI.swift` Process wrappers (start/stop/status/config-set) + `TranscriptionState.swift` heartbeat reader (lazy, max-age sweep 300 s) | done | MB-SW1 |
| MB-SW3 | `StatusItemController.swift` + `MenuBuilder.swift` + `main.swift`: NSStatusItem idle/live icon, dropdown menu, lazy refresh on open | done | MB-SW2 |
| MB-SW4 | `StorageLocation.swift` (NSOpenPanel → `mr config set out_root`), Open Transcripts/Recordings folders, Info.plist (LSUIElement + mic/audio usage), entitlements, `install.sh` | done | MB-SW3 |
| MB-SW5 | Compile whole package (sandbox-safe build), headless smoke of pure logic, `docs` manual-test doc (mirror `docs/simulated-test-production.md`), README note | done | MB-SW4 |
| MB-SW7 | **Fix:** an icon click must only open the dropdown, NOT start recording. macOS activates the first highlighted menu item on click-through → insert an inert (disabled) status header as the first row so the click can't hit `Start Recording` (`MenuBuilder.swift` only) | done | MB-SW3 |
| MB-SW8 | **Fix:** changing storage location re-opens the folder picker after the confirmation (re-entrant `refresh()` rebuilds the menu in the action handler → click-through re-fires `Change Storage Location…`; also `NSOpenPanel` not `orderOut` before the modal alert, per `NSSavePanel` API). Remove sync `refresh()` from `changeRoot` + `orderOut` panel before the alert (`StatusItemController.swift` only) | done | MB-SW4 |
| MB-SW9 | **Fix `mr start failed` in the app while the CLI works:** `DEFAULT_CAPTURE_BIN` is a CWD-relative path (`capture/.build/release/mr-capture`); the `.app` launches from a non-repo CWD so the helper can't resolve → `assert_capture_bin` FileNotFoundError → empty stdout → "mr start failed.". Make the default absolute, anchored to the repo root via `__file__` (`mr/core/capture.py`) | done | — |
| MB-SW10 | **Fix v2 of icon-click auto-starting recording (MB-SW7 didn't hold):** the single click opens the menu and macOS auto-activates the first **ENABLED** item under the click — it *skips* disabled rows, so the MB-SW7 disabled header (row 1) fell through to `Start Recording`. Fix: make the first row an **enabled no-op** status header (action = `statusHeaderClicked` no-op) so the auto-activation hits that instead. `MenuBuilder.swift` + `StatusItemController.swift` | done (did NOT hold — see MB-SW11) | MB-SW7 |
| MB-SW11 | **Structural fix v3 of icon-click auto-starting recording:** user confirms MB-SW7/MB-SW10 did not hold — a single icon click still starts a recording. Both prior fixes only changed *which* row absorbs the opening click's auto-activation; they didn't remove the auto-activation itself. Root cause: `statusItem.menu = menuBuilder.menu` makes AppKit treat the opening click as a click-through into the menu (opens + can fire an item in one gesture). Fix: stop assigning `statusItem.menu`; set `statusItem.button.action`/`.target` to a click handler that calls `refresh()` then shows the menu explicitly via `NSMenu.popUp(positioning:at:in:)`, so opening the dropdown and clicking an item inside it become two distinct, separate clicks. Revert the row-1 no-op-header workaround back to a plain disabled status label (no longer needed once auto-activation is structurally impossible). `MenuBuilder.swift` + `StatusItemController.swift` | done (pending human click-test — AppKit event behavior can't be verified in sandbox) | MB-SW10 |

## Per-epic acceptance (commands the CTO agent runs to verify)

- **MB-PY**: `./spike/.venv/bin/python -m pytest tests/ -q` (existing 106 + new all pass);
  `./spike/.venv/bin/ruff check mr tests` clean.
- **MB-SW**: `cd menu-bar && ./build.sh` produces a runnable binary (or at minimum a clean
  `swift build -c release` with the sandbox-safe env); manual-test doc written. The GUI
  event-loop behaviour (status item renders, perms) is HUMAN-verified per the manual-test doc;
  the CTO agent verifies compilation + pure-logic smoke only.

## Progress log

- **(new session) MB-SW11 — DONE (code), structural fix, pending human click-test:** user reported MB-SW10 did not hold (icon click still auto-started a recording). Root cause confirmed: `statusItem.menu = menuBuilder.menu` lets AppKit treat the opening click as a click-through onto a menu item — MB-SW7/MB-SW10 only changed which row absorbed that, never removed the mechanism. Fix: removed the `.menu` assignment; `statusItem.button` now has its own `target`/`action` → new `togglePressed(_:)` which calls `refresh()` then `menuBuilder.menu.popUp(positioning:at:in:)` explicitly, so opening the menu and clicking an item inside it are two separate, distinct clicks (structurally cannot auto-activate). Removed the now-unused `NSMenuDelegate` conformance, `menuWillOpen`, and the `statusHeaderClicked` no-op; reverted row 1 to a plain disabled status label. Verified independently (not just worker's word): `git diff` read in full, matches brief; `swift build -c release --disable-sandbox` exit 0; `swift test --disable-sandbox` 18/18 green; `.app` bundle rebuilt + re-signed via `install.sh`. **HUMAN step (required — this is live AppKit click-timing behavior no sandboxed agent can observe):** quit any running `mrBar`, relaunch the freshly rebuilt `menu-bar/.build/Release/mrBar.app`, and confirm a single icon click ONLY opens the dropdown with no recording started; then confirm clicking "Start Recording" inside the open menu still works and turns the icon red.
- **(prior session) MB-SW10 — DONE (code, commit pending):** first menu row now an ENABLED no-op status header (`statusHeaderClicked`) so a single icon click's auto-activation hits that instead of `Start Recording`. `swift build -c release` clean; `swift test` 18/18 green; `.app` regenerated. **HUMAN step:** relaunch `menu-bar/.build/Release/mrBar.app` and confirm a single icon click only opens the dropdown (no recording). If it STILL auto-records, the mechanism is not "first enabled item" — escalate to the structural fix: decouple the click from the menu via `statusItem.button.action` + `NSMenu.popUp(positioning:at:in:)` (do NOT assign `statusItem.menu`), which structurally cannot auto-activate.
- **(this session) MB-SW9 — DONE (root cause fixed, commit pending):** `DEFAULT_CAPTURE_BIN` now absolute (repo-root-anchored via `Path(__file__)`). pytest 135 passed, ruff clean, and `assert_capture_bin()` returns the absolute helper path from `/tmp` too. **HUMAN step:** relaunch the app and Start Recording — the helper now resolves from any CWD. (The initial "mr start failed." remains as a UI text but should not occur; a follow-on polish MB-SW10 would surface real CLI stderr in the dialog.)
- **(this session) MB-SW9 (in progress) — `mr start failed` in the app but works from CLI:** Confirmed root cause. The user ran `python -m mr.cli start` from the repo root → **succeeds** ("recording started … mic: MacBook Pro Microphone @ 48000 … aec=true"). From the menu-bar `.app` it fails with empty stdout. Cause: `DEFAULT_CAPTURE_BIN = "capture/.build/release/mr-capture"` is **CWD-relative**; the `.app` launches from a non-repo working dir, so `assert_capture_bin()` raises `FileNotFoundError` → typer exit 1, traceback to stderr (swallowed by the app) → "mr start failed.". Fix MB-SW9: anchor the default to the repo root via `Path(__file__)` in `mr/core/capture.py`.
- **(this session) MB-SW8 — DONE (code, pending user re-test):** added `panel.orderOut(nil)` before `changeRoot` + removed the re-entrant `refresh()` from `changeRoot`. `swift build -c release` clean; `swift test` 18/18 green; `.app` regenerated via `install.sh`. **HUMAN step:** relaunch `menu-bar/.build/Release/mrBar.app` (with `MR_PYTHON` set or `mr` on PATH); change storage location → confirm single confirmation, no re-opened picker; then Start Recording to confirm `mr start failed` is gone (this was a knock-on of the double-picker).
- **(this session) MB-SW8 (in progress) — storage-location double-picker + follow-on `mr start failed`:** User: "After selecting the new folder I got the confirmation that it changed but the select folder popped up again" then "mr start failed". Diagnosis: `changeRoot` calls `refresh()` inside the menu-action handler — `refresh()` → `menuBuilder.rebuild()` → `menu.removeAllItems()`+re-add → macOS click-through re-fires the same-position `Change Storage Location…` item → picker re-opens. Also `NSOpenPanel` isn't `orderOut` before the modal `NSAlert` (AppKit `NSSavePanel` API: must `orderOut` before showing an alert from the completion handler). Fix scope MB-SW8. The `mr start failed` is a knock-on: the double/re-entrant change can leave `out_root` momentarily wrong; `mr start` itself verified working on the real Mac. CTO sandbox blocks writes to `~/Documents/Meetings mr`, so the CTO cannot validate `mr start` against a real path — needs a user re-test after MB-SW8.
- **(this session) MB-SW7 bug fix — DONE (commit 8df4368):** inert first menu row. `swift build -c release` clean; `swift test` 18/18 green; `.app` bundle regenerated via `install.sh`. User must relaunch the rebuilt app to confirm the icon click no longer starts a recording.
- **(this session) MB-SW7 bug fix:** User report — "as soon as I click on the icon a meeting recording starts … it should just open the dropdown." Confirmed via user: the dropdown opens AND the click lands on the first auto-highlighted item, activating it. First item is `Start Recording` → single icon click starts recording. Fix: inert (disabled, non-actionable) status header becomes the topmost row so the click-through hits nothing. Brief `docs/tasks/MB-SW7_fix_first_item.md`.
- **(this session) Started Epic MB (menu-bar app).** Backlog refreshed from `MB_1_menubar_app.md`; plan + decomposition below.
  - **Post-Epic MB-SW6 (d7e344b):** Start/Stop now show an error dialog on any `mr` CLI failure instead of silently closing the menu. Confirmed via user test that `mr start` itself works on the real Mac (creates `~/Meetings/recordings/<stamp>`, records from mic). The earlier `FileNotFoundError` on `~/Meetings` was an artifact of the CTO's DSH sandbox (blocks `~/Meetings` writes), NOT a real `mr` bug. Remaining real issue: verifying the GUI action context — the `.app` must be launched with `MR_PYTHON=/Users/abhinavademmagari/Documents/Projects/meeting recorder/spike/.venv/bin/python` (or `mr` on PATH) or the CLI lookup fails `.mrUnavailable`. **HUMAN step now:** relaunch the freshly built `menu-bar/.build/Release/mrBar.app` with `MR_PYTHON` set and Start Recording — the icon should turn red and (on any failure) an alert explains why.
  - MB-PY1/2/3 done (config set_out_root, `mr config set out_root`, heartbeat). 133 Python tests pass, ruff clean.
  - MB-SW1 done (package scaffold + AppInfo). MB-SW2 done (MRCLI + TranscriptionState + XCTest target).
  - **`swift test` now GREEN (Xcode installed):** 17/17 tests pass via `DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer swift test`. `build.sh` auto-selects the Xcode toolchain. One test bug fixed (TrailingZ fixture now emits a genuine UTC `Z`).
  - **Environment note:** this host has only Xcode CommandLineTools (no Xcode.app), so `swift test` cannot run here (`XCTest` not found). Verification of Swift logic uses a Foundation-only runtime self-check harness (16 checks) + compile of the release binary. User chose to **install Xcode**; once installed, run `swift test` on `menu-bar/` for the real unit tests.
  - **Cross-language fix (behind MB-SW2):** Python heartbeats now write a UTC-aware `Z`-suffixed `started_at` (was naive local) so Swift `ISO8601DateFormatter` parses it; Swift reader has a naive-local fallback. Verified end-to-end.
- Prior history (Phase 1 + P2): see git log; all engineering done.

## Open decisions (from `MB_1_menubar_app.md`, defaults adopted — see that file for the full decision log)

1. Async stop → icon flips idle immediately; "Transcribing" section in the dropdown. **B1 heartbeat file.**
2. Lazy refresh — icon/list computed only on dropdown open; no background timer.
3. `mr` lookup — resolve candidates in order; explicit error menu item when none found.
4. Non-sandboxed → use `NSOpenPanel` and spawn CLI from the app (TCC attributes permissions to the app).
5. Store location edits the shared `~/.config/mr/config.toml` via `mr config set out_root`.
6. Heartbeat path `<out_root>/.state/transcribing.json`; `max_age` = 300 s.