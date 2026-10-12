# TASK: P1.5 — Implement `mr/core/transcribe.py` (mlx-whisper backend)

TASK: P1/1.5 Implement `mr/core/transcribe.py`: the `Transcriber` protocol and a
`MlxWhisperTranscriber` implementation wrapping local `mlx-whisper` (GPU) transcription.

GOAL: A function `transcribe_audio(path, *, speaker, model, language) -> TranscriptionResult`
that transcribes one 16 kHz mono WAV locally with `mlx-whisper` using the exact locked
settings, honoring offline/cache-only model loading, and raising a clear
`ModelNotCachedError` when the model isn't present offline. The heavy `mlx_whisper`
import must be lazy/injectable so tests can mock it without a GPU.

CONTEXT:
- Workspace root (WITH spaces): `/Users/abhinavademmagari/Documents/Projects/meeting recorder`.
- `mr.core.schema` (P1.2): `TranscriptionResult`, `Segment`, `Word`. `Word(text,start,end,probability)`.
- Conventions: Python 3.12+, dataclasses, ruff select E,F,I,UP, line-length 100.
- Python binary: `./spike/.venv/bin/python` (has `mlx_whisper` 0.4.3, `soundfile`, `numpy`).
- The spike reference logic is in `spike/transcribe.py` (READ IT). Model is cached at
  `~/.cache/huggingface/hub/models--mlx-community--whisper-large-v3-turbo`.

Locked transcription settings (do not change):
```python
TRANSCRIBE_SETTINGS = {
    "language": "en",
    "word_timestamps": True,
    "condition_on_previous_text": False,
    "no_speech_threshold": 0.6,
    "hallucination_silence_threshold": 0.0,
}
```
Default model: `"mlx-community/whisper-large-v3-turbo"`.

Module API (exact):
```python
class ModelNotCachedError(RuntimeError): ...   # message should guide the user to `mr doctor`

@dataclass(frozen=True)
class MlxWhisperConfig:
    model: str = "mlx-community/whisper-large-v3-turbo"
    language: str = "en"
    offline: bool = True          # cache-only; never hit the network at call time

class Transcriber(Protocol):
    CONFIG: MlxWhisperConfig
    def transcribe(self, path: str, *, speaker: str) -> TranscriptionResult: ...

def transcribe_audio(
    path: str, *, speaker: str,
    model: str = DEFAULT_MODEL, language: str = "en",
) -> TranscriptionResult:
    """Top-level helper: builds a MlxWhisperTranscriber + calls .transcribe."""
```
Behavior of `MlxWhisperTranscriber.transcribe(path, *, speaker)`:
1. Load audio via `soundfile` (`sf.read(path, dtype="float32")`) → drop to mono by `.mean(axis=1)` if 2-D. Assert sample rate == 16000 else raise `ValueError`.
2. If `offline`, set `os.environ["HF_HUB_OFFLINE"]="1"`; restore in try/finally.
3. Call `mlx_whisper.transcribe(audio, path_or_hf_repo=self.CONFIG.model, **settings)` where `settings` = locked TRANSCRIBE_SETTINGS with `language` from config. Time it (`time.monotonic`) → `wall_seconds`.
4. Convert result segments → `Segment(speaker, text, start, end, words)` tuples, dropping empty-text segments. Words → `Word(text,start,end,probability)`.
5. Return `TranscriptionResult(track=?, speaker, model, audio_seconds, wall_seconds, settings=locked dict, segments)`. `<track>`: `speaker="You"→"mic"`, `"Them"→"system"`, else `speaker.lower()`.
6. **Laziness/testability:** do NOT import `mlx_whisper` at module top level. Import inside `transcribe`, or accept an optional injected `whisper_module` param. `MlxWhisperTranscriber(config, *, whisper_module=None)` defaults to lazily importing `mlx_whisper`.
7. **Offline model-absent detection:** when `offline=True` and the model is not present, huggingface_hub raises (OfflineModeIsEnabled / LocalEntryNotFoundError / OSError). Catch those known "model not found / offline / not cached" exceptions and re-raise as `ModelNotCachedError` with guidance to run `mr doctor`/`mr doctor --fetch-model` or set `offline=False`. Do NOT swallow other errors.

FILES (create ONLY):
- `/Users/abhinavademmagari/Documents/Projects/meeting recorder/mr/core/transcribe.py`
- `/Users/abhinavademmagari/Documents/Projects/meeting recorder/tests/test_transcribe.py`

READ FIRST:
- `/Users/abhinavademmagari/Documents/Projects/meeting recorder/spike/transcribe.py` (reference logic).
- `/Users/abhinavademmagari/Documents/Projects/meeting recorder/mr/core/schema.py`.
- `/Users/abhinavademmagari/Documents/Projects/meeting recorder/docs/architecture.md` (decision #3).

STEPS:
1. Create `mr/core/transcribe.py` with `ModelNotCachedError`, `MlxWhisperConfig`, `Transcriber` protocol, `MlxWhisperTranscriber`, `DEFAULT_MODEL`, `TRANSCRIBE_SETTINGS`, `transcribe_audio`.
2. Import `mlx_whisper` lazily inside the implementation.
3. Implement offline env forcing + restore in try/finally; offline model-absent → `ModelNotCachedError`.
4. Write `tests/test_transcribe.py` WITHOUT importing the real `mlx_whisper`:
   - Fake `whisper_module` whose `.transcribe(audio, path_or_hf_repo=..., **kw)` returns a controlled dict.
   - Write a real 16000 Hz mono silence WAV to `tmp_path` with `soundfile` (all zeros, 0.5 s).
   - Assert correct speaker/track/model/segments; empty-text dropped; word conversion; `wall_seconds >= 0`; offline env set during call.
   - Assert `ModelNotCachedError` (with guidance) when the fake raises an offline/not-found exception (e.g. `OSError`), and that a different exception propagates unchanged.
   - Assert no real GPU/model touched (fake whisper_module only).

ACCEPTANCE (from repo root):
- `./spike/.venv/bin/python -m pytest tests/test_transcribe.py -q` → all pass (must NOT hit the real model/GPU).
- `./spike/.venv/bin/python -m ruff check mr/core/transcribe.py tests/test_transcribe.py` → clean.
- `./spike/.venv/bin/python -c "from mr.core.transcribe import transcribe_audio, MlxWhisperTranscriber, MlxWhisperConfig, Transcriber, ModelNotCachedError; print('OK')"` → imports WITHOUT loading mlx-whisper/Gpu.

OUT OF SCOPE: No CLI, no merge, no capture, no parallel transcription. Do not modify schema.py. Do not run the real model in tests. Do not touch other files.

REPORT: reply with STATUS, FILES CHANGED, VERIFICATION (pytest + ruff + import output), NOTES.