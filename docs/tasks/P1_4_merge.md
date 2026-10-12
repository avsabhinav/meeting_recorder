# TASK: P1.4 — Implement `mr/core/merge.py` (sort + echo dedup)

TASK: P1/1.4 Implement `mr/core/merge.py`: interleave You/Them segments by time and
remove echoed `You` segments that duplicate concurrent `Them` audio.

GOAL: A pure function `merge_transcripts(you, them, *, dedup_threshold=0.6) -> list[Segment]`
that returns a chronological, deduplicated list of `Segment`s ready for `output.py`.
This is the always-on safety net that corrects whatever residual echo the OS AEC leaves.
Fully unit-tested with realistic fixtures.

CONTEXT:
- Workspace root (WITH spaces): `/Users/abhinavademmagari/Documents/Projects/meeting recorder`.
- `mr.core.schema` (P1.2): `Segment(speaker, text, start, end, words=())`, frozen.
  `speaker` is "You" or "Them". Import from `mr.core.schema`.
- `rapidfuzz` is a declared dependency (`rapidfuzz>=3.0`); `from rapidfuzz import fuzz`.
- Conventions: Python 3.12+, dataclasses, ruff E,F,I,UP, line-length 100.
- Python binary: `./spike/.venv/bin/python` (rapidfuzz installed there).
- Time intervals are half-open `[start, end)` seconds.

Algorithm (implement exactly):
1. **Echo detection:** For each `You` segment, find any `Them` segment that
   **time-overlaps** it (i.e. `a.start < b.end and b.start < a.end`, with a small
   tolerance: treat overlap as true if overlap duration >= 0.05 s). If ANY overlapping
   `Them` segment has `fuzz.token_ratio(you.text, them.text) >= dedup_threshold*100`,
   drop the `You` segment as echo.
   - Compare on stripped text; if either text is empty/whitespace, skip (no echo).
2. **Sorting:** Return the surviving segments in chronological order by `start`.
   For equal `start` times, order `Them` before `You` (stable tie-break), then by `text`.

Signature:
```python
def merge_transcripts(
    you: list[Segment],
    them: list[Segment],
    *,
    dedup_threshold: float = 0.6,
) -> list[Segment]:
    """Merge You/Them segments; drop echoed You segments; return chronological list."""
```
- `dedup_threshold` is in `[0, 1]` range. It may be None → treat as 0.6.
- The input lists must not be mutated (return a new list; leave inputs untouched).
- Do NOT modify segment objects; the frozen dataclass prevents that anyway.

Edge cases to handle & test:
- A `You` segment that overlaps `Them` but is NOT similar (a real interruption) → KEPT.
- A `You` segment with empty text → kept (not crossed out); don't crash.
- No overlap at all → all kept, sorted.
- Two `You` or two `Them` segments that overlap each other → no interaction (only
  You-vs-Them cross-stream echo is considered).
- Identical start for a You and Them segment → Them sorts first.
- `dedup_threshold=1.0` → only exact textual matches dropped (token_ratio==100).

FILES (create ONLY):
- `/Users/abhinavademmagari/Documents/Projects/meeting recorder/mr/core/merge.py`
- `/Users/abhinavademmagari/Documents/Projects/meeting recorder/tests/test_merge.py`

READ FIRST:
- `/Users/abhinavademmagari/Documents/Projects/meeting recorder/mr/core/schema.py` (`Segment`).
- `/Users/abhinavademmagari/Documents/Projects/meeting recorder/spike/echo_check.py`
  (reference: the spike's echo-scoring approach + its overlap() helper).
- `/Users/abhinavademmagari/Documents/Projects/meeting recorder/docs/architecture.md`
  (decision #2 echo philosophy).

STEPS:
1. Create `mr/core/merge.py` with `merge_transcripts` implementing the algorithm above.
2. Use `fuzz.token_ratio` (range 0–100); compare against `dedup_threshold*100`.
3. Write `tests/test_merge.py` with the edge cases listed, using `Segment` fixtures:
   - echo dropped (You text ≈ Them text, overlapping);
   - real interruption kept (different text);
   - empty-text You kept, no crash;
   - non-overlapping sorted chronologically;
   - same-start tie → Them before You;
   - inputs not mutated (assert original list unchanged after call);
   - dedup_threshold=1.0 → only exact matches dropped.
ACCEPTANCE (from repo root):
- `./spike/.venv/bin/python -m pytest tests/test_merge.py -q` → all pass.
- `./spike/.venv/bin/python -m ruff check mr/core/merge.py tests/test_merge.py` → clean.
- `./spike/.venv/bin/python -c "from mr.core.merge import merge_transcripts; print('OK')"` → imports.

OUT OF SCOPE: No transcription, no output writing, no words-level handling. Do not modify
schema.py or output.py. Do not touch other files.

REPORT: reply with STATUS, FILES CHANGED, VERIFICATION (pytest + ruff output), NOTES.