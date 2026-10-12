# Task 4 — `transcribe.py` (mlx-whisper on both tracks → JSON + markdown)

> Throwaway spike. Do only what's described. Fresh context; don't explore the
> whole repo. When done, write `spike/tasks/04_transcribe.SUMMARY.md` and reply
> REPORT with STATUS / FILES CHANGED / VERIFICATION / NOTES.

## Context
- Python env: **`spike/.venv`** (uv, CPython 3.12; has mlx-whisper, rapidfuzz,
  numpy, soundfile, scipy). Use `spike/.venv/bin/python`.
- Model: already in the **standard HF cache**
  (`~/.cache/huggingface/hub/models--mlx-community--whisper-large-v3-turbo`).
  Load with `mlx_whisper.transcribe`, repo `mlx-community/whisper-large-v3-turbo`,
  offline: set `os.environ.setdefault("HF_HUB_OFFLINE","1")` at top.
- **Crucial:** there is **no `ffmpeg`** on this machine. `mlx_whisper.transcribe`
  cannot take a file path. Load the WAV with `soundfile.read(path, dtype="float32")[0]`
  (already 16 kHz mono, so sample rate is 16000) and pass the **numpy float32
  array** directly to `mlx_whisper.transcribe(audio=...)`. Do not try to pass a path.

## Scope — create `spike/transcribe.py`
A CLI: `transcribe.py <dir>` — reads `<dir>/mic.wav` and `<dir>/system.wav`
(16 kHz mono s16le), transcribes each, writes JSON + markdown + stats.

Behavior:
1. For a track, call:
   ```python
   r = mlx_whisper.transcribe(
       audio_array,                 # numpy float32, 16k mono
       path_or_hf_repo="mlx-community/whisper-large-v3-turbo",
       language="en",
       word_timestamps=True,
       condition_on_previous_text=False,
       hallucination_silence_threshold=0.0,   # default; may add VAD later
   )
   ```
   Exception: if the audio has essentially no speech, mlx may still emit text;
   this is the "hallucination on silence" concern. Also try
   `no_speech_threshold=0.6` (a keyword arg to `transcribe`). Wrap so a HW/HF
   error gives a clear message and exit 1.
2. Outputs (all in `<dir>`):
   - `<dir>/mic.segments.json` and `<dir>/system.segments.json`:
     ```json
     { "track": "mic", "speaker": "You", "model": "mlx-community/whisper-large-v3-turbo",
       "audio_seconds": 60.0, "wall_seconds": 4.2, "settings": {...},
       "segments": [ {"start": 0.0, "end": 2.1, "text": "hello",
                       "words": [{"word":" hello","start":0.0,"end":0.4,"probability":0.98}]} ] }
     ```
     `mic`→`You`, `system`→`Them`. Cast numpy scalars to plain float/int/str.
   - `<dir>/transcript.md`: interleaved by segment start, `**You (MM:SS):** text`
     and `**Them (MM:SS):** text`, blank line between blocks.
   - `<dir>/transcribe_stats.json`: `{mic:{audio_seconds,wall_seconds},system:{...},total_wall_seconds}`.
   - Print per-track + total wall time to stdout.
3. Settings to record in `settings`: the exact kwargs you passed (language,
   word_timestamps, condition_on_previous_text, no_speech_threshold,
   hallucination_silence_threshold).

## Test (self-check before REPORT)
- Create a short test WAV from `say` if you like:
  `say -o "$TMPDIR/s.wav" "Hello world, this is a test."` — note `say -o`
  produces caf; convert: `afconvert -f WAVE -d LEI16@16000 -c 1 s.caf s.wav`.
- Run `transcribe.py <dir-with-those-wavs>`; confirm `.segments.json` valid,
  `.md` interleaved, and stats exist and are sensible (seconds>0).
- Include the small end-to-end output in your SUMMARY.

## Non-goals
- No VAD integration (later), no echo/metrics, no model download (already
  present), no edits to other files.

## Deliverable
- `spike/transcribe.py`
- `spike/tasks/04_transcribe.SUMMARY.md`
- Nothing else.

## When done
Reply `REPORT:` with STATUS, FILES CHANGED, VERIFICATION (commands + outputs), NOTES.