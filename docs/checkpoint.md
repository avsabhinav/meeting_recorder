# MR — Session Checkpoint & Handoff (Phase 1 core DONE)

> Purpose of this file: let a **fresh session** pick the project up exactly where
> it stopped. It summarises the locked contracts, the PAUSE manual test the user
> must run, and the exact next tasks. Mirrors `docs/backlog/BACKLOG.md` (source of
> truth) and `PLAN.md`.

## Repo / conventions (re-confirm first)

- Working dir (HAS A SPACE): `/Users/abhinavademmagari/Documents/Projects/meeting recorder`
- Python interpreter for the project: `./spike/.venv/bin/python` (Python 3.12.13;
  has `mlx_whisper 0.4.3`, `soundfile`, `numpy`, `rapidfuzz`, `scipy`, `pytest 9`, `ruff 0.17`,
  and now `typer 0.27.3`). All unit/runtime checks use it.
- Test / lint: `./spike/.venv/bin/python -m pytest tests/ -q` · `./spike/.venv/bin/ruff check mr tests`
- 56 tests pass. Repo is a **git repo** on branch `main` (HEAD `7df890d`).
- Swift helper binary (Phase 1): `spike/capture/.build/release/mr-capture` (works, prints usage, exit 2).
- Model cached at `~/.cache/huggingface/hub/models--mlx-community--whisper-large-v3-turbo`
  (~1.61 GB) → offline transcription works now.

## Locked contracts (do not change without updating dependents)

- Segment: `dataclass Segment(speaker,text,start,end,words=())`, speaker exactly `"You"|"Them"`.
- `transcribe_audio(path, *, speaker, model=DEFAULT_MODEL, language="en") -> TranscriptionResult`
  (`mr/core/transcribe.py`); raises `ModelNotCachedError` if offline+not cached. Locked settings:
  `language=en, word_timestamps=True, condition_on_previous_text=False,
  no_speech_threshold=0.6, hallucination_silence_threshold=0.0`; model
  `mlx-community/whisper-large-v3-turbo`; offline cache-only at call time.
- `merge_transcripts(you, them, *, dedup_threshold=0.6) -> list[Segment]` (`mr/core/merge.py`).
- Output (`mr/core/output.py`): `render_transcript_md(*,stamp,source_dir,segments,duration_seconds)`,
  `render_transcript_json(segments, *, stamp)`, `write_transcript`, `write_json`, `SCHEMA_VERSION=1`.
- Capture meta: `from_capture_dict(d) -> CaptureMeta` (`mr/core/schema.py`).
- Swift contract: `mr-capture --out <dir> [--no-aec]` → runs until SIGINT/SIGTERM → writes
  `mic.wav`, `system.wav` (16 kHz mono s16le) + `meta.json`, exit 0.
- Transcribed `.md` format in §5 of `PLAN.md` / `output.py`.

## Completed (committed)

| Task | What |
|------|------|
| P1.1 | Scaffold: `mr/`, `mr/core/`, pyproject, ruff, pytest, LICENSE, README stub, config.toml.example |
| P1.2 | `schema.py` dataclasses (Segment, Word, TranscriptionResult, StreamMeta, CaptureMeta) + `from_capture_dict`, `format_ts` |
| P1.3 | `output.py` .md + JSON writers |
| P1.4 | `merge.py` segment sort + echo dedup (rapidfuzz overlap) |
| P1.5 | `transcribe.py` Transcriber + MlxWhisperTranscriber + ModelNotCachedError |
| —   | Manual-test setup: `docs/manual-test-conversation.md`, `examples/manual/driver.py`, `spike/out/manual/them.m4a` (TTS ~22 s) |
| **PAUSE** | Manual conversation test PASSED (`docs/manual-test-result.md`) — capture → transcribe → merge → attributed .md |
| P1.6 | `capture.py` — `RecordSession` context manager + `CaptureResult`; spawns/`os.kill`(SIGINT/SIGTERM)/waits on `mr-capture`, parses `meta.json` → `CaptureMeta`; env override `MR_CAPTURE_BIN`, default `spike/capture/.build/release/mr-capture` |
| P1.7 | `cli.py` — typer `app` + `process --mic --system [--json] [--dedup-threshold] [--model] [--language] [--stamp] [--out-dir]`; `ModelNotCachedError`→exit 3; `[project.scripts] mr = "mr.cli:app"`; adds `@app.callback()` to force multi-command mode |
| P1.8 | P1 integration: `mr process` end-to-end on scripted/real spike WAVs (offline) → attributed .md, dedup active |

Git history (`main`): `b5c5033→…→ef0b6b5→920459a (PAUSE)→18bb7eb (P1.6)→7df890d (P1.7)`.

## Phase 1 Core — DONE ✅

56 tests pass (`./spike/.venv/bin/python -m pytest tests/ -q`); `ruff check mr tests` clean.
Real integration verified this session:
`HF_HUB_OFFLINE=1 ./spike/.venv/bin/python -m mr.cli process --mic spike/out/manual/mic.wav --system spike/out/manual/system.wav --stamp p18 --out-dir /tmp/mr-p18`
→ correctly attributed You/Them `.md`, ~13 kept segments (echo dedup active). CLI help works via `python -m mr.cli --help` / `process --help`.

## Next tasks (Epic P2 — sequential, ONE dev_task at a time)

Briefs not yet written — write each in `docs/tasks/` before dispatch:
- **P2.1** Productionize `capture/` (top-level Swift pkg, build.sh, Info.plist, install) — drop real binary where `MR_CAPTURE_BIN`/default `spike/capture/.build/release/mr-capture` points, so P1.6 wrapper works unchanged.
- **P2.2** `config.py` TOML config (outdir, model, language, dedup_threshold) from `~/.config/mr/config.toml`.
- **P2.3** `state.py` pidfile + recording state under `~/Meetings/.state`.
- **P2.4** `cli.py` start/stop/toggle/status/doctor (extends the existing typer `app`; uses `RecordSession` + config + state).
- **P2.5** Completion notification (osascript) on stop→transcribe.
- **P2.6** README + hotkey (Shortcuts/Raycast) + permissions docs, LICENSE.
- **P2.7** End-to-end simulated conversation test (play scripted system audio; user replies) → verified attributed `.md`; then hand script+capture instructions to user for real-meeting validation.

Reminder on P1.6 wrapper for P2.4: `mr/core/capture.py` exposes `RecordSession(out_dir, *, aec=True, capture_bin=None)` as a context manager with `.returncode`/`.meta`/`.result()`, plus `assert_capture_bin()` and `CaptureResult`.

> **Dispatch discipline:** strictly ONE worker at a time; briefs in `docs/tasks/`; verify every result
> yourself (`git diff --stat` + acceptance commands) before marking done; workers never commit — the
> CTO agent owns git. After 2 failed attempts → re-split; then escalate via `subagent`.
> Tests/lint always via `./spike/.venv/bin/python`.

## Goal

Persisted goal (id `goal-a31ff0fb-2837-4ed0-9df8-ed94375a6af1`, rev 1, armed) with objective set
to: continue the meeting-recorder project — implement P1.6/P1.7/P1.8 (Phase 1 Core) then Epic P2 so
`mr toggle` records + transcribes + writes an attributed .md under `~/Meetings`. Phase 1 Core is done;
resume with **P2.1**.
