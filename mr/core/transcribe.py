"""Local GPU transcription of one 16 kHz mono WAV via ``mlx-whisper``.

``mlx_whisper`` is a heavy dependency (loads the Metal backend), so it is
never imported at module top level: ``MlxWhisperTranscriber`` imports it
lazily inside ``transcribe`` (or accepts an injected module for tests).

Model handling follows architecture decision #3: load by HF repo id only
(standard HF hub cache, never a custom cache_dir), run cache-only via
``HF_HUB_OFFLINE=1`` when ``offline=True``, and raise :class:`ModelNotCachedError`
with a pointer to ``mr doctor`` when the model is not present in the cache.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

import numpy as np
import soundfile as sf

from mr.core.schema import Segment, TranscriptionResult, Word

# Guarded: huggingface_hub ships with mlx-whisper, but keep the module
# importable (and testable) without it.
try:
    from huggingface_hub import LocalEntryNotFoundError, OfflineModeIsEnabled

    _MODEL_ABSENT_ERRORS: tuple[type[BaseException], ...] = (
        LocalEntryNotFoundError,
        OfflineModeIsEnabled,
        OSError,
    )
except ImportError:  # pragma: no cover
    _MODEL_ABSENT_ERRORS = (OSError,)

DEFAULT_MODEL = "mlx-community/whisper-large-v3-turbo"
EXPECTED_SAMPLE_RATE = 16000

# Locked transcription settings (architecture decision #5): do not change.
TRANSCRIBE_SETTINGS: dict[str, object] = {
    "language": "en",
    "word_timestamps": True,
    "condition_on_previous_text": False,
    "no_speech_threshold": 0.6,
    "hallucination_silence_threshold": 0.0,
}


class ModelNotCachedError(RuntimeError):
    """The requested Whisper model is not in the local HF cache (offline mode)."""


@dataclass(frozen=True)
class MlxWhisperConfig:
    """Settings for one :class:`MlxWhisperTranscriber` instance."""

    model: str = DEFAULT_MODEL
    language: str = "en"
    offline: bool = True


@runtime_checkable
class Transcriber(Protocol):
    """Anything that can transcribe one audio track (duck-typed)."""

    CONFIG: MlxWhisperConfig

    def transcribe(self, path: str, *, speaker: str) -> TranscriptionResult: ...


def _load_audio(path: str) -> np.ndarray:
    """Load a 16 kHz WAV as a mono float32 numpy array (no ffmpeg).

    Raises ``ValueError`` if the file's sample rate is not 16000 Hz.
    """
    audio, sr = sf.read(path, dtype="float32")
    if sr != EXPECTED_SAMPLE_RATE:
        raise ValueError(f"expected {EXPECTED_SAMPLE_RATE} Hz audio, got {sr} Hz")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    return np.asarray(audio, dtype=np.float32)


def _track_for(speaker: str) -> str:
    if speaker == "You":
        return "mic"
    if speaker == "Them":
        return "system"
    return speaker.lower()


def _segment_to_dataclass(seg: dict[str, Any], speaker: str) -> Segment:
    words: list[Word] = []
    for w in seg.get("words") or []:
        words.append(
            Word(
                text=str(w.get("word", "")),
                start=float(w.get("start", 0.0)),
                end=float(w.get("end", 0.0)),
                probability=float(w.get("probability", 0.0) or 0.0),
            )
        )
    return Segment(
        speaker=speaker,
        text=str(seg.get("text", "")).strip(),
        start=float(seg.get("start", 0.0)),
        end=float(seg.get("end", 0.0)),
        words=tuple(words),
    )


class MlxWhisperTranscriber:
    """Transcribe 16 kHz mono WAVs locally with ``mlx-whisper`` (Metal GPU).

    ``whisper_module`` is an optional dependency-injection hook: pass a
    module-like object exposing ``transcribe(audio, **kwargs)`` to avoid
    importing the real ``mlx_whisper`` (used in tests). When ``None``,
    ``mlx_whisper`` is imported lazily on the first ``transcribe`` call.
    """

    def __init__(
        self,
        config: MlxWhisperConfig | None = None,
        *,
        whisper_module: Any | None = None,
    ) -> None:
        self.CONFIG: MlxWhisperConfig = config or MlxWhisperConfig()
        self._whisper_module = whisper_module

    def _whisper(self) -> Any:
        mod = self._whisper_module
        if mod is None:
            import mlx_whisper  # lazy: heavy import, only at transcription time

            mod = mlx_whisper
        return mod

    def transcribe(self, path: str, *, speaker: str) -> TranscriptionResult:
        """Transcribe one WAV; return a :class:`TranscriptionResult`.

        Raises:
            ValueError: if the audio is not 16 kHz.
            ModelNotCachedError: if ``offline`` and the model is not cached.
        """
        config = self.CONFIG
        settings: dict[str, object] = {**TRANSCRIBE_SETTINGS, "language": config.language}
        audio = _load_audio(path)
        audio_seconds = len(audio) / EXPECTED_SAMPLE_RATE

        prior = os.environ.get("HF_HUB_OFFLINE")
        try:
            if config.offline:
                os.environ["HF_HUB_OFFLINE"] = "1"
            t0 = time.monotonic()
            try:
                raw = self._whisper().transcribe(
                    audio, path_or_hf_repo=config.model, **settings
                )
            except _MODEL_ABSENT_ERRORS as exc:
                if config.offline:
                    raise ModelNotCachedError(
                        f"model {config.model!r} is not in the local HF cache "
                        f"(offline mode). Run `mr doctor --fetch-model` to download "
                        f"it (or `mr doctor` to check), or set offline=False in "
                        f"MlxWhisperConfig to allow network access."
                    ) from exc
                raise
            wall_seconds = time.monotonic() - t0
        finally:
            if prior is None:
                os.environ.pop("HF_HUB_OFFLINE", None)
            else:
                os.environ["HF_HUB_OFFLINE"] = prior

        kept = [seg for seg in raw.get("segments") or [] if (seg.get("text") or "").strip()]
        segments = tuple(_segment_to_dataclass(seg, speaker) for seg in kept)
        return TranscriptionResult(
            track=_track_for(speaker),
            speaker=speaker,
            model=config.model,
            audio_seconds=audio_seconds,
            wall_seconds=wall_seconds,
            settings=dict(settings),
            segments=segments,
        )


def transcribe_audio(
    path: str,
    *,
    speaker: str,
    model: str = DEFAULT_MODEL,
    language: str = "en",
) -> TranscriptionResult:
    """Top-level helper: build a :class:`MlxWhisperTranscriber` and transcribe."""
    config = MlxWhisperConfig(model=model, language=language)
    transcriber = MlxWhisperTranscriber(config)
    return transcriber.transcribe(path, speaker=speaker)
