# MR Backlog — Production Build (Phase 1 → Phase 2 → MB Epic → CAP/MB fixes)

> Single source of truth for the production `mr` build. Lead (CTO agent) maintains
> this file and the mirrored `todo_write`. Statuses: `todo → in-progress → review →
> done | blocked | failed`. Each row = one focused task dispatched via `dev_task`.
> Briefs live in `docs/tasks/<epic>_<n>_<slug>.md`; workers reply with STATUS/FILES/
> VERIFICATION/NOTES. **Do not change shared contracts without updating dependents.**

## Context / state

- Phase 1 Core + Epic P2 (capture + control) **DONE**; Epic MB (menu-bar app) **DONE**.
- **This session: two post-MB bug fixes** based on the user's real Microsoft Teams call:
  1. **Recording degrades the live call audio** (remote participant + user's own voice
     both sound low while recording; normal again the moment recording stops).
  2. **The menu-bar dropdown will not open while recording is running** (must stop via CLI;
     dropdown works again after stop).

## Root causes (confirmed by inspection)

### Bug 1 — capture-time echo cancellation (VPIO) degrades the call
`capture/Sources/mr-capture/MicCapture.swift` enables AVAudioEngine voice processing
(VPIO) by default and connects `engine.mainMixerNode → engine.outputNode`, which starts a
voice-chat IO unit that:
- grabs the mic in voice-chat mode (AGC / high-pass / echo suppression → attenuates the
  near-end voice),
- renders through the physical output device and triggers macOS to duck "other audio"
  (the remote participant's voice from Teams).
Both symptoms disappear the moment recording stops. A VPIO session cannot run on the same
mic+output as an active VoIP call without degrading it. **Decision (user): record the raw
mic with no voice processing at all; echo is handled by the existing merge-time text-overlap
dedup (the architecture's documented safety net). Recording becomes invisible to the call.**

### Bug 2 — dropdown blocked by synchronous `mr status` on every open
`StatusItemController.togglePressed` → `refresh()` calls `MRCLI().status()` on the **main
thread**, and `ProcessRunner.realRun` blocks on `readDataToEndOfFile()`, then
`NSMenu.popUp` runs inside the status-bar button's tracking event. Blocking the main
thread mid-track and popping the menu synchronously inside a tracking event is a
known-fragile AppKit pattern; it fails intermittently once the live state makes the path
slower (matches: works idle, fails while recording). **Decision (user): stop running
`mr status` on every open; drive Start/Stop enablement from the app's locally-tracked live
state; move transcription-status behind an explicit on-demand **"Check Active
Transcriptions…"** menu item that shows **"Searching…"** then the active transcription name
or **"None"** (like the "Change Storage Location…" item).**

## Environment facts

- Working dir (HAS A SPACE): `/Users/abhinavademmagari/Documents/Projects/meeting recorder`
- Python for all checks: `./spike/.venv/bin/python` (3.12.13).
  - Tests: `./spike/.venv/bin/python -m pytest tests/ -q`  ·  Lint: `./spike/.venv/bin/ruff check mr tests`
- Swift: Xcode toolchain present. `capture/build.sh` and `menu-bar/build.sh` are sandbox-safe
  (workspace-local caches + `--disable-sandbox`). Menu-bar tests: `swift test --disable-sandbox`
  from `menu-bar/` (Xcode installed).
- `mrBar` rebuild + re-sign: `cd menu-bar && ./install.sh`. Human relaunch required after.

## Paths / naming

- `capture/Sources/mr-capture/MicCapture.swift`, `main.swift` — remove VPIO/AEC.
- `mr/core/capture.py`, `mr/cli.py` — remove `--aec`/`--no-aec` plumbing.
- `menu-bar/Sources/mrBar/StatusItemController.swift`, `MenuBuilder.swift`, `MRCLI.swift`,
  `TranscriptionState.swift` — lazy on-demand transcription status; no blocking on open.
- `tests/test_capture.py`, `tests/test_cli_start_stop_toggle_status_doctor.py` — drop aec asserts.
- Docs: `README.md`, `docs/architecture.md`, `docs/tasks/*`, `config.toml.example`.

## Shared contracts (LOCKED)

**`mr-capture` CLI** (after fix): `mr-capture --out <dir>` only — the `--no-aec` flag and all
voice-processing/ducking code are removed. The binary always records: (a) **raw mic** via an
input-bus tap with NO voice processing and NO `mainMixer→outputNode` connection (the engine
never starts an IO unit on the output device), (b) the system audio tap (unchanged). Writes
`mic.wav` / `system.wav` / `meta.json`; `meta.json` keeps `"aec": false`.

**Python CLI** (after fix): `mr start` / `mr toggle` no longer accept `--aec`/`--no-aec`.
`RecordSession` drops the `aec` kwarg; `_spawn_capture`/`_do_start` drop the `aec` parameter.
`CaptureMeta.aec` (schema) remains but always reads false — no merge/output dependency.

**Menu-bar** (after fix): opening the dropdown NEVER spawns a process and never blocks the
main thread. Start/Stop enablement derives from the controller's locally-tracked
`isLiveRecording`. The "Transcribing:" section is removed from the open menu. A new
**"Check Active Transcriptions…"** menu item runs `mr status` (+ heartbeat) on an explicit
click: label → "Searching…", result → shows `<stamp> — transcribing…` or `None (no active
transcription)`, and syncs the live state. App lays-over-transient text as a second menu row.

## Epics / Tasks (execution order)

### Epic CAP-AUDIO — Stop degrading the live call (remove capture-time VPIO/AEC)
| id | Task | Status | Depends |
|----|------|--------|---------|
| A1 | `MicCapture.swift`: remove voice-processing/ducking + `mainMixer→output` connect; `main.swift`: drop `--no-aec` parsing + `aecEnabled`; always raw mic. `meta.json` writes `aec: false`. Build with `capture/build.sh`. (**done**; build exit 0; also fixed the `[--no-aec]` hint in `capture/build.sh`) | done | — |
| A2 | Python: drop `aec` from `RecordSession`, `_spawn_capture`, `_do_start`, `start`, `toggle`; remove `--aec/--no-aec` options; update `tests/test_capture.py` + cli tests (remove `--no-aec`/aec-default asserts, `SAMPLE_META["aec"]` stays). pytest + ruff green. (**done**; 137 tests pass, ruff clean) | done | A1 |
| A3 | Docs: README CLI reference (remove `--aec/--no-aec`; rewrite Echo-handling + Permissions to state recording is invisible to the call, echo via dedup), `docs/architecture.md` design decision, operational docs (`docs/simulated-test-production.md`, `examples/manual/README.md`). Historical spike/plan/task briefs left untouched. (**done**; zero `--aec` refs in current docs) | done | A2 |

### Epic MB-DISPLAY — Dropdown always opens + on-demand transcription status
| id | Task | Status | Depends |
|----|------|--------|---------|
| D1 | `StatusItemController.refresh()`: stop calling `mr status` / heartbeat on open (no main-thread spawn, no block). Start/Stop enablement from local `isLiveRecording`; cache `cliAvailable` once at init. Remove the always-rendered "Transcribing:" section from `MenuBuilder.rebuild` (now `rebuild(status:isCLIAvailable:)`). (**done**; build exit 0, no subprocess on open path) | done | — |
| D2 | Add **"Check Active Transcriptions…"** item: on click set row label to "Searching…", run `MRCLI.status()` + `TranscriptionState.activeHeartbeat()` off the main thread, then update the row to `<stamp> — transcribing…` or `None (no active transcription)`; opportunistically sync `isLiveRecording` from the result. Uses `MRCLI` (no new subprocess logic beyond the existing runner). (**done**; build exit 0, all CLI work off main thread) | done | D1 |
| D3 | XCTest updates + new tests for the lazy item runner and the non-blocking `refresh` (pure-logic, fake runner); `swift test --disable-sandbox` green from `menu-bar/`; `menu-bar/install.sh` rebuilds + re-signs the `.app`. (**done**; 21 tests pass = 18 + 3 new MenuBuilderTests) | done | D2 |

## Per-epic acceptance (CTO runs to verify)

- **CAP-AUDIO**: `cd capture && ./build.sh` exits 0 (no `--no-aec`/VPIO refs in source);
  `./spike/.venv/bin/python -m pytest tests/ -q` green; `./spike/.venv/bin/ruff check mr tests`
  clean. Diff read in full: no `setVoiceProcessingEnabled`, no `voiceProcessingOtherAudioDucking`,
  no `mainMixer`→`output` connect, no `--no-aec` anywhere.
- **MB-DISPLAY**: `cd menu-bar && swift test --disable-sandbox` green; `cd menu-bar && ./install.sh`
  rebuilds `.app`; new "Check Active Transcriptions…" item present in `MenuBuilder`. **HUMAN verify:**
  relaunch `menu-bar/.build/Release/mrBar.app`, start recording from the icon, then click the icon
  again — the dropdown MUST open while recording; "Check Active Transcriptions…" shows
  "Searching…" then the active stamp (or None); stop via the dropdown works.

## Progress log

- **(this session) D2+D3 — DONE (verified, no commit yet):** "Check Active Transcriptions…" item added to `MenuBuilder` (tag 707); `StatusItemController.checkActiveTranscriptions` runs `mr status` + heartbeat off the main thread, shows "Searching…" then `<stamp> — transcribing…` or `None (no active transcription)`, and syncs live state. Display logic extracted to `MenuBuilder.transcriptionResultText(stamp:)` (D3) with 3 unit tests → `swift test` 21/21 green. My own `git diff` read + test run confirmed.
- **(this session) D1 — DONE (verified, no commit yet):** open path is now non-blocking.
- **(this session) A3 — DONE (verified, no commit yet):** current docs updated.
- **(this session) A2 — DONE (verified, no commit yet):** Python aec plumbing removed.
- **(this session) A1 — DONE (verified, no commit yet):** raw-mic capture. `MicCapture.start()` no longer enables VPIO, no `mainMixer→outputNode` connect; `main.swift` drops `--no-aec`, `meta.json` writes `aec: false`. `capture/build.sh` exit 0; only `aec` match is the meta key (worker's grep + my own `git diff` read + build re-run confirmed). Also fixed the stale `[--no-aec]` hint line in `capture/build.sh`. Commit pending epic end.
- **(this session) Investigated both reported bugs; decisions locked.** Bug1: VPIO/AEC
  degrades the live call — user chose "record raw mic, stop VPIO entirely". Bug2: dropdown
  blocked by synchronous `mr status` on open — user chose lazy on-demand "Check Active
  Transcriptions…". Backlog restructured with epics CAP-AUDIO (A1–A3) and MB-DISPLAY (D1–D3).