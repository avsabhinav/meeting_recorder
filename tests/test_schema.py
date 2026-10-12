"""Tests for mr.core.schema: dataclasses, format_ts, from_capture_dict."""

import dataclasses
import json

import pytest

from mr.core.schema import (
    CaptureMeta,
    Segment,
    StreamMeta,
    TranscriptionResult,
    Word,
    format_ts,
    from_capture_dict,
)

SAMPLE_META = {
    "macos_version": "27.0.1",
    "aec": True,
    "started_at": "2026-01-15T14:30:00+00:00",
    "duration_seconds": 123.4,
    "mic": {
        "device_name": "MacBook Pro Microphone",
        "native_sample_rate": 48000,
        "native_channels": 1,
        "first_sample_seconds": 1234.5678,
        "samples_written": 1974400,
    },
    "system": {
        "device_name": "Aggregate (system tap)",
        "native_sample_rate": 48000,
        "native_channels": 9,
        "first_sample_seconds": 1234.6,
        "samples_written": 1974400,
    },
}


def test_instantiate_all_dataclasses() -> None:
    word = Word(text=" hello", start=1.0, end=1.5, probability=0.98)
    segment = Segment(speaker="You", text=" hello world", start=1.0, end=2.0, words=(word,))
    assert segment.words == (word,)

    segment_empty = Segment(speaker="Them", text="hi", start=2.0, end=3.0)
    assert segment_empty.words == ()

    result = TranscriptionResult(
        track="mic",
        speaker="You",
        model="mlx-community/whisper-large-v3-turbo",
        audio_seconds=123.4,
        wall_seconds=130.1,
        settings={"language": "en", "word_timestamps": True},
        segments=(segment, segment_empty),
    )
    assert len(result.segments) == 2

    stream = StreamMeta(
        device_name="d",
        native_sample_rate=48000,
        native_channels=1,
        first_sample_seconds=1.23,
        samples_written=100,
    )
    capture = CaptureMeta(
        macos_version="27.0.1",
        aec=True,
        started_at="2026-01-15T14:30:00+00:00",
        duration_seconds=123.4,
        mic=stream,
        system=stream,
    )
    assert capture.mic.device_name == "d"


def test_dataclasses_are_frozen() -> None:
    with pytest.raises(Exception):
        Word(text="a", start=0.0, end=1.0, probability=1.0).text = "b"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [(0, "00:00"), (59, "00:59"), (60, "01:00"), (67.9, "01:07"), (3660.5, "61:00")],
)
def test_format_ts(seconds: float, expected: str) -> None:
    assert format_ts(seconds) == expected


def test_from_capture_dict_roundtrip() -> None:
    capture = from_capture_dict(SAMPLE_META)
    assert isinstance(capture, CaptureMeta)
    assert capture.macos_version == "27.0.1"
    assert capture.aec is True
    assert capture.started_at == "2026-01-15T14:30:00+00:00"
    assert capture.duration_seconds == pytest.approx(123.4)
    assert capture.mic.device_name == "MacBook Pro Microphone"
    assert capture.mic.native_sample_rate == 48000
    assert capture.mic.native_channels == 1
    assert capture.mic.first_sample_seconds == pytest.approx(1234.5678)
    assert capture.mic.samples_written == 1974400
    assert capture.system.native_channels == 9
    assert isinstance(capture.mic, StreamMeta)
    assert isinstance(capture.system, StreamMeta)


def test_from_capture_dict_missing_mic_raises() -> None:
    d = {k: v for k, v in SAMPLE_META.items() if k != "mic"}
    with pytest.raises(ValueError, match="mic"):
        from_capture_dict(d)


def test_from_capture_dict_missing_system_raises() -> None:
    d = {k: v for k, v in SAMPLE_META.items() if k != "system"}
    with pytest.raises(ValueError, match="system"):
        from_capture_dict(d)


def test_capture_meta_json_serializable() -> None:
    capture = from_capture_dict(SAMPLE_META)
    payload = json.dumps(dataclasses.asdict(capture), indent=2)
    assert '"macos_version": "27.0.1"' in payload
    re_parsed = json.loads(payload)
    assert re_parsed["mic"]["native_sample_rate"] == 48000
