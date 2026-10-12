# Task 4 — `transcribe.py` — SUMMARY

STATUS: DONE

## What was built
`spike/transcribe.py` — CLI `transcribe.py <dir>` that:
- Sets `HF_HUB_OFFLINE=1` (offline; model from standard HF cache).
- Loads `<dir>/mic.wav` and `<dir>/system.wav` via `soundfile.read(path, dtype="float32")`,
  asserts sample rate == 16000, passes the raw numpy float32 array to
  `mlx_whisper.transcribe` (no ffmpeg needed).
- Model: `mlx-community/whisper-large-v3-turbo`.
- Settings recorded in each JSON: `language="en"`, `word_timestamps=True`,
  `condition_on_previous_text=False`, `no_speech_threshold=0.6`,
  `hallucination_silence_threshold=0.0`.
- Writes `<dir>/mic.segments.json`, `<dir>/system.segments.json`,
  `<dir>/transcript.md`, `<dir>/transcribe_stats.json`; prints per-track + total wall time.
- Speakers: mic→`You`, system→`Them`. Empty-text segments are dropped; empty
  `segments` list still yields valid JSON. Missing file → clear error, exit 1.
- numpy scalars cast to plain float/int/str (json-safe helper).

## Self-check (offline run)
Test dir created in `$TMPDIR` (not committed):
```bash
say -o "$TMPDIR/s.caf" "Hello world, this is a short test."
afconvert -f WAVE -d LEI16@16000 -c 1 "$TMPDIR/s.caf" "$TMPDIR/t.wav"
# t.wav copied as both mic.wav and system.wav in a test dir
spike/.venv/bin/python spike/transcribe.py "$TMPDIR/t4_transcribe_test"
```
Output:
```
[mic] audio=2.411s wall=5.059s segments=1
[system] audio=2.411s wall=0.582s segments=1
[total] wall=5.641s
```
All 4 files produced. Both segments JSONs are valid JSON with keys
`track, speaker, model, audio_seconds, wall_seconds, settings, segments`;
first mic segment: `start=0.0 end=2.06 text="Hello world, this is a short test"`
with word timestamps (e.g. ` Hello` 0.00–0.24, p=0.686).

`transcript.md`:
```
# Transcript

**You (00:00):** Hello world, this is a short test

**Them (00:00):** Hello world, this is a short test
```
`transcribe_stats.json`:
```json
{
  "mic":    {"audio_seconds": 2.411, "wall_seconds": 5.059},
  "system": {"audio_seconds": 2.411, "wall_seconds": 0.582},
  "total_wall_seconds": 5.641
}
```
Stats sanity asserted: `total_wall_seconds > 0`, `audio_seconds > 0`.

Error path verified: dir with only `mic.wav` → `ERROR: missing input file: .../system.wav`, exit 1.

## NOTES
- First transcribe call per process pays model-load cost (~4.5 s of the 5.06 s mic wall);
  subsequent track reuses the cached model (0.58 s).
- `hallucination_silence_threshold=0.0` and `no_speech_threshold=0.6` passed to reduce
  silence hallucination; both recorded in `settings`.
