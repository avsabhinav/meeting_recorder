# Architecture Note — Production `mr` build

Documents the production architecture and the decisions carried over from the
Phase 0 spike. The spike code and the Phase 0 planning docs (`PLAN.md`,
`PHASE0_SPIKE.md`, and the original spike investigation/results) are archived out
of this repo in a sibling `meeting-recorder-archive/` directory; this note is the
canonical in-repo record of the design.

## Stack (locked)
- **Python 3.12+** core (package `mr/`) + **Swift** capture helper (one binary `mr-capture`).
- Python deps: `mlx-whisper`, `typer`, `soundfile`, `rapidfuzz`. Dev: `pytest`, `ruff`.
  Dataclasses (no pydantic). TOML config only.
- Swift: system frameworks only; macOS 14.2+, Apple Silicon.

## Module map
```
mr/
  cli.py          # typer app: start|stop (async transcribe)|toggle|process|status|doctor
  config.py       # load ~/.config/mr/config.toml
  state.py        # pidfile / recording state (~/Meetings/.state)
  core/
    schema.py     # Segment, Word, TranscriptionResult, CaptureMeta
    transcribe.py # Transcriber protocol + MlxWhisperTranscriber (mlx-whisper)
    merge.py      # interleave You/Them by time + echo dedup (rapidfuzz)
    output.py     # .md + optional JSON
    capture.py    # Python wrapper: spawn/signal mr-capture, read meta.json
capture/          # SwiftPM package -> mr-capture binary
tests/            # core unit tests; transcriber mocked
examples/demo/    # sample aligned WAVs + generated .md
```

## Design decisions carried from the spike
1. **Capture reality:** the Core Audio process tap is read via a **private aggregate
   device + IOProc** (not AudioQueue). Voice processing (VPIO) was **removed** — a
   real call showed it degraded audio (the spike originally noted VPIO input, AEC on,
   reports **9 channels** with user voice on **channel 0**); the mic is now a
   **raw 1-channel tap**. Keep the spike gotchas (INVESTIGATION.md) as
   comments/README.
2. **Echo philosophy:** capture is **RAW** (no voice processing by design, so
   recording never degrades an active call); the merge-time **text-overlap dedup**
   (rapidfuzz token_ratio ≥ `dedup_threshold`, default 0.6, over time-overlap) is
   the **sole** echo handling.
3. **Model handling:** load by HF repo id only so `mlx-whisper`/`huggingface_hub`
   use the **standard HF hub cache**; never a custom cache_dir. At call time run
   **cache-only** (`HF_HUB_OFFLINE=1`, `local_files_only`). Pre-fetch + report via
   `mr doctor`. If model absent → `ModelNotCachedError` with a clear message.
4. **Deterministic attribution:** mic→`You`, system→`Them` (stream origin). No LLM.
5. **Settings locked** (from spike): `language=en, word_timestamps=True,
   condition_on_previous_text=False, no_speech_threshold=0.6,
   hallucination_silence_threshold=0.0`; drop empty-text segments.
6. **State ownership:** the CLI owns recording state via a pidfile in `~/Meetings/.state`.
   The future menu-bar app calls CLI/core; never records independently.
7. **Meeting context (calendar):** transcripts carry an **Obsidian YAML
   frontmatter** block rather than prose — the target audience keeps Obsidian
   vaults and queries properties (`title`, `date`, `attendees`, `notes`,
   `duration`, `source`). Context is captured **at start time**: the menu-bar
   app (planned, EventKit — not shipping yet) hands the event to
   `mr start --context-json <path>`, which persists `meeting_context.json`
   into `recordings/<stamp>/`; the detached background transcriber reads it
   later, so the transcriber never needs calendar access. EventKit access is
   owned entirely by the menu-bar app, never by the Python core.

## Pipeline for one recording
1. `mr toggle` (idle) → `mr start` → spawn `mr-capture --out ~/Meetings/recordings/<stamp>`
   → write pidfile. `mr start` may also take `--context-json <path>`: it
   validates the file as parseable JSON and persists the raw text as
   `recordings/<stamp>/meeting_context.json` so the (detached) transcriber can
   find it later.
2. `mr toggle` (active) → `mr stop` → SIGINT `mr-capture` → finalized WAVs + meta.json
   → clear the recording pidfile → spawn a **detached background `mr _transcribe`
   process and return immediately** (a new recording can start right away).
3. Background `mr _transcribe` writes the `transcribing.json` heartbeat, then
   `transcribe` both tracks (sequential) → `TranscriptionResult`s.
4. `merge_transcripts(you, them, dedup_threshold=0.6)` → sorted, deduped segments.
5. `output` → `~/Meetings/transcripts/<stamp>.md` (+ optional JSON sidecar).
   If `recordings/<stamp>/meeting_context.json` exists (loaded by
   `_transcribe_and_write`), the `.md` gets an **Obsidian YAML frontmatter**
   block prepended — `title` (event title, fallback stamp), `date` (event
   start, fallback today), `attendees` (flow list, omitted if empty), `notes`
   (omitted if empty), `duration` (`<m>m <s>s`), `source` (`recordings/<stamp>/`)
   — and the JSON sidecar gains a `"context"` key with the raw dict. No context
   → output is identical to the plain path.
6. `osascript` completion notification, then clear the heartbeat.

## Verifiable acceptance (commands)
- `ruff check mr tests` clean; `pytest -q` green.
- `mr process --mic a.wav --system b.wav` → prints/emits `.md` with You/Them.
- `mr status` / `mr doctor` correct; `mr toggle` records then emits a transcript.
