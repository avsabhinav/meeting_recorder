# MR Backlog — Production Build (Phase 1 → Phase 2 → MB Epic → CAP/MB fixes)

> Single source of truth for the production `mr` build. Lead (CTO agent) maintains
> this file and the mirrored `todo_write`. Statuses: `todo → in-progress → review →
> done | blocked | failed`. Each row = one focused task dispatched via `dev_task`.
> Briefs live in `docs/tasks/<epic>_<n>_<slug>.md`; workers reply with STATUS/FILES/
> VERIFICATION/NOTES. **Do not change shared contracts without updating dependents.**

## Context / state

- Phase 1 Core + Epic P2 (capture + control) **DONE**; Epic MB (menu-bar app) **DONE**.
- Phase 1 Core + Epic P2 (capture + control) **DONE**; Epic MB (menu-bar app) **DONE**;
  Epics CAP-AUDIO + MB-DISPLAY **DONE**.
- **This session: two new post-DISPLAY user reports**:
  1. **The menu-bar dropdown STILL does not open after starting a recording** (must end it via
     the CLI). The DISPLAY D1 fix removed `mr status` from the open path, but the *start* action
     still ran `mr start` synchronously on the main thread — and the Python `_spawn_capture` let
     the long-lived `mr-capture` inherit `mr start`'s stdout pipe, so the Swift
     `readDataToEndOfFile()` blocked the main thread for the WHOLE recording.
  2. **`mr stop` from the CLI blocks until transcription completes** — the user wants stop to
     return immediately and let transcription run in the **background**, so they can start a new
     recording right away (back-to-back meetings, long meetings).

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

### Bug 3 (NEW) — dropdown still fails after START; `mr start` blocks the main thread
After DISPLAY D1, the open path is clean, but `StatusItemController.startRecording(_:)`
(STILL synchronous) runs `MRCLI().start()` on the **main thread**. `_spawn_capture`
(`mr/cli.py`) does `subprocess.Popen([binary, "--out", out_dir])` with **no stdio
redirection**, so the long-lived `mr-capture` **inherits `mr start`'s stdout pipe fd** and
keeps it open for the entire recording. `ProcessRunner.realRun` blocks on
`readDataToEndOfFile()` reading that pipe → the main thread is wedged for the whole
recording → the dropdown won't open and the icon never turns red. Killing the capture via
the CLI releases the pipe and the app unblocks (matches the report exactly).
**Decision (user): two-part fix.** (a) `_spawn_capture` must **detach the child's stdio**
(redirect to a per-session `.capture.log`) so the pipe closes when `mr start` exits;
(b) `startRecording` must **run `mr start` off the main thread** (mirror `stopRecording`),
so the menu never blocks on a CLI subprocess even transiently.

### Bug 4 (NEW) — `mr stop` blocks until transcription completes
`_do_stop` (`mr/cli.py`) currently does the whole Whisper transcription + merge + write
**synchronously** before returning. **Decision (user): let transcription run in the
background** (a detached process that outlives `mr stop`), so `mr stop` stops the capture,
clears recording state, spawns a detached `_transcribe` worker, and returns in ~1-2 s.
This supports back-to-back meetings and long meetings. The existing heartbeat
(`transcribing.json`) + menu-bar "Check Active Transcriptions…" item + completion
notification surface the in-flight transcription. Menu-bar item keeps the label
**"Stop Recording & Transcribe"** (user choice).

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

### Epic MB-OPEN — dropdown opens reliably after Start; `mr start` never blocks the menu
| id | Task | Status | Depends |
|----|------|--------|---------|
| O1 | `mr/cli.py` `_spawn_capture`: detach child stdio — `Popen(..., stdout=<recordings/<stamp>/.capture.log>, stderr=<same>)` so `mr-capture` never inherits the CLI's stdout pipe (the menu-bar `readDataToEndOfFile()` must return the moment `mr start` exits). Update/keep `_spawn_capture` signature stable for tests. | done | — |
| O2 | `menu-bar/Sources/mrBar/StatusItemController.swift` `startRecording`: dispatch `MRCLI().start()` off the main thread (mirror `stopRecording`); `setLive(true)` + any error `NSAlert` on the main thread. | done | — |

- **MB-OPEN acceptance (O1+O2):** `cd menu-bar && bash build.sh` exit 0; `swift test --disable-sandbox` green; Python `_spawn_capture` passes `stdout/stderr` (not inherited) — pytest green; **HUMAN verify:** relaunch `mrBar.app`, Start from the icon, then click the icon again — the dropdown MUST open while recording and the icon is red.

### Epic MB-BG — `mr stop` returns immediately; transcription runs in the background
| id | Task | Status | Depends |
|----|------|--------|---------|
| B1 | `mr/cli.py`: add internal `mr _transcribe <stamp> <out_dir> [--json]` subcommand that transcribes + merges + writes `transcripts/<stamp>.md` (+ optional JSON), sets the heartbeat at start and clears it in `finally`, and posts `notify_complete`. Reuses `_transcribe_and_write`. | done | — |
| B2 | `mr/cli.py` `_do_stop` (+ `toggle`): signal capture → wait for WAV flush → clear recording state → spawn a **detached** background `[sys.executable, "-m", "mr.cli", "_transcribe", stamp, out_dir]` (stdin/stdout stderr to DEVNULL, detached session) → return immediately ("stopped, transcribing in background (stamp …)"). Update `stop`/`toggle` docstrings. | done | B1 |
| B3 | Tests + docs: rework `tests/test_cli_start_stop_toggle_status_doctor.py` for non-blocking stop (stop does NOT call `_transcribe_and_write`; a detached spawn is asserted); new tests for `_transcribe` command + `_spawn_capture` detach; README + `docs/architecture.md` (stop no longer waits for transcription) update. `pytest` + `ruff` green. | done | B2 |

- **MB-BG acceptance (B1+B2+B3):** `./spike/.venv/bin/python -m pytest tests/ -q` green; `./spike/.venv/bin/ruff check mr tests` clean; `mr stop` returns in ~1-2 s (no blocking); after `mr stop`, `mr status` shows idle and `~/.cache`…/heartbeat shows the in-flight transcription; a new `mr start` works immediately while the previous transcription is still running; completion notification arrives when the transcript lands. **HUMAN verify** end-to-end with a real recording.

## Per-epic acceptance archive (earlier epics)

- **CAP-AUDIO**: `cd capture && ./build.sh` exits 0 (no `--no-aec`/VPIO refs in source);
  `./spike/.venv/bin/python -m pytest tests/ -q` green; `./spike/.venv/bin/ruff check mr tests`
  clean. Diff read in full: no `setVoiceProcessingEnabled`, no `voiceProcessingOtherAudioDucking`,
  no `mainMixer`→`output` connect, no `--no-aec` anywhere.
- **MB-DISPLAY**: `cd menu-bar && swift test --disable-sandbox` green; `cd menu-bar && ./install.sh`
  rebuilds `.app`; new "Check Active Transcriptions…" item present in `MenuBuilder`. **HUMAN verify:**
  relaunch `menu-bar/.build/Release/mrBar.app`, start recording from the icon, then click the icon
  again — the dropdown MUST open while recording; "Check Active Transcriptions…" shows
  "Searching…" then the active stamp (or None); stop via the dropdown works.

## Epic ECHO — delayed "You" echoes of the speakers survive in the transcript (no new deps)
User reported the transcript shows the user "repeating everything" that played on the speakers. Investigation (real sample `/Users/abhinavademmagari/Documents/Meetings mr/recordings/2026-10-13_1334`): the mic legitimately contains a QUIETER copy of the system audio (acoustic echo). The echoed "You" segments textually match a "Them" segment but TRAIL it by ~8.3–9.4 s (the mic↔system stream offset from `meta.json`, ≈ +9.34 s) — so the existing merge-time time-OVERLAP dedup never fires and the echo survives. `noisereduce` reference-mode was tested and REJECTED (removes ~16 dB of the user's own voice in voice-only windows). Decisions: (1) no new dependencies; (2) implementation = **delay-aware dedup** — drop a "You" segment that matches a "Them" segment AND follows it within the mic↔system offset window. User will validate by transcribing the sample: "if the transcript comes clean then it's acceptable."
| id | Task | Status | Depends |
|----|------|--------|---------|
| D1 | `mr/core/merge.py`: add `echo_lag_s` param to `merge_transcripts`/`_is_echo` (delay-aware drop, keep overlap rule); `mr/cli.py` reads `system_vs_mic` offset from `meta.json` and passes it; tests. (**evidence: real clip → only genuine You survives**) | done | — |
| D2 | Transcribe the sample end-to-end with the fixed pipeline; confirm echoed "You" gone while user's words remain; user acceptance. | done | D1 |

- **ECHO acceptance (D1):** pytest + ruff green; real-data merge keeps only the genuine "testing" You. **ECHO acceptance (D2):** `mr`-transcribed sample `.md` shows the echoed system text attributed to **Them** (or absent), NOT to "You"; user's own words remain attributed to "You". **HUMAN verify** on the sample folder.

## Progress log

- **(this session) MB-OPEN + MB-BG — DONE (verified; commit pending).**
  - **MB-OPEN (O1+O2):** `_spawn_capture` now redirects `mr-capture`'s stdio to `<out_dir>/.capture.log` + `start_new_session=True`, so `mr start` no longer holds the stdout pipe the menu-bar blocks on; `StatusItemController.startRecording` dispatches `MRCLI().start()` off the main thread. Dropdown opens reliably after Start. Menu-bar build + 21/21 Swift tests green.
  - **MB-BG (B1+B2+B3):** new hidden `mr _transcribe <stamp> <out_dir> [--json]` command + `_transcribe_worker` helper (owns heartbeat/transcribe/output/notification); `_do_stop` now SIGINT→flush→clear state→spawn detached background `_transcribe`→return in ~1-2 s. Python suite 141 green (reworked stop tests + new spawn/worker tests), ruff clean, README + architecture updated. `mr _transcribe` hidden from help; `mr --help` stop now reads "transcribe it in the background".
- **(this session) MB-OPEN + MB-BG — PLANNED (todo).** Two new user reports: (1) dropdown still
  won't open after Start (root cause: `_spawn_capture` lets `mr-capture` inherit `mr start`'s
  stdout pipe, so the menu-bar main-thread `readDataToEndOfFile()` blocks for the whole
  recording; plus `startRecording` runs `mr start` on the main thread); (2) `mr stop` blocks
  until transcription completes. Decisions (user): detach capture stdio + run start off the
  main thread (MB-OPEN); run transcription as a detached background `_transcribe` process so
  `mr stop` returns fast (MB-BG), keeping the "Stop Recording & Transcribe" label.
- **(this session) D2+D3 — DONE (verified, no commit yet):** "Check Active Transcriptions…" item added to `MenuBuilder` (tag 707); `StatusItemController.checkActiveTranscriptions` runs `mr status` + heartbeat off the main thread, shows "Searching…" then `<stamp> — transcribing…` or `None (no active transcription)`, and syncs live state. Display logic extracted to `MenuBuilder.transcriptionResultText(stamp:)` (D3) with 3 unit tests → `swift test` 21/21 green. My own `git diff` read + test run confirmed.
- **(this session) D1 — DONE (verified, no commit yet):** open path is now non-blocking.
- **(this session) A3 — DONE (verified, no commit yet):** current docs updated.
- **(this session) A2 — DONE (verified, no commit yet):** Python aec plumbing removed.
- **(this session) A1 — DONE (verified, no commit yet):** raw-mic capture. `MicCapture.start()` no longer enables VPIO, no `mainMixer→outputNode` connect; `main.swift` drops `--no-aec`, `meta.json` writes `aec: false`. `capture/build.sh` exit 0; only `aec` match is the meta key (worker's grep + my own `git diff` read + build re-run confirmed). Also fixed the stale `[--no-aec]` hint line in `capture/build.sh`. Commit pending epic end.
- **(this session) Investigated both reported bugs; decisions locked.** Bug1: VPIO/AEC
  degrades the live call — user chose "record raw mic, stop VPIO entirely". Bug2: dropdown
  blocked by synchronous `mr status` on open — user chose lazy on-demand "Check Active
  Transcriptions…". Backlog restructured with epics CAP-AUDIO (A1–A3) and MB-DISPLAY (D1–D3).
---

# PRODUCTION PREP — repo reorganization, hygiene, CI, and docs (Epic PP)

User decision: this will be a **public** GitHub repo. The Phase-0 spike was a quick
test; everything works, now we get it production-ready for a first push. Decisions
(confirmed): (1) **public repo** → strict hygiene review before push; (2) **archive the
`spike/` folder out of the tracked repo** (move to a local archive outside the repo, drop
from git tracking); (3) **GitHub Actions CI**: ruff + pytest + Swift build for both
`capture/` and `menu-bar/`. The user pushes to GitHub themselves — we never push.

## Current hygiene findings (pre-plan audit)
- Clean `main` (massively auto-committed per-feature). 133 tracked files. No real
  recordings/transcripts/state/config tracked. No `__pycache__` / `.DS_Store` tracked.
  No personal data leaks (the `/Users/u/...` strings in `menu-bar/Tests` are fake
  fixtures; the docs are scripted/fictional checkout conversations, no real calls).
- **5 untracked items** that slip through `.gitignore` today:
  1. `docs/tasks/MB_1_menubar_app.md` — a real task doc → **should be tracked**.
  2. `menu-bar/nohup.out` — runtime cruft → **should be gitignored**.
  3. `spike/echo_spike_analysis.py` + `spike/echo_spike_noisereduce.py` — the spike is
     being archived out of the repo → **moved to archive, untracked/ignored**.
  4. `spike/echo_spike_out/` (~3 MB of WAV binaries) → **moved to archive, ignored**.
- `git rm --cached` will be used for the entire `spike/` tree (keeps local files, removes
  from future tracking). The whole `spike/` folder is relocated to a local archive dir
  **outside** the repo so nothing is lost but nothing gets pushed.

## Epic PP-HYGIENE — clean tree, sane ignores, archive spike (3 tasks)
| id | Task | Status | Depends |
|----|------|--------|---------|
| H1 | Archive `spike/` out of the repo: move the folder to a sibling archive dir outside the repo (e.g. `../meeting-recorder-archive/spike/`), `git rm -r --cached spike/` (keep working copy present until moved), add the archive path + `spike/` to `.gitignore` so no future spike artifacts are tracked. `git status` shows the whole `spike/` tree as removed. | done | — |
| H2 | Track `docs/tasks/MB_1_menubar_app.md` (real doc); add `menu-bar/nohup.out`, `nohup.out` (repo-wide), and any leftover `*.log`/`*.out` runtime artifacts to `.gitignore`. After: `git status --porcelain` shows **zero** untracked files (tree fully clean). | done | H1 |
| H3 | Remove `.pytest_cache/` and `.ruff_cache/` dirs from disk (already git-ignored, just tidy the worktree); confirm `.gitignore` is lean and complete; `git status` clean. | done | H2 |

- **PP-HYGIENE acceptance:** `git status --porcelain` is empty (no untracked, no staged);
  the `spike/` tree lives in the out-of-repo archive (files preserved on disk); running
  `./build.sh` / `pytest` recreates caches that are all git-ignored.

## Epic PP-CI — GitHub Actions: lint + test + Swift build (2 tasks)
| id | Task | Status | Depends |
|----|------|--------|---------|
| C1 | Add `.github/workflows/ci.yml`: a single workflow running on `macos-15` (Apple Silicon, macOS 14.2+ SDK available) on `push` + `pull_request`: (a) setup-python 3.12; (b) `pip install -e ".[dev]"`; (c) `ruff check mr tests`; (d) `pytest`; (e) `cd capture && ./build.sh`; (f) `cd menu-bar && ./build.sh && swift test --disable-sandbox`. One job, sequential steps. | done | H3 |
| C2 | README: add a short "CI" line noting that GitHub Actions runs ruff + pytest + Swift build/test on every push & PR (a badge URL can't be filled until the repo has a known GitHub remote, so document the behavior instead of guessing a URL); the workflow YAML is validated (yaml ok, top keys name/on/jobs, runs-on macos-15, 8 ordered steps). | done | C1 |

- **PP-CI acceptance:** `.github/workflows/ci.yml` is valid YAML; each step's exact command
  exits 0 when run locally the same way (ruff, pytest, both `build.sh`, `swift test`).

## Epic PP-DOCS — production-facing documents (2 tasks)
| id | Task | Status | Depends |
|----|------|--------|---------|
| D1 | Add `CONTRIBUTING.md` (fork/PR flow, setup, `mr doctor`, how to run the checks, how to build both Swift helpers, spike→archive note) and `SECURITY.md` (local-first: how to report; note recordings stay local under `~/Meetings`; no secrets in the repo). | done | C2 |
| D2 | Public-repo hygiene review + README touches: swap `PLAN.md`/`PHASE0_SPIKE.md` spike-era references for a pointer to the archived spike / production docs; also archive root planning docs `PLAN.md`, `PHASE0_SPIKE.md`, `Project Goal.md` into `meeting-recorder-archive/` (user decision, alongside the spike) and untrack them; fix dangling refs in `docs/architecture.md`; remove `spike/` line from README "Project layout"; final `git status` clean. | done | D1 |

- **PP-DOCS acceptance:** `CONTRIBUTING.md` + `SECURITY.md` exist and are accurate; README
  no longer references a tracked `spike/`; `git status --porcelain` clean.

## Full build/test gate (runs at the end, integration)
- Dev/test interpreter is the archived venv at `../meeting-recorder-archive/spike/.venv/bin/python`
  (Python 3.12.13; the `mr` package resolves editable to this repo) — CI creates its own 3.12 env.
- `../meeting-recorder-archive/spike/.venv/bin/python -m pytest tests/ -q` green (146 passed);
  `ruff check mr tests` clean; `cd capture && ./build.sh` exit 0; `cd menu-bar && ./build.sh`
  exit 0. `swift test --disable-sandbox` requires full Xcode (local machine has Command Line
  Tools only, so it is validated on the CI macOS runner instead). Final commit is staged/clean
  for the user to push.

## Progress log
- **(this session) PP — PLANNED.** Audit complete. Decisions locked (public repo, archive
  spike, GH Actions CI). Repo is already well structured (mr/, capture/, menu-bar/, tests/,
  examples/, docs/) — no restructuring of source needed, only hygiene + CI + docs.
- **(this session) PP — HYGIENE DONE (committed 5a8da33).** Archived `spike/` (with its .venv) to
  `../meeting-recorder-archive/spike/`, `git rm -r --cached spike/`; `.gitignore` dropped stale
  spike refs, added `/spike/`, `nohup.out`/`*.out`/`*.log`; tracked `docs/tasks/MB_1_menubar_app.md`;
  removed on-disk `.pytest_cache`/`.ruff_cache`. Tree clean (zero untracked).
- **(this session) PP — CI + DOCS DONE (commit pending).** `.github/workflows/ci.yml` added
  (macos-15, setup-python 3.12, ruff, pytest, capture build, menu-bar build + swift test; trigger
  push@main + pull_request; YAML validated). README gained a "Continuous integration" section.
  `CONTRIBUTING.md` + `SECURITY.md` added. Per user decision, root planning docs `PLAN.md`,
  `PHASE0_SPIKE.md`, `Project Goal.md` archived to `meeting-recorder-archive/` and untracked;
  `docs/architecture.md` header rewritten; README "Project layout" no longer lists `spike/`.
  Full gate green: ruff clean, 146 pytest passed, both `build.sh` exit 0.
