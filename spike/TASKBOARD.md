# Spike Taskboard

> Lead-maintained tracker (single source of truth). Each row is one bite-size
> task handed to a fresh local coding agent (dispatched with `dev_task`, which
> runs on the local model — the DSH build in use has no `workflow` tool, so
> `dev_task` is the local-model dispatch path that satisfies `AGENTS.md`).
> Briefs live in `tasks/<n>_<slug>.md`; workers write
> `tasks/<n>_<slug>.SUMMARY.md` when done; the lead verifies before `done`.

## Status legend
`todo` → `in-progress` → `review` → `done` | `blocked` | `needs-rework`

## Tasks

| # | Task | Status | Owner | Depends on | Files |
|---|------|--------|-------|------------|-------|
| 1 | System-audio tap → `system.wav` (aggregate device + IOProc) | done | lead (worker stalled; design was wrong) | — | `capture/Sources/mr-capture/{Wav,Resample,SystemTap,main}.swift` |
| 2 | Mic capture (AVAudioEngine + VPIO) → `mic.wav`, `--no-aec` flag | done | lead (worker wrote code; lead fixed compile+runtime errors) | 1 | `MicCapture.swift`, `main.swift` |
| 3 | `meta.json` + `build.sh` + embedded Info.plist | done | lead | 2 | `main.swift`, `Info.plist`, `build.sh` |
| 4 | `transcribe.py` (mlx-whisper both tracks → JSON + md) | done | w4 | — (contract fixed) | `transcribe.py` |
| 5 | `align_check.py` (offset/drift via cross-correlation) | done | w5 | — (contract fixed) | `align_check.py` |
| 6 | `echo_check.py` (rapidfuzz overlap scoring) | done | w6 | 4 (contract) | `echo_check.py` |
| 7 | Lead: self-test recording (beeps + `say`), run 4/5/6, VAD comparison if needed | done | lead | 2–6 | `$TMPDIR` (not committed) |
| 8 | Lead: `README.md`, `.gitignore`, draft `SPIKE_RESULTS.md` | in-progress | lead | 7 | docs |
| 9 | Human: real ~45 min call + 5 min `--no-aec` clip, Shortcuts check, finish results | todo | user | 8 | — |

## Shared contracts (do not change without updating dependents)

**Capture output dir** `<dir>/`: `mic.wav`, `system.wav` (16 kHz mono s16le),
`meta.json`:
```json
{ "macos_version": "27.0.1", "aec": true, "started_at": "<ISO8601>",
  "duration_seconds": 123.4,
  "mic":    {"device_name": "...", "native_sample_rate": 48000, "native_channels": 1,
             "first_sample_host_time": 123456789, "first_sample_seconds": 1234.5678,
             "samples_written": 1974400},
  "system": { same keys as mic } }
```
`first_sample_seconds` = host time converted to seconds via `mach_timebase_info`.

**Transcribe output** (`transcribe.py <dir>`): `<dir>/mic.segments.json`,
`<dir>/system.segments.json`, `<dir>/transcript.md`, `<dir>/transcribe_stats.json`.
Segments JSON:
```json
{ "track": "mic", "speaker": "You", "model": "mlx-community/whisper-large-v3-turbo",
  "audio_seconds": 60.0, "wall_seconds": 4.2, "settings": {...},
  "segments": [ {"start": 0.0, "end": 2.1, "text": "hello",
                 "words": [{"word": " hello", "start": 0.0, "end": 0.4, "probability": 0.98}]} ] }
```
`mic` → `You`, `system` → `Them`.

## Notes carried from investigation (verified)
- Tap must be read via a **private aggregate device** + IOProc. Direct
  AudioQueue read of the tap does NOT work (`AudioQueueStart` -10478).
- Exclude own process via `kAudioHardwarePropertyTranslatePIDToProcessObject`.
- `setVoiceProcessingEnabled` is on `AVAudioIONode`; enable before
  `engine.start()`; macOS 14+ has `voiceProcessingOtherAudioDuckingConfiguration`.
- Build (inside DSH sandbox): `CLANG_MODULE_CACHE_PATH="$TMPDIR/mcache" swift build --disable-sandbox`.
- Python: `spike/.venv` (uv, CPython 3.12; mlx-whisper, rapidfuzz, numpy,
  soundfile, scipy). uv needs `UV_CACHE_DIR="$TMPDIR/uvcache"` in the sandbox.
- Model already in `~/.cache/huggingface/hub/models--mlx-community--whisper-large-v3-turbo`
  (weights 1.61 GB). Use `HF_HUB_OFFLINE=1`.
- Env: macOS 27.0.1, arm64, Swift 6.4.
