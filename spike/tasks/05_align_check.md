# Task 5 — `align_check.py` (offset/drift between mic & system tracks)

> Throwaway spike. Fresh context; do only this. When done write
> `spike/tasks/05_align_check.SUMMARY.md` and reply REPORT (STATUS/FILES/VERIFICATION/NOTES).

## Context
- Two 16 kHz mono s16le WAVs `mic.wav` and `system.wav`. `system` = tapped
  output (the remote party / whatever plays out of the speakers); `mic` =
  microphone. A called "click" at the start and end lands in BOTH tracks
  (acoustically into mic, directly into system tap).
- Env: `spike/.venv` (has numpy, scipy, rapidfuzz, soundfile). Use
  `spike/.venv/bin/python`.
- Goal: measure start **offset** `system_start - mic_start` and **drift**
  over the recording, using cross-correlation on the two broadband-aligned
  signals, plus a print of any `meta.json` first-sample times for comparison.

## Scope — create `spike/align_check.py`
CLI: `align_check.py <dir> [--probe N]`
1. Load `mic.wav`,`system.wav` (soundfile, float32), 16 kHz. Common length =
   min lengths.
2. Normalize each (subtract mean) and find lag via windowed cross-correlation.
   Implementation guide (fine to follow exactly):
   - Divide the common range into **3 windows** (start / middle / end), each
     ~1/3 of the audio. In each window, cross-correlate a shorter probe
     (e.g. 1 s) of `mic` against `system` using `scipy.signal.correlate`
     (`mode="valid"`) and take `argmax` → lag in samples.
   - Report `offset_ms` at window start, plus drift between start and end
     windows in ms and in samples/s (drift rate).
   - Fall back gracefully: if a window is all silence in both (e.g. small
     speech), print "low-confidence window" and skip rather than crash.
3. If `<dir>/meta.json` exists, print its first_sample_seconds for both tracks
   and the resulting offset for comparison.
4. Print a small report, e.g.:
   ```
   offset_start_ms = 12.3
   offset_end_ms   = 14.1
   drift_ms_over_call = 1.8   (drift_rate = 0.002 ms/s → 3.6 ms over 30 min)
   meta.json first-sample offset_ms = 11.0
   ```

## Self-check
- Generate a synthetic pair to prove the math: delay a short audio clip (e.g.
  `say -o` then afconvert to 16k wav, or numpy white noise) by a known offset
  (e.g. 0.200 s = 3200 samples) and confirm `align_check.py` recovers ~ the
  known offset. Simpler: write a tiny numpy array, save both, run, print.
- Include the command + recovered value in your SUMMARY.

## Non-goals
- No transcription, no echo metrics, no edits to other files, no model use.

## Deliverable
- `spike/align_check.py`
- `spike/tasks/05_align_check.SUMMARY.md`
- Nothing else.

## When done
Reply REPORT with STATUS, FILES CHANGED, VERIFICATION, NOTES.