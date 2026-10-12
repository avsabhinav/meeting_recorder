# TASK: P1.2 — Define schema dataclasses (`mr/core/schema.py`)

TASK: P1/1.2 Implement `mr/core/schema.py` with the shared data-model dataclasses.

GOAL: A single module defining the immutable, json-serializable dataclasses that every
other core module (transcribe, merge, output, capture) imports. This is the shared
contract of the whole project — get field names and types exactly right.

CONTEXT:
- Workspace root (WITH spaces): `/Users/abhinavademmagari/Documents/Projects/meeting recorder`.
- Package `mr` scaffolded in P1.1 (pyproject, ruff, pytest configured; `mr/core/` exists with an empty `__init__.py`).
- Conventions: Python 3.12+, dataclasses (NO pydantic), ruff with select E,F,I,UP, line-length 100.
- Python binary: `./spike/.venv/bin/python`.
- The dataclasses must round-trip cleanly through `json` (use `dataclasses.asdict` + types that json can serialize; keep them as simple scalar dataclasses).

Define exactly these types in `mr/core/schema.py`:

1. `@dataclass(frozen=True) Word`:
   - `text: str`  (the word text, may include a leading space as produced by Whisper)
   - `start: float`
   - `end: float`
   - `probability: float`

2. `@dataclass(frozen=True) Segment`:
   - `speaker: str`        # exactly "You" or "Them"
   - `text: str`
   - `start: float`
   - `end: float`
   - `words: tuple[Word, ...] = ()`  # optional word-level detail; empty default

3. `@dataclass(frozen=True) TranscriptionResult`:
   - `track: str`          # "mic" or "system"
   - `speaker: str`        # "You" for mic, "Them" for system
   - `model: str`
   - `audio_seconds: float`
   - `wall_seconds: float`
   - `settings: dict[str, object]`   # the mlx-whisper kwargs used
   - `segments: tuple[Segment, ...] = ()`

4. `@dataclass(frozen=True) StreamMeta` (per-stream capture metadata):
   - `device_name: str`
   - `native_sample_rate: int`
   - `native_channels: int`
   - `first_sample_seconds: float`
   - `samples_written: int`

5. `@dataclass(frozen=True) CaptureMeta`:
   - `macos_version: str`
   - `aec: bool`                     # True if voice-processing AEC was on
   - `started_at: str`               # ISO8601
   - `duration_seconds: float`
   - `mic: StreamMeta`
   - `system: StreamMeta`

Also provide these module-level helpers (same module):
- `def from_capture_dict(d: dict) -> CaptureMeta: ...` — parse the `meta.json` produced by
  `mr-capture` (see CONTEXT layout below) into a `CaptureMeta`, validating that `d["mic"]`
  and `d["system"]` exist and are dicts. Coerce numeric fields with `float()`/`int()` so a
  JSON number string is tolerated. Raise `ValueError` with a clear message if a top-level
  stream key is missing.
- `def format_ts(seconds: float) -> str: ...` — format a number of seconds as
  `MM:SS` (minutes zero-padded to 2, seconds zero-padded to 2, floor seconds; e.g.
  `format_ts(67.9) == "01:07"`). Minutes can exceed 99 (e.g. `format_ts(3660.5) == "61:00"`).

`meta.json` layout produced by `mr-capture` (parse via `from_capture_dict`):
```json
{ "macos_version": "27.0.1", "aec": true, "started_at": "<ISO8601>",
  "duration_seconds": 123.4,
  "mic":    {"device_name": "...", "native_sample_rate": 48000, "native_channels": 1,
             "first_sample_seconds": 1234.5678, "samples_written": 1974400},
  "system": { same keys } }
```

FILES (create ONLY):
- `/Users/abhinavademmagari/Documents/Projects/meeting recorder/mr/core/schema.py`

READ FIRST:
- `/Users/abhinavademmagari/Documents/Projects/meeting recorder/docs/architecture.md`
  (module map, contracts).
- `/Users/abhinavademmagari/Documents/Projects/meeting recorder/docs/backlog/BACKLOG.md`
  (§ Shared contracts).
- `/Users/abhinavademmagari/Documents/Projects/meeting recorder/spike/TASKBOARD.md`
  (real `meta.json` shape).

STEPS:
1. Create `mr/core/schema.py` with the five `@dataclass(frozen=True)` classes above.
   Order the file: imports → helper functions → dataclasses → `from_capture_dict` →
   `format_ts`. (Order within module is up to you; ensure no forward-reference issues,
   using `from __future__ import annotations` if convenient.)
2. Implement `format_ts` with floor math (see spec above).
3. Implement `from_capture_dict` returning a `CaptureMeta`, with clear `ValueError` on a
   missing `mic`/`system` key. Coerce numbers with `float()`/`int()`.
4. Write tests in `tests/test_schema.py`:
   - import + instantiate every dataclass with sample values.
   - `format_ts(0) == "00:00"`, `format_ts(67.9) == "01:07"`, `format_ts(3660.5) == "61:00"`.
   - `from_capture_dict` on a realistic meta dict round-trips to a `CaptureMeta` with equal
     field values; and raises `ValueError` when `"mic"` is missing.
   - `json.dumps(asdict(capture_meta), indent=2)` succeeds (json-serializable).
ACCEPTANCE (from repo root):
- `./spike/.venv/bin/python -m pytest tests/test_schema.py -q` → all pass.
- `./spike/.venv/bin/python -m ruff check mr/core/schema.py` → clean.
- `./spike/.venv/bin/python -c "from mr.core.schema import Segment, Word, TranscriptionResult, CaptureMeta, StreamMeta, from_capture_dict, format_ts" ` → imports without error.

OUT OF SCOPE: No transcribe/merge/output/capture logic. Do not modify `mr/core/__init__.py`
(leave it as-is). Do not touch any other file. Do not add dependencies.

REPORT: reply with STATUS, FILES CHANGED, VERIFICATION (pytest + ruff output), NOTES.
