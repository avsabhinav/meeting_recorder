# Meeting Recorder — Project Plan (v2)

A local, privacy‑first macOS tool that records a 1:1 call (your mic **+** the
other side), transcribes it locally, and writes a clean **Markdown transcript**
attributing each line to *You* or *Them* — so other AI agents can consume it.

**Trigger:** a hotkey (bound via macOS Shortcuts / Raycast) runs `mr toggle`.
Stop → auto‑transcribe → `.md` saved → notification. Everything stays local.

**One job, done well:** faithful capture + transcription + attribution. No
summaries, no action items, no LLM — that's the agent's job (see `Project Goal.md`).

Open‑source, showcase‑grade: clean modules, tests, README, runnable demo.

> **v2 changes (after plan review):** speakers‑not‑headphones → echo handling is
> core v1; Apple Silicon (M5 Pro, 64 GB) → `mlx-whisper` on GPU; macOS 14.2+ →
> native Core Audio taps instead of BlackHole; menu‑bar app deferred to v1.1;
> a de‑risking **spike** now precedes scaffolding.

---

## 1. Locked decisions

| Decision | Choice | Why |
|---|---|---|
| Purpose | Personal tool, built as an **OSS showcase** | Clean, defensible code + docs. |
| Scope (v1) | **1:1 "You vs Them" only** | Simplest robust path; group calls deferred. |
| Attribution | **Stream origin**: mic = `You`, system = `Them` | Deterministic; no diarization, no token. |
| LLM in tool | **None** | Agent's job. Deterministic, private. |
| System capture | **Core Audio process taps** (macOS 14.2+) via a small **Swift helper** | No virtual device, volume keys keep working, no BlackHole setup. |
| Mic capture | Same Swift helper, **voice‑processing I/O (AEC) on** | Speaker use is common → OS echo cancellation on the mic. |
| Echo fallback | **Text‑overlap dedup** in merge (always on) | Drops `You` segments that duplicate concurrent `Them` text. Covers AEC gaps. |
| Transcription | **`mlx-whisper`, `large-v3-turbo`** (Metal), behind a `Transcriber` interface | 30–60 min calls ≈ 1–2 h audio; GPU path is fast + more accurate. `faster-whisper` stays a swappable backend for non‑Mac later. |
| Model storage | **Standard Hugging Face hub cache** (`~/.cache/huggingface/hub`, honors `HF_HOME` / `HF_HUB_CACHE`); never a custom/app‑private copy | Reuses models the user already has → no duplicate multi‑GB downloads. |
| VAD | **On** (skip silence before transcribing) | Prevents Whisper hallucinations on the long silences in each stream. |
| Merge unit | **Segment/utterance**, not word | Word‑level interleave shreds sentences on backchannels. |
| Trigger / UX | **`mr toggle`** bound via Shortcuts/Raycast; macOS orange mic indicator; completion notification | Zero UI code in v1. Menu‑bar app = v1.1. |
| Language | **English default** (`--language` override) | One rule, no auto/en ambiguity. |
| Output | **`.md` only** by default; JSON sidecar behind `--json` | Matches goal; keep folder clean. |
| Storage | `recordings/<stamp>/` (wavs + meta) + `transcripts/<stamp>.md` under `~/Meetings` | Raw vs output separated. |
| Platform (v1) | **macOS 14.2+, Apple Silicon** | Your machine. Others later behind same interfaces. |
| Stack | **Python** (core, CLI) + **Swift** (capture helper only) | Swift only where native APIs require it. |

---

## 2. Goals / Non‑goals

**Goals (v1)**
- `mr toggle` (hotkey‑bound) starts/stops recording; stop auto‑transcribes to `.md`.
- Two separate tracks: mic (echo‑cancelled) + system audio, 16 kHz mono WAV.
- Local GPU transcription with segment + word timestamps, VAD on.
- Deterministic `You`/`Them` attribution; echo duplicates removed.
- CLI for agents/scripting: `start · stop · toggle · process · status · doctor`.
- OSS quality: typed, tested, linted, README, demo.

**Non‑goals (v1)**
- Menu‑bar app (v1.1) · group diarization · real‑time transcription ·
  summaries/action items · speaker names · Windows/Linux · SRT/TXT export.

---

## 3. Architecture

```
 hotkey (Shortcuts/Raycast) ──► mr toggle
                                   │
┌──────────────────────────────────▼───────────────────────────┐
│ CLI (Python, typer): start · stop · toggle · process · status │
│ · doctor     — owns recording state (pidfile + signals)       │
└───────────────┬───────────────────────────────┬──────────────┘
                │ spawns / signals              │ imports
┌───────────────▼──────────────┐ ┌──────────────▼──────────────┐
│ mr-capture (Swift binary)    │ │ CORE (pure Python, tested)  │
│ • Core Audio tap → system.wav│ │ transcribe (mlx-whisper,VAD)│
│ • VPIO mic (AEC) → mic.wav   │ │ → merge (segments + dedup)  │
│ • shared start timestamp     │ │ → output (.md, opt. JSON)   │
└──────────────────────────────┘ └─────────────────────────────┘
                 recordings/ + transcripts/  (all local)
```

- **Single owner of recording state:** the CLI (pidfile in `~/Meetings/.state`).
  The future menu‑bar app will call the CLI/core — never record independently.
- **Contract between Swift and Python:** `mr-capture --out <dir>`; SIGINT → flush
  + finalize WAVs + write `meta.json` (start time, devices, sample rates); exit 0.
- WAVs written incrementally so a crash leaves recoverable audio.

---

## 4. Components

### 4.1 Capture — `mr-capture` (Swift, ~200 LOC target)
- System: `AudioHardwareCreateProcessTap` (global tap, macOS 14.2+) → aggregate device → WAV.
- Mic: `AVAudioEngine` input with voice processing enabled (AEC).
- Resample both to 16 kHz mono; record a common start timestamp for alignment.
- Permissions: Microphone + System Audio Recording. **Spike must confirm which
  process macOS attributes them to** when launched from Shortcuts/Raycast/Terminal.

### 4.2 Transcription — `core/transcribe.py`
- `Transcriber` protocol; default `MlxWhisperTranscriber` (`large-v3-turbo`).
- `word_timestamps=True`, VAD pre‑filter, `language="en"` default.
- Each stream transcribed independently (sequential first; parallel only if spike shows a win).
- **Model storage rule:**
  - Load by HF repo id (default `mlx-community/whisper-large-v3-turbo`) so
    `mlx-whisper` → `huggingface_hub.snapshot_download()` uses the **standard HF
    hub cache**. Never pass a custom `cache_dir`, never copy weights into
    `~/Meetings` or bundle them in an app.
  - Per‑call runs resolve **cache‑only** (`local_files_only=True` /
    `HF_HUB_OFFLINE=1`) → no network on each meeting. Download happens only via
    `mr doctor --fetch-model` (or first run with an explicit message + size).
  - `--model` accepts an HF repo id **or** a local path (for users who keep
    models elsewhere). `mr doctor` reports cache location + whether the model is present.
  - Note: sharing only works for the *same repo*. OpenAI / faster‑whisper
    checkpoints are different formats and are not reused.

### 4.3 Merge — `core/merge.py`
- Input: segments labeled `you` / `them`. Sort by segment `start`.
- **Echo dedup:** drop/trim a `you` segment when it overlaps in time with a
  `them` segment and text similarity exceeds a threshold (tunable; tested with fixtures).
- Overlap with *different* text = real interruption → keep both.

### 4.4 Output — `core/output.py`
- `.md` writer (format §5); optional JSON sidecar (`--json`) with `schema_version`.

### 4.5 CLI — `mr`
```
mr toggle                          # start if idle, else stop → transcribe → .md
mr start | mr stop                 # explicit forms
mr process --mic a.wav --system b.wav [--json]   # re-run on existing WAVs
mr status                          # recording? last transcript?
mr doctor                          # macOS version, helper present, permissions, model cached
```
- Clear exit codes; config in `~/.config/mr/config.toml` (outdir, model, language).
- Completion notification via `osascript` (no extra deps).

---

## 5. Transcript format

`~/Meetings/transcripts/2026-08-24_1432.md`:

```markdown
# Meeting — 2026-08-24 14:32

- **Duration:** 42m 10s
- **Participants:** You (mic), Them (system)
- **Source:** `recordings/2026-08-24_1432/`

## Transcript

**You (00:00):** hey, can you hear me ok?
**Them (00:02):** yeah, I hear you just fine.
```

Faithful text, chronological, no rewording.

---

## 6. Repo layout

```
meeting-recorder/
├── README.md  LICENSE  pyproject.toml
├── capture/                 # Swift package → mr-capture binary
│   └── Sources/mr-capture/main.swift
├── mr/
│   ├── cli.py  config.py  state.py
│   └── core/
│       ├── capture.py       # Python wrapper: spawn/signal mr-capture
│       ├── transcribe.py    # Transcriber protocol + mlx backend
│       ├── merge.py         # segment interleave + echo dedup
│       ├── output.py        # .md + optional JSON
│       └── schema.py        # dataclasses
├── tests/                   # transcriber mocked in CI; fixture segments/WAVs
└── examples/demo/           # sample WAVs + generated .md
```

Deps (Python): `mlx-whisper`, `typer`, `soundfile`, `pytest`, `ruff` (lint + format).
Dataclasses for schema (no pydantic); TOML config only (no dotenv).
Swift: system frameworks only.

---

## 7. Phased plan

### Phase 0 — Spike (≈ ½–1 day, throwaway code)  ← do this first
Goal: prove the risky parts before any showcase polish.
- Minimal Swift: tap system audio + VPIO mic → two WAVs.
- Record a real **~45 min call on laptop speakers**.
- Run `mlx-whisper large-v3-turbo` (VAD on) on both tracks with a script.

**Exit criteria (go/no‑go):**
| Check | Pass bar |
|---|---|
| Both tracks captured, aligned | Offset between tracks < ~0.5 s over the call |
| Echo | AEC removes most remote speech from mic; residue removable by text dedup |
| Permissions | Works when triggered from Shortcuts/Raycast; attribution understood |
| Speed | 45‑min call transcribed (both tracks) in an acceptable wait (target ≤ ~3 min — measure) |
| Hallucination | No invented text in silent stretches |

If AEC can't cancel other apps' audio → rely on text dedup (and document
headphones as "best quality"). If taps fail → fall back to BlackHole.

### Phase 1 — Core (Python)
- Scaffolding: `pyproject`, ruff, pytest, CI (lint + unit tests, transcriber mocked).
- `schema`, `transcribe` (mlx), `merge` (segments + dedup), `output` (.md).
- `mr process --mic --system` end‑to‑end on spike WAVs.

### Phase 2 — Capture + control
- Productionize `mr-capture` (build via SwiftPM; incremental WAV writes; SIGINT finalize).
- `mr start/stop/toggle/status/doctor`; pidfile state; notification on completion.
- README: Shortcuts + Raycast hotkey setup, permissions, troubleshooting.
- **Done bar:** press hotkey, take a call on speakers, press again → clean,
  correctly attributed `.md` in `~/Meetings/transcripts/` + notification.

### Phase 3 — OSS polish
- Demo, sample output, contribution guide, `pipx install`, helper build/install
  script, CI green.

### Later (v1.1+)
- Menu‑bar app (calls CLI/core) · group calls (pyannote on system stream only) ·
  `faster-whisper` backend + Windows/Linux capture · SRT/TXT export · streaming.

---

## 8. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Echo on speakers mislabels Them as You | VPIO AEC + text‑overlap dedup; validated in spike with real call |
| VPIO may not cancel other apps' audio | Dedup fallback is always on; measured in spike |
| TCC permissions attributed to launcher app (Shortcuts/Terminal) | Spike verifies; `mr doctor` checks; README documents |
| Whisper hallucinations on silence | VAD on by default |
| Two‑language repo complexity | Swift limited to one small binary with a tiny CLI contract |
| Track misalignment / clock drift | Shared start timestamp; drift negligible at line granularity — verified in spike |
| Model download on first run / duplicate copies | Standard HF hub cache (shared with other tools); cache‑only at call time; `mr doctor --fetch-model` pre‑fetch with documented size |
| Crash mid‑call loses audio | Incremental WAV writes; `mr process` can re‑run on partial files |

---

## 9. Open decisions (defaults in bold)
1. **Dedup threshold** — tune on spike data (start: similarity ≥ 0.6 with time overlap).
2. **`out_root`** — **`~/Meetings`**.
3. **Suggested hotkey** in README — **`⌥⌘R`**.
4. Keep raw WAVs forever, or offer `--keep-audio=false`? — **keep** (re‑processing).

*Next step: run the Phase 0 spike and record results against the exit criteria above.*
