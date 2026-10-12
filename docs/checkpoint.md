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
- 42 tests pass. Repo is a **git repo** on branch `main` (HEAD `ef0b6b5`).
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

Git history (`main`): `b5c5033→a01e44a→0e3abcb→91854be→4bbbe73→ef0b6b5`.

## ⏸ PAUSE — manual test the USER must run (NEXT)

Everything below is waiting on the user to record + run the driver. Then dispatch P1.6 onward.

From `docs/manual-test-conversation.md` (scripted Alex/design conversation):
1. **Window 1:** `spike/capture/.build/release/mr-capture --out spike/out/manual \
   --no-aec`** (⚠ on MacOS the `\` line-continuation inside a single command line is fine only in a shell;
   in a GUI Terminal type it as one line: `spike/capture/.build/release/mr-capture --out spike/out/manual`).
   — note: use the default AEC (omit `--no-aec`) unless you prefer raw mic; the script covers both.
2. **Window 2:** play `spike/out/manual/them.m4a` (loop it) while you read the `You` lines in the pauses.
3. **Stop** with Ctrl-C in window 1.
4. **Run:** `./spike/.venv/bin/python examples/manual/driver.py spike/out/manual`
5. Report back: `transcript.md` contents, `meta.json`, whether the mic-permission prompt appeared,
   and whether AEC/echo-ducking behaved.

This surfaces the real TCC mic-permission behavior (unverified from a real Terminal/Shortcuts).

## Next tasks (sequential, ONE dev_task at a time)

Briefs are ready in `docs/tasks/`:
- **P1.6** `mr/core/capture.py` — `RecordSession` context manager spawning `mr-capture`
  (env override `MR_CAPTURE_BIN`; default `spike/capture/.build/release/mr-capture`), forwards
  SIGINT/SIGTERM, parses `meta.json` → `CaptureMeta`. (brief + tests ready)
- **P1.7** `mr/cli.py` — `typer` app with `process --mic --system [--json] [--dedup-threshold]`
  subcommand; edits `pyproject.toml` to add `[project.scripts] mr = "mr.cli:app"`. (brief + tests ready)
- **P1.8** P1 integration: run `mr process` on scripted WAV data end-to-end.
- **Epic P2** (capture + control): P2.1 productionize `capture/` Swift; P2.2 `config.py`;
  P2.3 `state.py` pidfile; P2.4 `cli.py` start/stop/toggle/status/doctor; P2.5 notification;
  P2.6 README+hotkey+permissions docs; P2.7 end-to-end simulated test.

> **Dispatch discipline:** strictly ONE worker at a time; briefs in `docs/tasks/`; verify every result
> yourself (`git diff --stat` + acceptance commands) before marking done; workers never commit — the
> CT O-agent owns git. After 2 failed attempts → re-split; then escalate via `subagent`.

## Immediate next action (this session only document — not yet executed)

P1.6 worker was cancelled at dispatch; nothing from it was written. `BACKLOG.md` currently shows P1.6
`in-progress` — **revert to `todo`** in a fresh session, since P1.6 is not started.

Open git items at checkpoint:
- `docs/tasks/P1_6_capture.md`, `docs/tasks/P1_7_cli.md` (new, untracked, ready)
- `docs/backlog/BACKLOG.md` modified (mark P1.6 in-progress — revert to `todo` before commit)

## Goal

Persisted goal (id `goal-060369c5-874a-4881-a2ab-2ad26be9c6ab`, rev 2) is **paused/disarmed**.
The user must resume it (or it re-arms when a "continue" request arrives in a new session).
Objective: build Phase 1 Core + Phase 2 Capture/control so `mr toggle` records + transcribes +
writes an attributed .md under `~/Meetings`.
