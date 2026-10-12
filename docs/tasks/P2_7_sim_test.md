TASK: P2.7 Update the scripted simulated-conversation test to the production `mr` CLI

GOAL: Refresh the scripted simulated-conversation test so it validates the **production
`mr toggle`** end-to-end flow (record via `mr toggle` → auto-transcribe → attributed `.md` →
notification), instead of the older spike-binary + in-process driver approach. Produce the
scripted Them-side TTS assets, update the guide to drive `mr toggle`, and verify the assets +
commands work. NOTE: the actual recording requires the human user (play scripted audio, speak
replies); your job is to make the scenario reproducible and the guide accurate. A real live
record SHOULD NOT be started by you.

CONTEXT:
- Repo: `meeting recorder/` (space in path — quote paths).
- The production CLI is built and works (P2.4): `mr toggle [--aec/--no-aec]` starts or stops +
  transcribes; `mr status`; `mr doctor`; output `~/Meetings/transcripts/<stamp>.md`. The helper
  is built at `capture/.build/release/mr-capture` (P2.1). Config at `~/.config/mr/config.toml`
  (P2.2). Run the CLI with `./spike/.venv/bin/python -m mr.cli <cmd>` (the package isn't
  installed as a `mr` console script in this repo checkout).
- The OLD manual test (`docs/manual-test-conversation.md`) uses the spike binary +
  `examples/manual/driver.py`. That flow is superseded by `mr toggle` + `mr stop`. Keep the old
  file (historical), but create a PRODUCTION update so the user runs the real CLI.
- Existing timed-playback assets:
  - `examples/manual/prep_clips.sh` — builds 5 per-line Them WAVs (`them_1..5.wav`) via `say`.
  - `examples/manual/play_timed.sh` — plays them timed with "Your turn" prompts.
  - `examples/manual/driver.py` — OLD in-process pipeline driver (mic.wav/system.wav → .md via
    transpcribe+merge+output). Deprecate it in the new guide (note it's superseded by `mr stop`).
- Scripted scenario (from the old guide): Them side = a product-review chat played from speakers
  (lands in system.wav AND acoustically in mic.wav → the echo case); You speak lines aloud.

FILES (create/modify only):
- `docs/manual-test-conversation.md` (EDIT — add a "Production CLI version (P2.7)" section, or
  better: create `docs/simulated-test-production.md`) — choose the cleaner option: a new file
  `docs/simulated-test-production.md` that is the canonical production test, and add a pointer
  from the old file. Keep edits minimal.
- `examples/manual/README.md` (CREATE — short note describing each script + the production flow)
- Do NOT modify `examples/manual/*.sh` / `driver.py` unless strictly needed (they still work for
  the old flow; leave them).

READ FIRST:
1. `docs/manual-test-conversation.md` — the old scenario + steps to mirror.
2. `examples/manual/prep_clips.sh`, `play_timed.sh`, `driver.py` — what exists.
3. `mr/cli.py` — exact `toggle`/`stop`/`status` behavior + exit codes (lines ~258-311).
4. `README.md` — the hotkey/permissions sections to reference.
5. `docs/checkpoint.md`, `docs/backlog/BACKLOG.md` — current status.

STEPS:
1. Create `examples/manual/README.md` — short reference: `prep_clips.sh` (build Them audio),
   `play_timed.sh` (timed playback with prompts), `driver.py` (DEPRECATED — superseded by
   `mr stop`), and the recommended **production** record flow (steps below).
2. Create `docs/simulated-test-production.md` — the canonical production simulated test:
   - **What it validates**: the production `mr toggle` end-to-end record → transcribe → attributed
     `.md` → notification, with a controllable scripted conversation (so attribution is checkable).
   - **Prereqs**: helper built (`capture/build.sh`), model cached (`mr doctor --fetch-model` once),
     `mr doctor` shows helper + model-cached yes.
   - **Step 1 — assets**: `bash examples/manual/prep_clips.sh` (builds 5 Them WAVs into
     `spike/out/manual/`). Or use the pre-built ones if present.
   - **Step 2 — record (Terminal, human user)**: run
     `./spike/.venv/bin/python -m mr.cli toggle --no-aec` (or default AEC). In a SECOND Terminal
     run `bash examples/manual/play_timed.sh` and speak the "You" lines in the prompts. After the
     last prompt, `./spike/.venv/bin/python -m mr.cli toggle` (stop) — it transcribes and writes
     `~/Meetings/transcripts/<stamp>.md`. NOTE: use a scratch `out_root` by temporarily editing
     `~/.config/mr/config.toml` (e.g. `out_root = "~/Meetings-dev"`) so the test doesn't pollute
     the real Meetings tree IF desired; mention this option.
   - **Step 3 — verify**: open the `.md`; check You/Them interleaved in time order, correct
     attribution (no swaps), no full echo duplicate (dedup removed it — note the overlap line 3),
     no hallucinations; `mr status` confirms no active recording after stop.
   - **Step 4 — what to report**: transcript content, `meta.json` `samples_written` for both
     tracks, whether the osascript notification appeared, any permission prompt behavior.
   - Include the full Them script (5 lines) and You script (5 lines) inline so it's self-contained.
   - Mark clearly: **"This test requires a human to speak and play audio — a recording will be
     started; do not run this in an automated/headless context."**
3. Add a one-line pointer from the top of `docs/manual-test-conversation.md`: "→ Production CLI
   version: see `docs/simulated-test-production.md`".
4. Verify (without doing a real recording): `bash -n examples/manual/prep_clips.sh
   examples/manual/play_timed.sh` (syntax check); confirm `spike/out/manual/them_1.wav` exists
   (pre-built) or that prep_clips would build it; and sanity-run
   `./spike/.venv/bin/python -m mr.cli doctor` to confirm the env is ready. If `them_1.wav` is
   absent and `say` is available, run `prep_clips.sh` to build them (this is safe — it only
   creates WAVs, no recording).

ACCEPTANCE:
- `docs/simulated-test-production.md` exists and is self-contained (scripts inline).
- `examples/manual/README.md` exists.
- `docs/manual-test-conversation.md` has a pointer to the new file.
- `bash -n examples/manual/prep_clips.sh examples/manual/play_timed.sh` → no syntax errors.
- `./spike/.venv/bin/python -m mr.cli doctor` runs (env ready: helper + model-cached).
- `git diff --stat` shows only docs/ + examples/manual/README.md changes (no code changes).

OUT OF SCOPE:
- Do NOT start a real recording (that's the human user's step). Do NOT record mic/system audio.
- Do NOT modify `mr/`, `capture/`, `tests/`, `pyproject.toml`, or the `.sh`/`driver.py` scripts.
- Do NOT rewrite history / delete the old manual-test file.
- Do NOT commit (CTO agent owns git).

REPORT: reply with STATUS, FILES CHANGED, VERIFICATION (commands + output), NOTES.