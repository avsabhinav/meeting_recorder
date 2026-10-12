# Task: Phase 0 Spike — Prove Capture, Echo, and Transcription

> Context: see `PLAN.md` (§7 Phase 0) and `Project Goal.md`.
> This is a **throwaway spike**. Goal is *evidence*, not production code.

## Objective
In ≤ 1 day, prove (or disprove) that on **macOS 14.2+ / Apple Silicon** we can:
1. Capture **system audio** (Core Audio process tap) and **mic** (with OS echo
   cancellation) into two aligned 16 kHz mono WAVs, from a small Swift binary.
2. Transcribe both tracks locally with **`mlx-whisper` (`large-v3-turbo`)** fast
   enough and without hallucinated text on silence.
3. Produce attribution good enough that `You` lines don't contain the remote
   person's words when the call is on **laptop speakers**.

Output = working spike code + a filled‑in `spike/SPIKE_RESULTS.md`.

## Environment
- MacBook M5 Pro, 64 GB unified memory, macOS 14.2+ (record exact version).
- Calls on **laptop speakers** (not headphones) — this is the case that matters.

## Constraints (do NOT do)
- No repo scaffolding, packaging, CI, tests, CLI framework, or config system.
- No menu‑bar app, no hotkey work.
- No BlackHole / virtual devices (only as a documented fallback if taps fail).
- No LLM, no summaries.
- Keep everything under `spike/`. Hard‑coded paths/flags are fine.

## Deliverables
```
spike/
  capture/            # SwiftPM package → `mr-capture` binary
  transcribe.py       # mlx-whisper on both WAVs → segments JSON + quick .md
  align_check.py      # measures offset/drift between tracks
  echo_check.py       # measures echo residue in mic transcript
  SPIKE_RESULTS.md    # filled template (below)
  README.md           # exact commands to build + run
```
Do not commit call recordings; add `spike/out/` to `.gitignore`.

## Task 1 — `mr-capture` (Swift)
**CLI contract:** `mr-capture --out <dir> [--no-aec]`
- Runs until **SIGINT**, then flushes, finalizes WAVs, writes `meta.json`, exits 0.
- Writes `<dir>/mic.wav`, `<dir>/system.wav` (16 kHz, mono, 16‑bit PCM), written
  **incrementally** (not buffered in memory for the whole call).
- `meta.json`: macOS version, device names, native sample rates, host time of
  the first sample of each stream, AEC on/off, duration.

**System audio:** `CATapDescription` (global stereo tap, exclude own process) →
`AudioHardwareCreateProcessTap` → private aggregate device containing the tap →
IOProc → downmix + resample to 16 kHz → WAV.

**Mic:** `AVAudioEngine` input node with `setVoiceProcessingEnabled(true)`
(skip when `--no-aec`) → downmix + resample to 16 kHz → WAV.

**Permissions:** embed an Info.plist in the binary (e.g. linker
`-sectcreate __TEXT __info_plist`) with `NSMicrophoneUsageDescription` and
`NSAudioCaptureUsageDescription`.

## Task 2 — Alignment check (short, `--no-aec`)
- Record ~2 min with `--no-aec`. Play a short click/beep via `afplay` at the
  start and again at the end (it lands in `system.wav` via the tap and in
  `mic.wav` acoustically).
- `align_check.py`: cross‑correlate to find the offset at start and end →
  report **offset** and **drift**. Also compare with `meta.json` first‑sample times.

## Task 3 — Real call recording (AEC on)
- Record a real **~45 min 1:1 call on laptop speakers** (Zoom/Meet/Teams —
  note which). **Get the other party's consent.**
- Also record a **~5 min** clip with `--no-aec` in similar conditions, for comparison.
- Observe and note: does enabling voice processing **duck/lower other audio**
  (the call volume)? Any audible artifacts on your own voice?

## Task 4 — Transcription (`transcribe.py`)
- `mlx-whisper`, model `mlx-community/whisper-large-v3-turbo`,
  `word_timestamps=True`, `language="en"`, `condition_on_previous_text=False`.
- Silence handling: first try built‑in options (`hallucination_silence_threshold`,
  `no_speech_threshold`). If invented text still appears in silent stretches,
  add a VAD pre‑pass (e.g. `silero-vad`) and compare.
- **Model storage:** load by HF repo id only — let `mlx-whisper` /
  `huggingface_hub` use the **standard HF hub cache** (`~/.cache/huggingface/hub`,
  honoring `HF_HOME` / `HF_HUB_CACHE`). Do **not** set a custom `cache_dir`,
  download weights into `spike/`, or copy them anywhere. After the first
  download, verify a re‑run works with `HF_HUB_OFFLINE=1` (no network). Report
  model size on disk and cache path in results.
- Transcribe each track separately; save segments (`start`, `end`, `text`,
  `words`) as JSON; write a quick interleaved `.md` (`**You (MM:SS):** …` /
  `**Them (MM:SS):** …`) sorted by segment start.
- Record **wall‑clock time** per track and total; peak memory if easy.

## Task 5 — Echo check (`echo_check.py`)
- For each `You` segment overlapping in time with a `Them` segment, compute text
  similarity (e.g. `rapidfuzz` token ratio).
- Report: # `You` segments, # flagged as likely echo at thresholds 0.5 / 0.6 /
  0.7, and 5–10 example pairs. Do this for **AEC on (45 min)** and **AEC off (5 min)**.
- Manually spot‑check ~10 flagged + ~10 unflagged to estimate false positives/negatives.

## Exit criteria (go / no‑go)
| Check | Pass bar |
|---|---|
| Capture | Both WAVs valid for the full 45 min; no dropouts; crash/Ctrl‑C leaves usable files |
| Alignment | Start offset < 0.5 s; drift < 0.5 s over the call (or correctable from meta) |
| Echo | With AEC + dedup at some threshold, `You` lines contain essentially no remote speech, with few false drops |
| Permissions | Works when launched from **Terminal**, and from a **Shortcuts** "Run Shell Script" action; note which app macOS asks permission for |
| Speed | Both tracks of the 45‑min call transcribed in ≤ ~3 min (report actual) |
| Hallucination | No invented text in silent stretches (report which setting achieved it) |

## `SPIKE_RESULTS.md` template
```markdown
# Spike Results
- Date / macOS version / hardware:
- Call app used:

## Verdict: GO / NO-GO / GO-WITH-CHANGES

| Check | Result | Pass? | Notes |
|---|---|---|---|
| Capture | | | |
| Alignment (offset / drift) | | | |
| Echo (AEC on vs off, best threshold) | | | |
| Permissions (Terminal / Shortcuts) | | | |
| Speed (per track / total) | | | |
| Hallucination (setting used) | | | |
| AEC ducking / artifacts | | | |

## Surprises / gotchas

## Recommended changes to PLAN.md

## Sample output
(10–20 lines of the generated .md)
```

## Fallbacks (only if a check fails — note it, don't over‑invest)
- Taps fail → try a quick BlackHole capture to compare; report.
- AEC ducks call audio badly or doesn't cancel other apps' audio → report; rely
  on text dedup and measure how well it alone performs (AEC off clip).
- Speed misses target → try `whisper.cpp` (Metal) on the same file; report timing.

**Timebox: 1 day.** If blocked > 2 hours on one item, write down what you tried
in `SPIKE_RESULTS.md` and move on.
