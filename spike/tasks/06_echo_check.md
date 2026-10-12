# Task 6 — `echo_check.py` (text-overlap echo scoring)

> Throwaway spike. Fresh context; do only this. When done write
> `spike/tasks/06_echo_check.SUMMARY.md` and reply REPORT (STATUS/FILES/VERIFICATION/NOTES).

## Context
We want to know whether "You" lines contain remote-party speech leaked into
the mic (echo) on **laptop speakers**. We already have transcript JSON produced
by `transcribe.py`:
- `<dir>/mic.segments.json` and `<dir>/system.segments.json`:
  ```json
  { "track":"mic","speaker":"You","audio_seconds":60.0,
    "segments":[ {"start":0.0,"end":2.1,"text":"hello"} ] }
  ```
- Speakers track = `system` → "Them", mic track = `You`.
- Env: `spike/.venv` (has numpy, rapidfuzz, soundfile).

## Scope — create `spike/echo_check.py`
CLI: `echo_check.py <dir>` (reads both `*.segments.json` in `<dir>`).
For each **`You`** segment, if it **overlaps in time** with any **`Them`**
segment (overlap > 0), compute the token-ratio similarity between that You
segment's text and the overlapping Them segment's text using
`rapidfuzz.fuzz.token_ratio`. A high ratio = suspicious echo.

Report:
1. Total `You` segments, `Them` segments.
2. Number of overlapping You segments, and # flagged as likely echo at
   thresholds 0.5 / 0.6 / 0.7 (a You segment is flagged if **any** overlapping
   Them segment's similarity exceeds the threshold; take the max).
3. Print 5–10 example pairs above the 0.5 threshold: `(start,You_text | Them_text → ratio)`.
4. Print a one-line suggestion: recommended threshold to minimize You-lines-
   containing-remote-speech, given observed ratios (just an opinionated
   heuristic summary, no ML).
5. Also print, for contrast: max similarity per You segment statistics
   (mean / p90) so the reader sees distribution.

Handle missing/empty JSON gracefully (cheap click-records will have few segments).

## Self-check
- Build a tiny synthetic case: craft two small segments JSON in `$TMPDIR`
  where one You segment text exactly equals a Them segment text (ratio→100)
  and another is clearly different (ratio low). Run `echo_check.py` on that
  dir and confirm the identical pair is flagged, the different pair is not.
- Put the command + output in your SUMMARY.

## Non-goals
- No transcription, no AEC, no modifying other files, no writing output files
  (print to stdout only).

## Deliverable
- `spike/echo_check.py`
- `spike/tasks/06_echo_check.SUMMARY.md`
- Nothing else.

## When done
Reply REPORT with STATUS, FILES CHANGED, VERIFICATION, NOTES.