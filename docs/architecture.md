# Architecture Note — Production `mr` build

Ties the Phase 0 spike findings to the production architecture (see `PLAN.md`,
`spike/SPIKE_RESULTS.md`, `spike/TASKBOARD.md`).

## Stack (locked)
- **Python 3.12+** core (package `mr/`) + **Swift** capture helper (one binary `mr-capture`).
- Python deps: `mlx-whisper`, `typer`, `soundfile`, `rapidfuzz`. Dev: `pytest`, `ruff`.
  Dataclasses (no pydantic). TOML config only.
- Swift: system frameworks only; macOS 14.2+, Apple Silicon.

## Module map
```
mr/
  cli.py          # typer app: start|stop|toggle|process|status|doctor
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

## Pipeline for one recording
1. `mr toggle` (idle) → `mr start` → spawn `mr-capture --out ~/Meetings/recordings/<stamp>`
   → write pidfile.
2. `mr toggle` (active) → `mr stop` → SIGINT `mr-capture` → finalized WAVs + meta.json.
3. `transcribe` both tracks (sequential) → `TranscriptionResult`s.
4. `merge_transcripts(you, them, dedup_threshold=0.6)` → sorted, deduped segments.
5. `output` → `~/Meetings/transcripts/<stamp>.md` (+ optional JSON sidecar).
6. `osascript` notification.

## Verifiable acceptance (commands)
- `ruff check mr tests` clean; `pytest -q` green.
- `mr process --mic a.wav --system b.wav` → prints/emits `.md` with You/Them.
- `mr status` / `mr doctor` correct; `mr toggle` records then emits a transcript.
