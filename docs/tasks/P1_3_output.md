# TASK: P1.3 — Implement `mr/core/output.py` (transcript .md + JSON writer)

TASK: P1/1.3 Implement `mr/core/output.py`: writers for the Markdown transcript and
optional JSON sidecar.

GOAL: Given a merged list of `Segment`s (chronological, from `merge.py`), write a clean
attributed `.md` transcript in the exact project format, and optionally a JSON sidecar.
Pure functions, fully unit-tested. No I/O beyond path writing helpers.

CONTEXT:
- Workspace root (WITH spaces): `/Users/abhinavademmagari/Documents/Projects/meeting recorder`.
- `mr.core.schema` exists from P1.2 with `Segment(speaker, text, start, end, words=())`
  and helper `format_ts(seconds) -> "MM:SS"`. Import these from `mr.core.schema`.
- Conventions: Python 3.12+, dataclasses (no pydantic), ruff E,F,I,UP, line-length 100.
- Python binary: `./spike/.venv/bin/python`.

Transcript `.md` format (exact — from PLAN.md §5 and the spike sample):
```
# Meeting — <stamp>

- **Duration:** <dur>   e.g. "42m 10s"
- **Participants:** You (mic), Them (system)
- **Source:** <source_dir>

## Transcript

**You (00:00):** hey, can you hear me ok?
**Them (00:02):** yeah, I hear you just fine.
```
- `<stamp>` is a string like `2026-08-24_1432` (YYYY-MM-DD_HHMM — pass it in; don't compute it here).
- `<dur>` formatting: if total_seconds < 60 → `"0m <s>s"` (e.g. `0m 45s`); else `"<m>m <s>s"`
  where `<s>` is `total_seconds % 60` (floor), and `<m>` is `total_seconds // 60`.
  Examples: `2530 -> "42m 10s"`, `45 -> "0m 45s"`, `3661 -> "61m 1s"`.
- Each line: `**{speaker} ({format_ts(start)}):** {text}`. One blank line between
  consecutive transcript lines. The transcript section header `## Transcript` is followed
  by one blank line, then the first `**...` line (no extra leading blank line).
- Timestamps use `mr.core.schema.format_ts`.

Module API (exact signatures):
```python
def render_transcript_md(
    *, stamp: str, source_dir: str, segments: list[Segment], duration_seconds: float,
) -> str:
    """Return the full .md text (as a single string ending with a newline)."""

def write_transcript(md_path: str | Path, text: str) -> None:
    """Write text to md_path (creates parent dirs)."""

def render_transcript_json(segments: list[Segment], *, stamp: str) -> dict:
    """Return a JSON-serializable dict with the transcript layout below."""

def write_json(json_path: str | Path, data: dict) -> None:
    """Write data to json_path, indent=2, an explicit trailing newline, utf-8."""
```
`render_transcript_md` must NOT depend on files — it's a pure function returning the string.
`write_transcript`/`write_json` are thin file helpers (accept `str` or `pathlib.Path`).

JSON sidecar layout (`render_transcript_json` returns):
```json
{ "schema_version": 1, "stamp": "<stamp>",
  "segments": [ {"speaker": "You", "start": 0.0, "end": 2.1, "text": "hello"}, ... ] }
```

FILES (create ONLY):
- `/Users/abhinavademmagari/Documents/Projects/meeting recorder/mr/core/output.py`
- `/Users/abhinavademmagari/Documents/Projects/meeting recorder/tests/test_output.py`

READ FIRST:
- `/Users/abhinavademmagari/Documents/Projects/meeting recorder/mr/core/schema.py`
  (`Segment`, `format_ts`).
- `/Users/abhinavademmagari/Documents/Projects/meeting recorder/PLAN.md` (§5 Transcript format).
- `/Users/abhinavademmagari/Documents/Projects/meeting recorder/spike/SPIKE_RESULTS.md`
  ("Sample output" section for reference).

STEPS:
1. Create `mr/core/output.py` implementing the five functions with exact signatures above.
   Import `Segment` and `format_ts` from `mr.core.schema`.
2. Implement duration formatting exactly as specified (floor minutes/seconds).
3. Implement JSON serialization returning plain dict/list with floats/strings only
   (json-safe).
4. Write `tests/test_output.py`:
   - `render_transcript_md` produces the exact Markdown (assert the full string equals a
     constructed expected string, including blank-line placement) for a 3-segment You/Them
     sequence.
   - Duration formatting cases: `2530 -> "42m 10s"`, `45 -> "0m 45s"`, `3661 -> "61m 1s"`.
   - `render_transcript_json` returns the expected dict.
   - `write_transcript`/`write_json` create parent dirs and correct file content
     (use `tmp_path` fixture), including the trailing newline.

ACCEPTANCE (from repo root):
- `./spike/.venv/bin/python -m pytest tests/test_output.py -q` → all pass.
- `./spike/.venv/bin/python -m ruff check mr/core/output.py tests/test_output.py` → clean.
- `./spike/.venv/bin/python -c "from mr.core.output import render_transcript_md, write_transcript, render_transcript_json, write_json"` → imports without error.

OUT OF SCOPE: No transcription, no merge, no CLI, no file-IO beyond the two helpers.
Do not modify `mr/core/schema.py`. Do not touch other files.

REPORT: reply with STATUS, FILES CHANGED, VERIFICATION (pytest + ruff output), NOTES.