# Menu-Bar App Manual Test (Epic MB)

> **⚠️ This test requires a human at a Mac with a mic and speakers — a recording will be started.**
> **Do not run it in an automated or headless context.** The menu-bar app must be clicked
> by a person (it has no CLI surface for the actions under test), and the start/stop
> steps (Steps 3–4) must be performed on a real Mac with a working mic and speakers.

This is the **manual verification for the menu-bar app (`Oatmeal`)**, the UI front-end
for Epic MB. The CLI it drives (`mr`) is already covered by the production test in
[`docs/simulated-test-production.md`](simulated-test-production.md) — this doc is
specifically about the **app**: its menu-bar icon, its dropdown actions, and the
first-run permissions that now attach to *the app* rather than to a Terminal.

`Oatmeal` is a thin shell around the `mr` CLI. It **only shells out to `mr`** (it never
spawns `mr-capture` and never reads/writes the config or state files itself) and
**never polls** — the menu and icon are rebuilt only each time you open the menu
(`NSMenu` `menuWillOpen`), so a state change (recording, transcription) shows up the
moment you click the icon, not on a timer.

## What this validates

End-to-end, the done-bar for the menu-bar app:

1. **Icon in the menu bar** — the menu-bar icon **changes with state**: it is the `icon-white`
   **template glyph** when idle (not recording) and swaps to the distinct full-color
   `icon-recording` glyph while recording, so it clearly reads "recording" and a user knows to
   click it to stop. The OS also shows its own **orange recording indicator**. The **stale-pidfile → idle**
   case must read as idle (a leftover state file with a dead pid must never leave a "recording"
   cue behind).
2. **Start Recording** — spawns a capture identical to the CLI `mr start` (same
   `mr-capture`, same two-track recording) and the menu-bar icon **swaps to the full-color
   `icon-recording` glyph** (the OS's separate orange recording indicator also appears).
3. **Stop Recording & Transcribe** — triggers the `mr stop`-equivalent; transcription
   runs; the **macOS completion notification** fires when the transcript is written;
   and the OS recording indicator clears **immediately** on stop — *not* after transcription
   finishes (a 1–3 min transcription must never leave a recording cue behind).
4. **Transcribing: section** — while a transcription is in flight, opening the menu
   shows a disabled **Transcribing:** section with the session `stamp — transcribing…`;
   it is absent before and clears once the transcript is done.
5. **Change Storage Location…** — updates `out_root` so a **new** recording lands in
   the new root, and existing files are **not moved** (the confirmation copy says so).
6. **First-run TCC permissions** — Microphone + System Audio Recording are granted with
   the **app** (launched from the menu bar) as the responsible process — attribution to
   `Oatmeal`, not to a Terminal or a keyboard shortcut.

## Setup / prerequisites

All commands run from the repo root (`meeting recorder/`).

1. **Build + install the app** (MB-SW4):

   ```sh
   cd menu-bar && ./install.sh
   ```

   This produces `menu-bar/.build/Release/Oatmeal.app` (the release binary + `Info.plist`
   with `LSUIElement` and the usage strings, adhoc-signed). To keep it out of the
   build tree, **drag the `.app` into `/Applications`** (or just launch it in place).

2. **Make `mr` reachable.** The app resolves the CLI two ways, in this order
   (`AppInfo.mrCandidates`): **(1)** `mr` on `PATH`, then **(2)** the `MR_PYTHON`
   environment variable pointing at a Python that can run `-m mr.cli`. It has **no**
   other fallback — if neither works, every action row is disabled and a greyed-out
   `mr CLI not found (set MR_PYTHON)` row appears. Pick one:

   - **(a) `mr` on `PATH`** (recommended — simplest): `pip install -e .` (the README
     quickstart's `pip install -e ".[dev]"` also works; it just adds dev extras). Now
     `which mr` succeeds and the app finds it with no env setup.
   - **(b) `MR_PYTHON`** (no install): point it at a venv that has the package
     importable, e.g. the repo spike venv: `export MR_PYTHON="$PWD/spike/.venv/bin/python"`.
     This env must be **present in the app's environment at launch** — so launch the
     **binary directly** with it set (see below), not via a Dock/`open` icon, because a
     GUI launch does not reliably forward a shell's `export`ed variables.

   **Launch the app for this test** (binary directly, so the env is inherited):

   ```sh
   # From the repo root, with option (b):
   MR_PYTHON="$PWD/spike/.venv/bin/python" \
     menu-bar/.build/Release/Oatmeal.app/Contents/MacOS/Oatmeal &
   # ...or, if you chose (a) and `mr` is on PATH, just:
   open menu-bar/.build/Release/Oatmeal.app
   ```

   (If you see the disabled `mr CLI not found (set MR_PYTHON)` row, you are here — fix
   the environment per the two options above and relaunch before continuing.)

3. **Model cached** (one-time, needs network) and **helper built**, per the P2.7
   prerequisites:

   ```sh
   bash capture/build.sh                              # the mr-capture helper
   ./spike/.venv/bin/python -m mr.cli doctor --fetch-model   # cache the Whisper model
   ./spike/.venv/bin/python -m mr.cli doctor                 # should show helper + model cached
   ```

4. **Permissions:** grant **Microphone** + **System Audio Recording** to the
   **responsible process**. When launched from the menu bar, that is the app itself
   (not a Terminal). See [docs/permissions-troubleshooting.md](permissions-troubleshooting.md)
   and the [README](../README.md) *Permissions* section for how to grant, re-grant, and
   confirm the capture actually has audio.

## Steps

### Step 1 — launch, icon, and initial menu

1. Launch the app (Step 2 of the setup).
2. **Confirm the menu-bar icon (the `icon-white` template glyph, idle state) appears** in the
   menu bar (top-right, with the other status icons) — and that **no Dock icon** appears
   (`LSUIElement` / `.accessory`).
3. **Click the icon.** The dropdown should show, in order:
   - **Start Recording** — enabled (grey text) when idle.
   - **Stop Recording & Transcribe** — disabled when idle.
   - **no** `Transcribing:` section (nothing is transcribing).
   - **no** `mr CLI not found (set MR_PYTHON)` row — if it is there, the CLI is not
     resolvable; go back to setup step 2, fix the environment, relaunch, and re-check.
   - a separator, then **Change Storage Location…**, then **Open Folder ▸** (with
     **Recordings** / **Transcripts**), a separator, and **Quit**.
4. **Expectation:** Start enabled, Stop disabled, no Transcribing section, no "not
   found" row. If Start/Stop are both disabled *and* the "not found" row is present,
   the app cannot reach `mr`.

### Step 2 — Change Storage Location to a scratch dir

1. Click **Change Storage Location…**.
2. In the panel, choose a **scratch** directory (e.g. `~/Meetings-dev`, or a fresh
   folder under `/tmp`). The panel's message reads:
   *"New recordings & transcripts will go here. Existing files are NOT moved."*
3. Confirm. An informational alert should appear: **"Storage location updated."** with
   *"Recordings and transcripts for NEW sessions go to: <new-root>"* and
   **"Existing files were not moved."**
4. Verify the config actually changed (in a terminal, using whichever `mr` is
   reachable): `mr config get out_root` → the new root.

   > **Why a scratch dir:** so the test's recordings/transcripts don't pollute your
   > real `~/Meetings`. Restore `out_root` to `~/Meetings` afterwards (or via the menu).

### Step 3 — Start Recording (and cross-check the CLI)

1. Open the menu → **Start Recording**.
2. **Start recording.** The menu-bar icon **swaps to the full-color `icon-recording`
   glyph** (the OS also shows its orange recording indicator near Control Center). The menu
   should now show **Stop enabled / Start disabled** on the next open.
3. **Cross-check** from a terminal that a real capture is running and identical to the
   CLI path: `mr status` → `recording: yes` (with a `pid`, `out_dir` under the scratch
   root, and a `stamp`).
4. While recording, **speak a few words** (You) and play a short **test tone or a
   spoken line from the speakers** (Them) so both tracks capture audio — the same
   mic + system-audio case the CLI test exercises.

### Step 4 — Stop, watch the icon, and watch the Transcribing section

1. Open the menu → **Stop Recording & Transcribe**.
2. **The menu-bar icon swaps back to the `icon-white` template glyph, and the OS recording
   indicator clears, immediately** — *before* transcription finishes. This is the key MB behavior: a
   long (1–3 min) transcription must not keep a recording cue showing.
3. **Within a few seconds**, open the menu again: a **Transcribing:** section should be
   visible — a disabled header `Transcribing:` with a line like
   `<stamp> — transcribing…`. (It reads the `<out_root>/.state/transcribing.json`
   heartbeat, fresh within 300 s.)
4. **Wait for the macOS notification** — title `mr`, body
   `Recording "<stamp>" transcribed -> <stamp>.md` — posted when the transcript is
   written.
5. Once notified, open the menu again: the **Transcribing:** section should be **gone**
   (heartbeat now stale/absent), and Start/Stop back to idle state.

### Step 5 — verify the transcript landed in the NEW root

1. The transcript should be at `<scratch-root>/transcripts/<stamp>.md` (NOT the old
   root).
2. Run the verifier (as in the P2.7 test) on the new transcript + its recording dir:

   ```sh
   ./spike/.venv/bin/python examples/manual/verify_transcript.py \
     "<scratch-root>/transcripts/<stamp>.md" --recording "<scratch-root>/recordings/<stamp>"
   ```

   Expect `OVERALL: PASS` (both speakers present, timestamps in order, both tracks
   non-silent).
3. Open the `.md` and eyeball **You / Them attribution** and `MM:SS` timing, as in the
   P2.7 verification.

### Step 6 — Open Folder ▸ Transcripts

1. Open the menu → **Open Folder ▸ Transcripts**.
2. **Finder should open the scratch root's `transcripts/` folder** — and you should see
   the `<stamp>.md` you just verified. (If the subfolder didn't exist, the app opens
   the root instead; if neither exists it says the folder is created on first use.)
3. **Open Folder ▸ Recordings** should likewise open `<scratch-root>/recordings/`.

### Step 7 — reuse, and switch storage back

1. **Repeat Start → Stop once more** to confirm the app reuses cleanly across sessions
   (icon live → idle, Transcribing section appears/clears again, notification fires).
2. **Change Storage Location…** back to `~/Meetings`.
3. Confirm a **new** session now lands in `~/Meetings/…`, while the earlier scratch
   files remain in the scratch root **untouched** (not moved, not deleted).

### Step 8 — first-run permission attribution

If this is your first run of the app, the **Microphone** and **System Audio
Recording** TCC prompts should appear **when the app starts a capture** (Step 3) —
i.e. attributed to **`Oatmeal`** (or the `mr-capture` helper it launches), **not** to a
Terminal or a keyboard shortcut. Note which app each prompt names. If a prompt was
denied, re-grant per
[docs/permissions-troubleshooting.md](permissions-troubleshooting.md) and restart the
capture. (This is the *new* thing the menu-bar path changes: the responsible process
is the menu-bar app, so a previously-allowed Terminal grant may not carry over.)

## Done bar

- [ ] `icon-white` template glyph appears in the menu bar; **no Dock icon** (`LSUIElement`).
- [ ] Icon **is `icon-white` (template) when idle and swaps to the full-color `icon-recording`
      glyph while recording** (the OS also shows its orange recording indicator);
      **stale-pidfile reads as idle** — no lingering recording cue.
- [ ] **Start Recording** spawns a real capture (identical to CLI `mr start`); the menu-bar
      icon swaps to `icon-recording`; `mr status` shows `recording: yes`.
- [ ] **Stop** triggers `mr stop`-equivalent; **the menu-bar icon swaps back to `icon-white`
      immediately**, not after the 1–3 min transcription.
- [ ] **macOS notification** (`Recording "<stamp>" transcribed -> <stamp>.md`) fires
      when the transcript is written.
- [ ] **Transcribing:** section appears (with `stamp — transcribing…`) while transcribing
      and **clears** when done.
- [ ] **Change Storage Location** updates `out_root`; a **new** recording lands in the
      new root; **existing files are not moved** (confirmation copy says so).
- [ ] **Open Folder ▸ Recordings / Transcripts** open the correct folders in Finder.
- [ ] **First-run TCC** (Microphone + System Audio Recording) granted, attributed to the
      app (`Oatmeal`/helper), not a Terminal/shortcut.
- [ ] Transcript at the new root passes `verify_transcript.py` (You/Them + timing).

## What to report

Mirror the P2.7 report, plus the menu-bar specifics:

- The transcript `.md` content (paste or link) and `verify_transcript.py`'s
  `OVERALL:` line.
- `meta.json` `samples_written` for **both** tracks (mic + system) and the capture
  duration — confirms the app's capture actually recorded audio.
- **Icon behavior:** the menu-bar icon swapping from `icon-white` to `icon-recording` on
  start and back on stop (**immediately**, before the transcript finishes), plus the OS
  recording indicator appearing/clearing.
- **Transcribing: section:** did it appear with the stamp, and did it clear when done?
- **Notification:** did the macOS `Recording … transcribed -> …` notification appear?
- **Permission-prompt attribution:** for each TCC prompt, *which app* it named
  (`Oatmeal` vs helper vs Terminal/shortcut), and whether any were denied.
- Exit codes of each `mr` command the app ran (all should be `0`; a one-off `3` only
  if the model wasn't yet cached).
- Any **attribution, echo, or hallucination** issues in the transcript — quote the
  offending lines.
- Whether **Open Folder** opened the expected folder (or the "created on first use"
  alert), and whether switching `out_root` back left the scratch files untouched.

## Cross-references

- [`docs/architecture.md`](architecture.md) — overall design, including the
  transcription-heartbeat contract the Transcribing: section reads.
- [`docs/permissions-troubleshooting.md`](permissions-troubleshooting.md) — granting,
  re-granting, and confirming the two TCC permissions.
- [`README.md`](../README.md) — the `mr` CLI reference, configuration, and the
  *Permissions* and *Output layout* sections.
- [`docs/simulated-test-production.md`](simulated-test-production.md) — the production
  CLI test this menu-bar test complements.
