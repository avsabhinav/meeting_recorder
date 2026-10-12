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
| P1.2 | `schema.py` dataclasses (Segment, Word, TranscriptionResult, CaptureMeta) | done | P1.1 |
| P1.3 | `output.py` .md + optional JSON writer (+ tests) | done | P1.2 |
| P1.4 | `merge.py` segment sort + echo dedup (+ tests w/ fixtures) | done | P1.2 |
| P1.5 | `transcribe.py` Transcriber + MlxWhisperTranscriber + ModelNotCachedError (+ tests w/ mock) | done | P1.2, P1.1 |
| P1.6 | `capture.py` Python wrapper: spawn/signal `mr-capture`, read `meta.json` | done | — |
| P1.7 | `cli.py` with subcommand `process` (mic+system wav → .md) | done | P1.3..P1.6 |
| P1.8 | P1 integration: `mr process` on scripted WAV data | done | P1.7 |
| **PAUSE** | **Manual test: scripted conversation → capture (spike binary) → production transcribe+merge+output → attributed .md review** | **done** | P1.1..P1.5 |

### Epic P2 — Capture + control (Phase 2)
| id | Task | Status | Depends |
|----|------|--------|---------|
| P2.1 | Productionize `capture/` (top-level Swift pkg, build.sh, Info.plist, install) | done | — |
| P2.2 | `config.py` TOML config (outdir, model, language, dedup_threshold) | done | P1.1 |
| P2.3 | `state.py` pidfile + recording state | done | P1.1 |
| P2.4 | `cli.py` start/stop/toggle/status/doctor | done | P1.6, P2.1..P2.3 |
| P2.5 | Completion notification (osascript) on stop→transcribe | done | P2.4 |
| P2.6 | README + hotkey (Shortcuts/Raycast) + permissions docs, LICENSE | done | P2.4 |
| P2.7 | End-to-end simulated conversation test (play scripted system audio; user replies) → verified attributed .md | in-progress | P2.4, P2.6 |

## Open / next — ALL ENGINEERING TASKS DONE ✅
- **Manual test PASSED** (2026-10-12): pipeline works end-to-end on real hardware
  (`docs/manual-test-result.md`). Attribution + echo handling correct; speed ~15–63× realtime.
- **Phase 1 Core COMPLETE + Epic P2 COMPLETE (this session, HEAD `8a49418`):**
  - P1.6 `capture.py` RecordSession; P1.7 `cli.py process`; P1.8 integration.
  - P2.1 `capture/` Swift package (top-level, `com.local.mr-capture`); P2.2 `config.py`;
    P2.3 `state.py` pidfile; P2.4 `cli start/stop/toggle/status/doctor`; P2.5 osascript notify;
    P2.6 README + permissions/troubleshooting docs; P2.7 production simulated-conversation test doc.
  - Real `mr toggle`-style capture → transcribe → attributed `.md` VERIFIED end-to-end (P2.4).
  - **99 tests pass; ruff clean.** Working tree clean.
- **Remaining (HUMAN user, real hardware):** run the live simulated-conversation test in
  `docs/simulated-test-production.md` (play scripted Them audio via `play_timed.sh`, speak You
  lines, `mr toggle` start/stop) → validate attribution/echo/hallucination + the `.md`. Then the
  project (Phase 1 + Phase 2, `mr toggle` goal) is verifiably complete.
- **Session handoff:** `docs/checkpoint.md` is the single resume guide (update for new commits).
