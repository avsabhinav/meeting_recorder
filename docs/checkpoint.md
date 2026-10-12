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
| P2.1 | `capture/` production Swift package (top-level, `com.local.mr-capture`, build.sh + install.sh); wrapper default → `capture/.build/release/mr-capture` |
| P2.2 | `config.py` — `load_config()` reads `~/.config/mr/config.toml` (tomllib), defaults + validation |
| P2.3 | `state.py` — pidfile `<out_root>/.state/recording.json`, atomic write, stale (`os.kill(pid,0)`) probe |
| P2.4 | `cli.py` — `start`/`stop`/`toggle`/`status`/`doctor [--fetch-model]` wired to config+state+capture; `_spawn_capture` keeps the child alive across commands (not RecordSession) |
| P2.5 | `notify_complete()` — fail-soft osascript macOS notification on stop/toggle |
| P2.6 | Full README (CLI ref, config, hotkey, permissions, troubleshooting) + `docs/permissions-troubleshooting.md` |
| P2.7 | `docs/simulated-test-production.md` (canonical `mr toggle` simulated test) + `examples/manual/README.md`; old driver deprecation noted |

Git history (`main`): `…920459a (PAUSE)→18bb7eb→7df890d→1e22195→bc229c9→daa22ae→1871fa9→a7f5119→dd085f9→409be11→8a49418`.

## Phase 1 + Epic P2 — ALL ENGINEERING TASKS DONE ✅

99 tests pass (`./spike/.venv/bin/python -m pytest tests/ -q`); `ruff check mr tests` clean;
working tree clean at `8a49418`.
Real end-to-end VERIFIED this session (P2.4): a real sparse capture via `_do_start` → ~4 s
mic+system → `_do_stop` → offline mlx-whisper transcribe → merge → correct You/Them `.md`
(`/tmp` scratch out_root). `mr doctor` on this Mac: macOS 27.0.1, helper
`capture/.build/release/mr-capture`, model cached.

## Remaining — HUMAN user, real hardware (the actual live recording)

The live **simulated-conversation test** needs a person to speak + play audio —
`docs/simulated-test-production.md` is the canonical guide. Steps: build assets
(`examples/manual/prep_clips.sh`), `mr toggle --no-aec` (Terminal 1),
`examples/manual/play_timed.sh` (Terminal 2) + speak the You lines, `mr toggle` (stop) →
verify `~/Meetings/transcripts/<stamp>.md` attribution/echo/hallucination + the notification.
Then `mr toggle` on a real 1:1 call validates the goal.

## Working notes for any future session

- Run CLI via `./spike/.venv/bin/python -m mr.cli <cmd>` (not the `mr` console script, which
  isn't installed in this checkout). Config at `~/.config/mr/config.toml`.
- P1.6 `mr/core/capture.py` exposes `RecordSession` + `assert_capture_bin()` + `CaptureResult`
  (used by integration); P2.4 `start`/`toggle` spawn via `_spawn_capture` (Popen) so the child
  outlives the short command.

> **Dispatch discipline:** strictly ONE worker at a time; briefs in `docs/tasks/`; verify every result
> yourself (`git diff --stat` + acceptance commands) before marking done; workers never commit — the
> CTO agent owns git. After 2 failed attempts → re-split; then escalate via `subagent`.
> Tests/lint always via `./spike/.venv/bin/python`.

## Goal

Persisted goal (id `goal-a31ff0fb-2837-4ed0-9df8-ed94375a6af1`) armed. Objective: continue the
meeting-recorder project — Phase 1 + Epic P2 so `mr toggle` records + transcribes + writes an
attributed .md under `~/Meetings`. **ALL engineering tasks done**; only the human-run live
simulated-conversation test remains (see above) to fully validate the goal.
