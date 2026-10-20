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
   **raw tap, downmixed across all channels** to mono — the channel-0 pick was
   only valid for that VPIO layout, and on a stereo interface or aggregate
   device it yields silence or a half-signal. `MicCapture` and `SystemTap`
   downmix identically. Keep the spike gotchas (INVESTIGATION.md) as
   comments/README.
2. **Echo philosophy:** capture is **RAW** (no voice processing by design, so
   recording never degrades an active call); the merge-time **text-overlap dedup**
   (rapidfuzz token_ratio ≥ `dedup_threshold`, default 0.6, over time-overlap) is
   the **sole** echo handling. Echo is removed at **word** level, not segment
   level: `merge_transcripts` drops only the `You` words the speaker was saying
   concurrently (`Segment.words` timings vs the matching `Them` interval,
   widened by `_WORD_EDGE_TOLERANCE_S = 0.3` s). Whisper segments the two tracks
   on different boundaries, so one mic segment routinely straddles echoed
   speaker audio *and* the user's own words — segment-level handling therefore
   either deletes real speech (hiding the segment: on `2026-10-20_1553` every
   `You` segment was flagged and the transcript read as if the user never spoke)
   or duplicates the speaker's line (printing it: unreadable on a long meeting).
   A trimmed segment comes back with `echo_suspected=False` — what survives is
   genuine speech and needs no marker. A segment every word of which was echoed
   is dropped. Only a segment with **no word timings** cannot be trimmed; it is
   flagged and printed with a `*(possible echo)*` marker, never hidden. The edge
   tolerance exists because Whisper's word boundaries are approximate: a strict
   test left crumbs of the speaker's audio glued to genuine speech ("...let's
   see **and**", "**basis** okay that will end the recording"), all within 0.3 s
   of a boundary. Utterances under 4 words need near-exact similarity (95%)
   before they can match at all — two people saying "yeah" is conversation, not
   echo, and that guard keeps a lone short utterance out of trimming entirely. A
   delay-aware rule once widened matching to a ~10 s window using the mic/system
   `first_sample_seconds` difference; it was **removed**, because that difference
   measures tap-callback scheduling, not speaker→air→mic acoustic delay.
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
   app (EventKit; shipping) hands the event to
   `mr start --context-json <path>`, which persists `meeting_context.json`
   into `recordings/<stamp>/`; the detached background transcriber reads it
   later, so the transcriber never needs calendar access. EventKit access is
   owned entirely by the menu-bar app, never by the Python core. In the menu
   bar this surfaces as a "Start Recording from Calendar…" submenu (CAL-L1/L2/L3);
   the plain "Start Recording" item works with no calendar and everything
   degrades gracefully if Calendar permission is denied.

## Pipeline for one recording
1. `mr toggle` (idle) → `mr start` → spawn `mr-capture --out ~/Meetings/recordings/<stamp>`
   → write pidfile. `mr start` may also take `--context-json <path>`: it
   validates the file as parseable JSON and persists the raw text as
   `recordings/<stamp>/meeting_context.json` so the (detached) transcriber can
   find it later.
2. `mr toggle` (active) → `mr stop` → SIGINT `mr-capture` → finalized WAVs + meta.json
   → clear the recording pidfile → spawn a **detached background `mr _transcribe`
   process and return immediately** (a new recording can start right away).
   `_spawn_transcription` re-launches the *same* interpreter: in a source
   (venv) install it runs `[sys.executable, "-m", "mr.cli", "_transcribe", …]`,
   and in the **frozen** (PyInstaller) build — where `sys.executable` IS the
   `mr-cli` binary — it runs `[sys.executable, "_transcribe", …]` and must NOT
   prepend `-m mr.cli` (the frozen CLI treats `-m` as an unknown argument). Both
   spawn with `stdin=/dev/null`, **stdout+stderr appended to
   `recordings/<stamp>/.transcribe.log`**, and `start_new_session=True`, so the
   worker outlives `mr stop` and a worker that dies still leaves a traceback
   on disk. (An unwritable `out_dir` falls back to `/dev/null` rather than
   refusing to spawn — the log is a diagnostic, not a precondition.) The worker
   owns its own error reporting; see step 6.
3. Background `mr _transcribe` writes the `transcribing.json` heartbeat, then
   `transcribe` both tracks (sequential) → `TranscriptionResult`s.
3a. **Track alignment.** The mic and the system tap do not start together, and
   each WAV begins at its own first sample as if that sample were t=0 — so the
   two tracks share no timeline. `_stream_start_offsets(out_dir)` reads the two
   `first_sample_seconds` from `meta.json` and `shift_segments` pushes whichever
   stream started later forward by the delta (word timestamps move with their
   segment). Measured deltas: 0.98 s, 7.0 s, 10.5 s with the system tap late,
   0.09 s with the mic late. Without this the overlap-based echo rule never sees
   an echo and its original as concurrent, and speaker bleed lands under `You`.
   Missing or unparseable `meta.json` → `(0.0, 0.0)`: an unknown offset shifts
   nothing, because a wrong shift is worse than the misalignment.
4. `merge_transcripts(you, them, dedup_threshold=0.6)` → segments sorted
   chronologically, with echoed `You` **words** trimmed out (decision #2). A
   trimmed segment carries `echo_suspected=False` and tightened `start`/`end`;
   a wholly-echoed one is dropped; one with no word timings is returned
   `echo_suspected=True` for the writers in step 5 to mark. `Them` segments are
   never touched.
5. `output` → `~/Meetings/transcripts/<stamp>.md` (+ optional JSON sidecar).
   If `recordings/<stamp>/meeting_context.json` exists (loaded by
   `_transcribe_and_write`), the `.md` gets an **Obsidian YAML frontmatter**
   block prepended — `title` (event title, fallback stamp), `date` (event
   start, fallback today), `attendees` (flow list, omitted if empty), `notes`
   (omitted if empty), `duration` (`<m>m <s>s`), `source` (`recordings/<stamp>/`)
   — and the JSON sidecar gains a `"context"` key with the raw dict. No context
   → output is identical to the plain path. Trimmed segments reach the `.md` as
   ordinary lines (no marker — what survived trimming is genuine speech); the
   only lines carrying `*(possible echo)*` (`ECHO_MARKER` in
   `mr/core/output.py`) are segments that had no word timings to trim. The
   sidecar keeps whatever the merge returned, with `"echo_suspected": true` on
   those same untrimmable segments (the key is written only when true, so a
   recording with no suspected echo produces the same payload as before), and
   is the only artifact carrying word-level timings.
6. The worker clears the `transcribing.json` heartbeat in a `finally` (so it
   happens on the success path AND every failure path), then raises the
   `osascript` completion notification (fail-soft; never blocks or raises).
   **On failure** it writes `transcripts/<stamp>.FAILED.md` — naming the
   recording dir, the exception, the `.transcribe.log` path (only when that
   file exists: a hand-run `mr _transcribe` prints to the terminal instead and
   the stub must not point at a missing file), and the
   `mr _transcribe <stamp> <out_dir>` retry command — and exits non-zero (3 for
   `ModelNotCachedError`, 1 for anything else). The WAVs are **not** deleted on
   a failed run even when `keep_audio` is false, so a retry still has its audio;
   a later successful run removes the stale `.FAILED.md`. Before this, a crashed
   transcription was indistinguishable from a slow one: no transcript, no error,
   and a heartbeat that silently aged out.

## Production packaging (menu-bar + DMG)

The distributable is a self-contained `.app` inside a DMG, built by
`packaging/make_dmg.sh`:

- **Frozen CLI (PyInstaller):** `packaging/freeze_cli.sh` produces a onedir
  frozen `mr-cli` in `dist-freeze/mr-cli` (PyInstaller 6; collects `mlx`/
  `mlx_whisper`, and **excludes** `torch` and `torchgen`, which
  `--collect-all mlx` drags in transitively but this pipeline never imports —
  the only torch reference is `mlx_whisper/torch_whisper.py`, a
  weight-conversion helper nothing imports). Do **not** also exclude `numba` or
  `scipy`: `mlx_whisper/timing.py` imports both at module scope and
  `__init__.py -> transcribe.py -> timing.py` makes that unconditional, so
  excluding them freezes cleanly and then fails at transcription time with
  `ModuleNotFoundError`. `make_dmg.sh` **re-freezes from source first**, so a
  DMG can never embed a stale binary.
- **Self-contained app:** `menu-bar/install.sh` copies the frozen CLI tree into
  `Oatmeal.app/Contents/Resources/mr-cli/` and the `mr-capture` helper into
  `Oatmeal.app/Contents/Resources/mr-capture`, then adhoc-signs. The app resolves
  its own CLI (bundled frozen binary first, then `mr` on PATH, then
  `MR_PYTHON`) and sets `MR_CAPTURE_BIN` internally, so a bundled install needs
  no `PATH`/venv/`launchctl` wiring.
- Because the bundled app runs a *frozen* CLI, the frozen `_spawn_transcription`
  branch (pipeline step 2) is mandatory — shipping a frozen binary built before
  that branch existed was the root cause of the "recording saved but no
  transcript" bug.
- The DMG holds **only** `Oatmeal.app` + an Applications shortcut
  (`packaging/make_dmg.sh`, PKG-BUNDLE/5). See `docs/installing.md`.

## Verifiable acceptance (commands)
- `ruff check mr tests` clean; `pytest -q` green.
- `mr process --mic a.wav --system b.wav` → prints/emits `.md` with You/Them.
- `mr status` / `mr doctor` correct; `mr toggle` records then emits a transcript.
