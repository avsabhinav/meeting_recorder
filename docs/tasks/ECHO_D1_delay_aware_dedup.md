TASK: ECHO/D1 Make the echo dedup delay-aware so delayed "You" echoes of "Them" audio are dropped (no new dependencies)
GOAL: The current merge-time dedup only drops a "You" segment if it TIME-OVERLAPS a "Them" segment. But acoustic speaker echo is a DELAYED copy: the mic records the system audio ~`echo_lag` seconds after it was played, so the echoed "You" segment trails its "Them" original and never overlaps it — it survives as a false "You." Add a delay-aware check: a "You" segment that textually matches a "Them" segment AND follows it within the mic↔system stream-offset window (`echo_lag`) is treated as an echo and dropped. This uses NO new dependencies (just the existing `fuzz.token_ratio` + timestamps).
CONTEXT: Repo root `/Users/abhinavademmagari/Documents/Projects/meeting recorder` (note the space). Real sample confirmed: `/Users/abhinavademmagari/Documents/Meetings mr/recordings/2026-10-13_1334` — the echoed "You" segments have token_ratio >= 90% vs a "Them" segment that starts ~8.3–9.4 s earlier; the genuine "testing" "You" is 43% similar and precedes any "Them." The mic↔system stream offset (`echo_lag`) is `system.first_sample_seconds - mic.first_sample_seconds` from `meta.json` (≈ +9.34 s here). `merge_transcripts` (mr/core/merge.py) currently takes `(you, them, *, dedup_threshold=0.6)` and is PURE (no file I/O); the CLI computes the offset and passes it in.
FILES: create/modify ONLY `mr/core/merge.py`, `mr/cli.py`, `tests/test_merge.py`
READ FIRST: `mr/core/merge.py` (whole, 75 lines) — esp. `_is_echo` (lines 28-49) and `merge_transcripts` (52-74). Then `mr/cli.py` `_transcribe_and_write` (lines 82-114) — it calls `merge_transcripts(...)` and has `out_dir` (the recording dir containing `meta.json`). Then `tests/test_merge.py` (whole, 123 lines) for test style.
STEPS:
1. `mr/core/merge.py`:
   a. Add a module constant `_ECHO_LAG_TOLERANCE_S = 0.75` (the slack beyond `echo_lag` that a real echo may drift).
   b. Change `_is_echo` signature to `_is_echo(you, them, threshold_pct, echo_lag_s)`. Keep the EXISTING overlap check unchanged (it must still run; it covers concurrent echoes). ADD a delay-aware check:
      ```python
      # Delayed acoustic echo: the mic records the system audio `echo_lag_s`
      # seconds after it played, so the echoed You segment follows (not
      # overlaps) its Them original by roughly that offset.
      if echo_lag_s is not None and echo_lag_s >= 0:
          lag = float(echo_lag_s) + _ECHO_LAG_TOLERANCE_S
          if you.start >= them.start and (you.start - them.start) <= lag:
              return True
      ```
      Place this inside the same loop where the token_ratio >= threshold check already gates (i.e., only applies to a matched Them segment that already passes the similarity check). Do NOT remove the existing `_overlap_duration >= 0.05` return-True path.
   c. Change `merge_transcripts(you, them, *, dedup_threshold=0.6, echo_lag_s=None)` and pass `echo_lag_s` through to `_is_echo`. `echo_lag_s=None` means "no delay-aware dedup" (pure/backward-compatible). Keep the existing input-validation (`dedup_threshold` in [0,1]) and the "inputs not mutated" guarantees.
2. `mr/cli.py` — in `_transcribe_and_write`, compute the offset from `meta.json` in the recording dir and pass it to `merge_transcripts`. Add at the merge call site:
   ```python
   echo_lag = _system_vs_mic_offset(out_dir)   # seconds (None if unavailable)
   merged = merge_transcripts(list(you.segments), list(them.segments),
                              dedup_threshold=cfg.dedup_threshold,
                              echo_lag_s=echo_lag)
   ```
   Add a small private helper near `_transcribe_and_write`:
   ```python
   def _system_vs_mic_offset(out_dir: str) -> float | None:
       """Seconds by which the system (speaker) stream lags the mic stream's start,
       from meta.json (mic.first_sample_seconds vs system.first_sample_seconds).
       None when meta.json is missing/unparseable or lacks the fields. This is the
       approximate acoustic-echo delay to use for delay-aware dedup."""
       try:
           meta = json.loads((Path(out_dir) / "meta.json").read_text(encoding="utf-8"))
           m, s = meta["mic"], meta["system"]
           return float(s["first_sample_seconds"]) - float(m["first_sample_seconds"])
       except (OSError, KeyError, ValueError, TypeError):
           return None
   ```
   Ensure `json` is imported in `cli.py` (check; add `import json` at top if missing). Note the offset can be positive (system starts later → mic echo trails system) or negative (system already playing when mic starts, e.g. the echo pre-existed). Only use it when it's >= 0 (the guard in step 1b); when negative, `_is_echo`'s `echo_lag_s >= 0` guard already disables delay-aware dedup, so passing a negative value is safe.
   - `_transcribe_worker` calls `_transcribe_and_write`, so it inherits the fix (background path also gets it).
3. `tests/test_merge.py` — add cases. Use the existing `seg(...)` helper:
   - `test_delayed_you_echo_dropped_when_follows_them_within_lag`: You "Washington DC ..." @ 12.0-18.0, Them "Washington DC ..." @ 3.0-9.0, `merge_transcripts(you, them, dedup_threshold=0.6, echo_lag_s=9.0)` → only Them survives.
   - `test_delayed_you_echo_kept_without_echo_lag`: SAME inputs WITHOUT `echo_lag_s` → both survive (backward compat; no meta).
   - `test_genuine_you_kept_when_low_similarity_even_with_lag`: You "testing 1 2 3 hello" @ 3.0-11.0, Them "Washington DC ..." @ 3.14-9.38, `echo_lag_s=9.0` → You kept (low token ratio).
   - `test_delayed_you_echo_beyond_lag_kept`: You "same words here" @ 25.0-30.0, Them "same words here" @ 1.0-5.0, `echo_lag_s=5.0` → You kept (offset 24 > 5+0.75), i.e. too far to be this stream's echo.
   - `test_existing_overlap_echo_still_dropped_with_echo_lag`: You "we should ship on friday" @ 0.0-2.0, Them "we should ship on friday" @ 1.0-3.0, `echo_lag_s=9.0` → dropped (overlap rule still applies; You precedes Them but overlaps).
   Verify the two existing tests `test_you_echo_dropped_when_similar_and_overlapping` and `test_you_echo_dropped_even_if_them_starts_later` still pass with `echo_lag_s=None` (unchanged behavior).
ACCEPTANCE:
1. `cd "meeting recorder" && ./spike/.venv/bin/python -m pytest tests/ -q` → green (existing + new). `./spike/.venv/bin/ruff check mr tests` → clean.
2. Real-data check: `./spike/.venv/bin/python - <<'PY'` script (run from repo root) that loads `/Users/abhinavademmagari/Documents/Meetings mr/recordings/2026-10-13_1334/meta.json`, computes `_system_vs_mic_offset` ≈ +9.34, and calls `merge_transcripts` with the hardcoded You/Them segments from that clip (see CONTEXT) + `echo_lag_s=9.34` → ONLY the genuine "testing" You segment survives; the 4 echoed "You" ("washington dc", "in real time", "impressive gemini", "claims first") are dropped. Print the surviving You texts.
3. `git diff` touches ONLY `mr/core/merge.py`, `mr/cli.py`, `tests/test_merge.py`.
OUT OF SCOPE: the full transcription validation (I'll run transcribe+merge end-to-end separately after dispatch), AEC/DSP libraries, the Swift capture (SystemTap/MicCapture), changing timestamps/streams, README/docs (only if the user then approves; do not touch docs).
REPORT: reply with STATUS, FILES CHANGED, VERIFICATION (pytest tail + ruff + the real-data survival check output + the `_is_echo` hunk), and NOTES.