# examples/manual — scripted simulated-conversation test assets

Short reference for the manual test scripts in this directory.

> **Canonical production test:** see
> [`docs/simulated-test-production.md`](../docs/simulated-test-production.md)
> for the full step-by-step flow using the production `mr toggle` CLI.

## Scripts

| Script | Purpose |
|---|---|
| `prep_clips.sh` | Builds the 5 per-line Them-side TTS WAVs (`them_1..5.wav`) in `spike/out/manual/` using macOS `say` (Samantha voice, 16 kHz mono LEI16). Run once: `bash examples/manual/prep_clips.sh`. The assets are gitignored; rebuild only if `them_1.wav` is missing. |
| `play_timed.sh` | Timed playback of `them_1..5.wav` with "Your turn" prompts between lines (line 3 overlaps — you speak while Alex speaks, exercising echo dedup). Run in a second terminal during a recording: `bash examples/manual/play_timed.sh`. Ctrl-C stops early. |
| `verify_transcript.py` | Automated PASS/FAIL verdict for Step 3 of the simulated test: parses the attributed transcript `.md` (both speakers present, timestamps in non-decreasing order, no full-echo duplicate) and, with `--recording <dir>`, checks `meta.json` has non-zero `samples_written` for mic and system. Run: `./spike/.venv/bin/python examples/manual/verify_transcript.py <transcript.md> [--recording <recording_dir>]`. Exit 0 = PASS, 1 = FAIL, 2 = error. A demo fixture is at `fixtures/sample_transcript.md`. |
| `driver.py` | **DEPRECATED** — the old in-process pipeline driver (`transcribe → merge → render` on a captured dir). Superseded by the production CLI: `mr stop` (or `mr toggle` to stop) now does transcribe + merge + write `~/Meetings/transcripts/<stamp>.md` and posts the notification. Kept for historical reference only; do not use for new tests. |

## Recommended production record flow (summary)

1. `bash examples/manual/prep_clips.sh` (if assets missing)
2. `./spike/.venv/bin/python -m mr.cli toggle` (start recording — human, in Terminal)
3. Second terminal: `bash examples/manual/play_timed.sh`, speaking the "You" lines at the prompts
4. `./spike/.venv/bin/python -m mr.cli toggle` (stop → transcribes → writes the `.md`)
5. `./spike/.venv/bin/python -m mr.cli status` (confirms no active recording)

Full details, scripts inline, verification checklist, and reporting checklist:
`docs/simulated-test-production.md`.
