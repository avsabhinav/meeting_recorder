"""Tests for mr.core.transcribe: MlxWhisperTranscriber with a fake whisper module.

The real ``mlx_whisper`` (and any GPU) is never imported: a fake module with a
controlled ``transcribe`` result is injected. A real 16 kHz mono silence WAV is
written to ``tmp_path`` via ``soundfile``.
"""

from __future__ import annotations

import os

import numpy as np
import pytest
import soundfile as sf

import mr.core.transcribe as transcribe_mod
from mr.core.schema import TranscriptionResult
from mr.core.transcribe import (
    TRANSCRIBE_SETTINGS,
    MlxWhisperConfig,
    MlxWhisperTranscriber,
    ModelNotCachedError,
    transcribe_audio,
)

LOCKED_SETTINGS = {
    "language": "en",
    "word_timestamps": True,
    "condition_on_previous_text": False,
    "no_speech_threshold": 0.6,
    "hallucination_silence_threshold": 0.0,
}

FAKE_RESULT = {
    "text": " hello world.\n",
    "segments": [
        {
            "start": 0.1,
            "end": 0.9,
            "text": " hello world. ",
            "words": [
                {"word": " hello", "start": 0.1, "end": 0.4, "probability": 0.98},
                {"word": " world.", "start": 0.4, "end": 0.9, "probability": 0.91},
            ],
        },
        {"start": 1.0, "end": 1.5, "text": "   ", "words": []},  # empty-text: dropped
    ],
}


class FakeWhisper:
    """Module stand-in exposing ``transcribe``; records env + kwargs at call time."""

    def __init__(self, result: dict | None = None, exc: BaseException | None = None):
        self.result = result if result is not None else FAKE_RESULT
        self.exc = exc
        self.last_kwargs: dict | None = None
        self.env_during_call: str | None = None

    def transcribe(self, audio, **kwargs):
        self.last_kwargs = kwargs
        self.env_during_call = os.environ.get("HF_HUB_OFFLINE")
        if self.exc is not None:
            raise self.exc
        return self.result


@pytest.fixture()
def wav_path(tmp_path):
    """A real 16 kHz mono silence WAV (0.5 s of zeros)."""
    path = tmp_path / "silence.wav"
    sf.write(str(path), np.zeros(8000, dtype=np.float32), 16000)
    return str(path)


def test_transcribe_you_mic(wav_path):
    fake = FakeWhisper()
    t = MlxWhisperTranscriber(MlxWhisperConfig(), whisper_module=fake)
    result = t.transcribe(wav_path, speaker="You")

    assert isinstance(result, TranscriptionResult)
    assert result.track == "mic"
    assert result.speaker == "You"
    assert result.model == "mlx-community/whisper-large-v3-turbo"
    assert result.audio_seconds == pytest.approx(0.5)
    assert result.wall_seconds >= 0
    assert result.settings == LOCKED_SETTINGS

    # empty-text segment dropped
    assert len(result.segments) == 1
    seg = result.segments[0]
    assert seg.speaker == "You"
    assert seg.text == "hello world."
    assert seg.start == pytest.approx(0.1)
    assert seg.end == pytest.approx(0.9)

    # word conversion
    assert len(seg.words) == 2
    w0, w1 = seg.words
    assert (w0.text, w0.start, w0.end, w0.probability) == (" hello", 0.1, 0.4, 0.98)
    assert (w1.text, w1.start, w1.end, w1.probability) == (" world.", 0.4, 0.9, 0.91)


def test_transcribe_them_system_and_custom_speaker(wav_path):
    assert (
        MlxWhisperTranscriber(MlxWhisperConfig(), whisper_module=FakeWhisper())
        .transcribe(wav_path, speaker="Them")
        .track
        == "system"
    )
    assert (
        MlxWhisperTranscriber(MlxWhisperConfig(), whisper_module=FakeWhisper())
        .transcribe(wav_path, speaker="Bob")
        .track
        == "bob"
    )


def test_whisper_called_with_locked_settings_and_model(wav_path):
    fake = FakeWhisper()
    t = MlxWhisperTranscriber(
        MlxWhisperConfig(model="repo/model", language="fr"), whisper_module=fake
    )
    t.transcribe(wav_path, speaker="You")
    assert fake.last_kwargs["path_or_hf_repo"] == "repo/model"
    assert fake.last_kwargs == {
        "path_or_hf_repo": "repo/model",
        "language": "fr",
        "word_timestamps": True,
        "condition_on_previous_text": False,
        "no_speech_threshold": 0.6,
        "hallucination_silence_threshold": 0.0,
    }
    assert TRANSCRIBE_SETTINGS == LOCKED_SETTINGS


def test_offline_env_set_during_call_and_restored(wav_path, monkeypatch):
    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
    fake = FakeWhisper()
    MlxWhisperTranscriber(MlxWhisperConfig(), whisper_module=fake).transcribe(
        wav_path, speaker="You"
    )
    assert fake.env_during_call == "1"  # HF_HUB_OFFLINE was "1" during the call
    assert "HF_HUB_OFFLINE" not in os.environ  # restored (was unset)

    # a pre-set value is restored, not clobbered
    monkeypatch.setenv("HF_HUB_OFFLINE", "0")
    MlxWhisperTranscriber(MlxWhisperConfig(), whisper_module=FakeWhisper()).transcribe(
        wav_path, speaker="You"
    )
    assert os.environ["HF_HUB_OFFLINE"] == "0"


def test_model_not_cached_raises_with_doctor_guidance(wav_path):
    fake = FakeWhisper(exc=OSError("Cannot send a request, as offline mode is enabled"))
    t = MlxWhisperTranscriber(MlxWhisperConfig(), whisper_module=fake)
    with pytest.raises(ModelNotCachedError) as excinfo:
        t.transcribe(wav_path, speaker="You")
    msg = str(excinfo.value)
    assert "mr doctor --fetch-model" in msg
    assert "mr doctor" in msg
    assert "offline=False" in msg
    assert excinfo.value.__cause__ is fake.exc


def test_other_exceptions_propagate_unchanged(wav_path):
    boom = ValueError("boom")
    fake = FakeWhisper(exc=boom)
    t = MlxWhisperTranscriber(MlxWhisperConfig(), whisper_module=fake)
    with pytest.raises(ValueError) as excinfo:
        t.transcribe(wav_path, speaker="You")
    assert excinfo.value is boom


def test_wrong_sample_rate_raises_value_error(tmp_path):
    path = str(tmp_path / "wrong.wav")
    sf.write(path, np.zeros(4410, dtype=np.float32), 44100)
    t = MlxWhisperTranscriber(MlxWhisperConfig(), whisper_module=FakeWhisper())
    with pytest.raises(ValueError, match="16000"):
        t.transcribe(path, speaker="You")


def test_transcribe_audio_helper_builds_config_and_delegates(monkeypatch, wav_path):
    calls: dict = {}
    sentinel = object()

    class Stub:
        def __init__(self, config, *, whisper_module=None):
            calls["config"] = config
            calls["whisper_module"] = whisper_module

        def transcribe(self, path, *, speaker):
            calls["path"] = path
            calls["speaker"] = speaker
            return sentinel

    monkeypatch.setattr(transcribe_mod, "MlxWhisperTranscriber", Stub)

    result = transcribe_audio(wav_path, speaker="You", model="custom/model", language="fr")
    assert result is sentinel
    assert calls["config"].model == "custom/model"
    assert calls["config"].language == "fr"
    assert calls["whisper_module"] is None
    assert calls["path"] == wav_path
    assert calls["speaker"] == "You"
