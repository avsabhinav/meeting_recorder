# MB_1 — macOS Menu Bar App (start/stop + storage location)

> Epic: **Menu bar (v1.1)**. This is the "simple mac menu bar icon on the top
> right" feature. It adds a native status-bar `NSStatusItem` that lets the user
> (1) choose where meeting recordings are stored and (2) **start** / **stop**
> recording, where Stop also triggers transcription into a `.md`.
>
> **Guiding contract (locked in `PLAN.md` §3):** the menu-bar app **calls the
> existing `mr` CLI / core and never records independently**. All recording
> state, capture, and transcription stay owned by `mr`. The menu bar is a thin,
> native Swift shell around it.
>
> Decision log for this task (user-confirmed):
> - **Shell stack:** native Swift `NSStatusItem` app (recommended).
> - **Stop → transcribe:** fire-and-forget + completion notification (matches
>   current CLI behavior; menu bar stays responsive).
> - **Storage location:** the folder picker edits the existing `out_root` in
>   `~/.config/mr/config.toml` (recordings/ + transcripts/ both move under the
>   new root).

---

## 1. User story & success criteria

**As a user** I want a small icon in the macOS menu bar (top right) so that I
can control recording without the terminal.

**When idle:** icon is plain (e.g. grayscale mic / dot). **When recording:** icon
is highlighted (e.g. red/live) to indicate the recording is in progress.

- Click → menu with:
  - **Start Recording** (disabled/✓ when recording)
  - **Stop Recording & Transcribe** (disabled when idle)
  - **Change Storage Location…** → `NSOpenPanel` folder picker → persists to config
  - **Show Status / Open Transcripts Folder**
  - **Quit**

**Done bar (accept/reject):**
1. Icon renders in the menu bar and its state (idle vs live) accurately mirrors
   `mr status` (incl. stale pidfile handled).
2. **Start** spawns a capture identical to `mr start` (AEC on by default) and the
   icon turns live.
3. **Stop** triggers `mr stop`-equivalent behavior; transcription runs and the
   completion notification fires; icon returns to idle **immediately** after stop
   (not after transcription finishes).
4. **Change Storage Location** updates `out_root` such that a NEW recording lands
   in the new root; existing files are NOT moved (must be clearly communicated in
   the UI copy).
5. First-run permissions (Microphone + System Audio Recording) work when the app
   is launched from the menu bar (TCC attribution — see risks).

---

## 2. Architecture

```
 macOS menu bar (NSStatusItem) — Swift, "mrBar" app
   │  calls (Process)                          │  reads/writes
   ├── mr start        (AEC on)                │
   ├── mr stop                                 │  ~/.config/mr/config.toml  (out_root)
   ├── mr status       (poll idle/live)        │
   └── open folder (transcripts / recordings)  │
```

Key principle: the app never spawns `mr-capture` itself and never writes the
pidfile. It shells out to the `mr` CLI that already exists, so behavior stays
identical to the hotkey/terminal flow and all state logic stays in Py.

Two integration styles considered — **both are viable**; recommended is A:

- **A. Shell out to existing `mr` CLI** (recommended): `Process` runs
  `mr start` / `mr stop` / `mr status`. Minimal new logic, single source of
  truth, but depends on `mr` being on `PATH` inside the app's environment.
- **B. Call `mr.core.*` via a tiny Python HTTP/stdio bridge**: more moving
  parts, unnecessary for v1.1.

Go with **A**, and make the `mr` invocation robust (whitelist the resolved
`mr` executable path, provide env hints / fallback if not found).

**Config write-back:** Python owns config today. For v1.1 we add an **`mr set-*
config` CLI command** (or the Swift app writes the TOML directly). Recommended:
add `mr config set out_root <dir>` to `config.py`/`cli.py` so the write-back is
validated/atomic and tested, vs. the Swift app editing TOML. This keeps existing
`load_config` the single reader.

---

## 3. Components & files

New Swift package (sibling to `capture/`):
```
menu-bar/
├── Package.swift                 # executable target "mrBar", app bundle
├── Sources/mrBar/
│   ├── main.swift                # NSApplication + StatusItem setup, event loop
│   ├── MenuBuilder.swift         # builds menu items; enable/disable states
│   ├── StatusItemController.swift # icon + highlighted state management
│   ├── Recorder.swift            # Process wrappers: mr start/stop/status
│   ├── StorageLocation.swift     # NSOpenPanel + persists out_root choice
│   └── AppInfo.swift             # PATH resolution, binary lookup, version
```

Python changes (small, in existing files):
```
mr/config.py      # add set_out_root(path) atomic write (validates, preserves keys)
mr/cli.py         # add `mr config set out_root <dir>` command (calls set_out_root)
```

Sandbox/plist needs (spike already proved `com.local.mr-capture`); menu-bar app
needs an **Info.plist** declaring:
- `LSUIElement` = YES (no Dock icon — it's a menu bar app)
- `NSMicrophoneUsageDescription` (then launch it as the "foreground"/responsible
  process so TCC attributes permissions to it)
- System Audio Recording entitlement for macOS 15+ (`com.apple.security.device.audio-input` /
  system audio recording TCC — confirm exact key in spike).

---

## 4. Behavior detail

### 4.1 Start
- Menu item "Start Recording" → run `mr start` (AEC default) → on exit 0, poll
  `mr status` → set icon to live/highlighted.
- If `mr start` reports "already recording", just show live state (idempotent).

### 4.2 Stop (the important UX requirement)
- "Stop Recording & Transcribe" → run `mr stop` **asynchronously** (fire-and-forget).
- `mr stop` writes the `.md` (blocks on transcription ~1–3 min for long calls).
- **Menu icon flips to idle immediately** on stop initiation — do NOT block the
  status bar on transcription. A status read `mr status` returns "not recording"
  for this purpose.
- Transcription completion is surfaced by the **existing osascript notification**
  in `notify_complete` (already wired in `_do_stop`).
- Because `mr stop` is long-running, run it in a background queue; do not call it
  synchronously on the main thread.
- **Progress visibility (user decision):** active transcription(s) appear as a
  **"Transcribing" section inside the dropdown menu** — a live list of any
  in-flight transcription tasks (one entry per recording being processed). This
  gives the user confidence things are progressing without cluttering the status
  bar icon. See §4.5.

### 4.5 Active transcription list (in the dropdown)
- Adding a stop spawns a **TranscriptionTask** entry. The dropdown renders a
  disabled/faded **"Transcribing:"** section header, then one row per active task,
  e.g. `2026-08-24_1432 — transcribing…`.
- **Refresh is lazy — on dropdown open, never polling** (user decision). The list
  is only re-queried when the user actually opens the menu. This keeps the app
  battery/CPU-friendly and the state fresh-enough for a confidence check.
- **Cross-process visibility (user decision): Option B.** Progress comes from
  Python so transcription started *outside* the app (CLI `mr stop`, hotkey) also
  shows. Mechanism — pick one; recommended is the heartbeat file:
  - **B1 (recommended): heartbeat files.** When `_do_stop` begins transcription it
    writes `<out_root>/.state/transcribing.json` (or `~/.config/mr/transcribing.json`)
    with `{stamp, started_at}`; on completion it removes it (or marks done). The
    menu bar reads the file **only when the dropdown opens** and lists each entry.
    Duration/liveness can be derived from `started_at` (a task older than a cap is
    shown as stale/failed).
  - **B2 (less moving parts, no Python write):** the app shells `mr status` /
    `mr process --just-report` style query purely on dropdown open. If a dedicated
    query is added, ensure it does NOT trigger transcription. Cleaner API; still a
    CLI round-trip per open. **Default for v1.1: B1** (heartbeat file) because it
    needs no new query surface and renders both self- and cross-launched tasks.
- Entry lifecycle: shelf-life/sweep — since we only read on open, a crashed task
  should not show "transcribing" forever. A transcription older than e.g.
  `max_age` (default from `started_at`) is shown as **"— (no longer running / failed)"**
  and ignored. Only-helpful because a genuinely-long call may legitimately sit >1 min.

### 4.3 Change Storage Location
- "Change Storage Location…" → `NSOpenPanel` (choose directory) → confirms a new
  root → runs `mr config set out_root <new>` → updates UI copy.
- UI copy must state: **recordings/transcripts for NEW sessions go to the new
  root; existing files are not moved.**

### 4.4 Idle/live state detection
- Derive icon state on: launch, after start, after stop.
- **No background polling.** The icon state is refreshed **when the menu is opened**
  (the dropdown is the trigger). This avoids a constantly-running timer while the
  app sits idle in the menu bar.
- The dropdown refresh reads the pidfile / `mr status` (or the heartbeat file for
  transcriptions) and updates the icon + list atomically for that open. This also
  reflects external starts (hotkey/Shortcuts) the next time the user opens the menu.
- Reuse `is_stale` semantics: a stale pidfile should show idle with a
  "recording left running / stale — run mr stop" row.

---

## 5. Risks & mitigations

| Risk | Mitigation |
|---|---|
| **TCC permissions** attributed to launch context (menu bar app vs Shortcuts) | Do the permission-granting from the menu bar app so it becomes the "responsible process"; spike confirms attribution; `mr doctor` documents. |
| `mr` not on `PATH` inside GUI app env | App resolves `mr` at build; whitelist absolute path; fall back to a user-set path; provide env hint. |
| Long `mr stop` (transcription) blocks menu bar | Run stop async on a background queue; flip icon to idle immediately; completion via notification. |
| Editing TOML from Swift corrupts config | Recommended: route via `mr config set` in Python (validated + atomic) instead of Swift writing TOML directly. |
| Two language stacks (this is the same accepted tradeoff as `mr-capture`) | Swift only for the status-item UI; call CLI for all logic. |
| "Change location" beware of moving files | UI copy explicitly says only new sessions move; never migrate existing dirs automatically. |
| App Sandbox / entitlements blocking file access | Decide sandbox-need vs. non-sandboxed; test folder picker + CLI spawn under chosen mode. |

---

## 6. Phased steps (for a coding agent)

1. **Spike P0** — prove: `NSStatusItem` renders; TCC permission attribution works
   when launching capture from the app; `mr` callable from app env. (≈½ day)
2. **Python config write-back** — `mr/config.py::set_out_root` + `mr config set`
   CLI; unit tests; update `config.toml.example`/README.
3. **Python transcription heartbeat** — write/clear `transcribing.json` in
   `_do_stop` around the transcribe step; unit tests; used by the menu bar for the
   dropdown list (see §4.5 B1).
4. **Swift menu-bar shell** — status item, menu, idle/live icon, Start/Stop via
   Process, async stop, background queue.
5. **Dropdown refresh (lazy)** — rebuild the icon state + "Transcribing" section by
   reading pidfile + `transcribing.json`, **only when the menu opens** (no polling).
6. **Storage location** — `NSOpenPanel` + persist via `mr config set out_root`.
7. **Package/configure** — app bundle, `LSUIElement`, Info.plist, entitlements.
8. **Manual + simulated test** — reuse docs/manual-test-conversation pattern for the
   menu bar drive; verify done-bar criteria.

---

## 7. Out of scope (explicit)
- Moving existing recordings/transcripts when out_root changes.
- Group calls, live transcription into the bar, speaker names.
- Windows/Linux. Agent integration. Summaries (per Project Goal).

---

## 8. Open decisions (defaults underlined for the coder)
1. **Async stop UX — RESOLVED:** icon flips to idle immediately; active
   transcription tasks are listed in a **"Transcribing" section in the dropdown**
   (see §4.5). __Default: Option B1 (heartbeat file Python writes), rendered on
   dropdown open — no polling.__
2. **Refresh model — RESOLVED:** **lazy — compute icon state + transcription list
   only when the user opens the dropdown; no background timer.**
3. **`mr` lookup:** bundle a wrapper that resolves `~/.local/bin/mr` /
   `pyproject` console script; __default: resolve via shutil.which + explicit error menu item.__
4. **Sandboxed or not:** __default: non-sandboxed for v1.1__ (matches capture helper;
   revisit if distributing via App Store).
5. Whether storing the chosen folder should be a per-user override vs. editing the
   shared `config.toml`. __default: edit shared config.toml (single source of truth).__
6. **Heartbeat file path + `max_age`** for the transcription list's stale-sweep
   (see §4.5). __default: `<out_root>/.state/transcribing.json`; `max_age` ≈ 5 min.__