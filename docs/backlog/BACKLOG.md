# MR Backlog — Production Build (Phase 1 → Phase 2)

> Single source of truth for the production `mr` build. Lead (CTO agent) maintains
> this file and the mirrored `todo_write`. Statuses: `todo → in-progress → review →
> done | blocked | failed`. Each row = one focused task dispatched via `dev_task`.
> Briefs live in `docs/tasks/<epic>_<n>_<slug>.md`; workers reply with STATUS/FILES/
> VERIFICATION/NOTES. **Do not change shared contracts without updating dependents.**

## Context / state

- Phase 0 spike **GO** (`spike/SPIKE_RESULTS.md`): capture (system process tap via
  aggregate+IOProc, mic via AVAudioEngine+VPIO AEC), mlx-whisper local GPU
  (`large-v3-turbo`), echo handling (AEC on is primary; rapidfuzz token-ratio text
  dedup is the always-on safety net), alignment ~1.4 ms, speed ~7× realtime,
  no hallucinations with locked settings.
- Locked settings (from spike): `language=en, word_timestamps=True,
  condition_on_previous_text=False, no_speech_threshold=0.6,
  hallucination_silence_threshold=0.0`; model `mlx-community/whisper-large-v3-turbo`;
  offline cache-only via standard HF hub cache (`HF_HUB_OFFLINE=1`).
- **Spike item #9 (real 45-min call) substituted** by user decision: validate with a
  short **simulated conversation** (play scripted system audio; user replies with a
  provided script) instead of a 45-min call. Real-meeting validation tomorrow.
- Repo is NOT yet a git repo. Plan doc: `PLAN.md`. Spike: `spike/`.

## Paths / naming

- Production package at repo root (working dir = `meeting recorder/`).
- `mr/` Python package (cli, config, state, core/), `capture/` Swift package,
  `tests/`, `examples/`, `docs/`, `pyproject.toml`, `LICENSE`, `README.md`.
- Output: `~/Meetings/recordings/<stamp>/` (wavs+meta) + `~/Meetings/transcripts/<stamp>.md`.
- State: `~/Meetings/.state/`. Config: `~/.config/mr/config.toml`.

## Shared contracts (LOCKED — dependents assume these)

**Segment block** (both transcribe & merge use this):
```python
@dataclass Segment: text: str; start: float; end: float; speaker: str  # "You"|"Them"
```
Word-level detail: `Segment.words: list[Word]` optional (`word,start,end,probability`).

**Transcriber** (`mr/core/transcribe.py`):
```python
def transcribe_audio(path: str, *, speaker: str, model: str, language: str) -> TranscriptionResult
class TranscriptionResult: track, speaker, model, audio_seconds, wall_seconds, settings, segments: list[Segment]
```
Raises `ModelNotCachedError` if model absent and offline.

**merge** (`mr/core/merge.py`):
```python
def merge_transcripts(you: list[Segment], them: list[Segment], *, dedup_threshold: float=0.6) -> list[Segment]
```
Sorted by start (tie: Them before You, then by text). Echo dedup: drop a `you` segment
when it time-overlaps a `them` segment and rapidfuzz token_ratio ≥ threshold*100.

**Capture meta** (`meta.json` from `mr-capture`): keys
`macos_version,aec,started_at,duration_seconds,mic:{device_name,native_sample_rate,
native_channels,first_sample_seconds,samples_written},system:{...}`.

**Swift contract:** `mr-capture --out <dir> [--no-aec]` → runs until SIGINT/SIGTERM,
writes `mic.wav`, `system.wav` (16 kHz mono s16le, incremental) + `meta.json`, exit 0.

**Transcript .md format** (`mr/core/output.py`): header `# Meeting — <stamp>`,
`- Duration`, `- Participants: You (mic), Them (system)`, `- Source`, `## Transcript`,
then `**You (MM:SS):** …` / `**Them (MM:SS):** …` chronologically.

## Epics / Tasks (execution order)

### Epic P1 — Core Python (Phase 1)
| id | Task | Status | Depends |
|----|------|--------|---------|
| P1.1 | Scaffold package (pyproject, ruff, pytest, `mr/`+`mr/core/` dirs, git init, LICENSE, README stub, config.toml.example) | done | — |
| P1.2 | `schema.py` dataclasses (Segment, Word, TranscriptionResult, CaptureMeta) | in-progress | P1.1 |
| P1.3 | `output.py` .md + optional JSON writer (+ tests) | todo | P1.2 |
| P1.4 | `merge.py` segment sort + echo dedup (+ tests w/ fixtures) | todo | P1.2 |
| P1.5 | `transcribe.py` Transcriber + MlxWhisperTranscriber + ModelNotCachedError (+ tests w/ mock) | todo | P1.2, P1.1 |
| P1.6 | `capture.py` Python wrapper: spawn/signal `mr-capture`, read `meta.json` | todo | — |
| P1.7 | `cli.py` with subcommand `process` (mic+system wav → .md) | todo | P1.3..P1.6 |
| P1.8 | P1 integration: `mr process` on scripted WAV data | todo | P1.7 |

### Epic P2 — Capture + control (Phase 2)
| id | Task | Status | Depends |
|----|------|--------|---------|
| P2.1 | Productionize `capture/` (top-level Swift pkg, build.sh, Info.plist, install) | todo | — |
| P2.2 | `config.py` TOML config (outdir, model, language, dedup_threshold) | todo | P1.1 |
| P2.3 | `state.py` pidfile + recording state | todo | P1.1 |
| P2.4 | `cli.py` start/stop/toggle/status/doctor | todo | P1.6, P2.1..P2.3 |
| P2.5 | Completion notification (osascript) on stop→transcribe | todo | P2.4 |
| P2.6 | README + hotkey (Shortcuts/Raycast) + permissions docs, LICENSE | todo | P2.4 |
| P2.7 | End-to-end simulated conversation test (play scripted system audio; user replies) → verified attributed .md | todo | P2.4, P2.6 |

## Open / next
- After P2.7, hand simulated-conversation script + capture instructions to user;
  user validates capture on a real meeting tomorrow.
