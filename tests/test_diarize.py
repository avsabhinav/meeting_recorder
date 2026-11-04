"""Tests for mr.core.diarize (pure attribution logic; the model is injected).

The seam cases reproduce what the spike measured on real recordings
(``spike/nemotron_diarize_them.py``): a mid-sentence speaker change, a genuine
one-word reply, an unpunctuated stranded fragment, and a diarized speaker who
never gets a word.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import soundfile as sf

import mr.cli
from mr.core.diarize import Turn, assign_speakers, diarize_audio, speaker_label
from mr.core.schema import Segment, Word
from mr.core.transcribe import ModelNotCachedError

REPO = Path(__file__).resolve().parent.parent

_DUR = 0.3
_GAP = 0.05


def _words(texts: list[str], start: float = 0.0) -> list[Word]:
    out, t = [], start
    for text in texts:
        out.append(Word(text=" " + text, start=t, end=t + _DUR, probability=1.0))
        t += _DUR + _GAP
    return out


def _segment(words: list[Word]) -> Segment:
    return Segment(
        speaker="Them",
        text="".join(w.text for w in words).strip(),
        start=words[0].start,
        end=words[-1].end,
        words=tuple(words),
    )


def _turns(words: list[Word], labels: list[int]) -> list[Turn]:
    """One diarized turn per word, padded by half the inter-word gap."""
    return [
        Turn(w.start - _GAP / 2, w.end + _GAP / 2, spk)
        for w, spk in zip(words, labels, strict=True)
    ]


def _lines(segments: list[Segment]) -> list[tuple[str, str]]:
    return [(s.speaker, s.text) for s in segments]


def test_speaker_label() -> None:
    assert speaker_label(3) == "Speaker 3"


def test_mid_sentence_change_snaps_to_sentence_end() -> None:
    """2026-11-02_1104 02:21: "It'll likely" was stranded on the previous speaker."""
    words = _words(
        ["Okay.", "answer", "and", "respond.", "It'll", "likely", "be", "Vinit,", "but"]
    )
    labels = [0, 0, 0, 0, 0, 0, 1, 1, 1]
    out = assign_speakers([_segment(words)], _turns(words, labels))
    assert _lines(out) == [
        ("Speaker 1", "Okay. answer and respond."),
        ("Speaker 2", "It'll likely be Vinit, but"),
    ]


def test_complete_short_reply_is_kept() -> None:
    """A genuine "Yeah." from another speaker must not be folded away."""
    words = _words(["on", "teams?", "Yeah.", "So", "that", "we"])
    labels = [0, 0, 1, 0, 0, 0]
    out = assign_speakers([_segment(words)], _turns(words, labels))
    assert _lines(out) == [
        ("Speaker 1", "on teams?"),
        ("Speaker 2", "Yeah."),
        ("Speaker 1", "So that we"),
    ]


def test_sentence_fragment_moves_to_its_sentence() -> None:
    """14:44: "All" sat on the previous speaker; "All good." is one utterance."""
    words = _words(["Happy", "Halloween.", "All", "good.", "Thanks."])
    labels = [2, 2, 0, 1, 1]
    out = assign_speakers([_segment(words)], _turns(words, labels))
    assert _lines(out) == [
        ("Speaker 1", "Happy Halloween."),
        ("Speaker 2", "All good. Thanks."),
    ]


def test_unpunctuated_sandwiched_fragment_is_absorbed() -> None:
    words = _words(
        ["we", "have", "a", "contract", "for", "because", "they", "pay", "us", "money", "ok"]
    )
    labels = [0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0]
    out = assign_speakers([_segment(words)], _turns(words, labels))
    # One speaker left, and the absorbed id never got a number.
    assert [s.speaker for s in out] == ["Speaker 1"]
    assert sum(len(s.words) for s in out) == len(words)


def test_wordless_speaker_dropped_and_numbering_contiguous() -> None:
    """2026-11-04_1304: a diarized speaker with no Whisper words got a label."""
    first = _words(["Hello", "there."], start=0.0)
    second = _words(["Good", "morning."], start=5.0)
    turns = _turns(first, [3, 3]) + _turns(second, [1, 1]) + [Turn(100.0, 110.0, 5)]
    out = assign_speakers([_segment(first), _segment(second)], turns)
    assert _lines(out) == [("Speaker 1", "Hello there."), ("Speaker 2", "Good morning.")]


def test_segment_without_words_takes_dominant_speaker() -> None:
    seg = Segment(speaker="Them", text="no timings", start=1.0, end=2.0)
    out = assign_speakers([seg], [Turn(0.5, 2.5, 4)])
    assert _lines(out) == [("Speaker 1", "no timings")]


def test_no_turns_leaves_segments_unchanged() -> None:
    words = _words(["hi", "there"])
    segs = [_segment(words)]
    assert assign_speakers(segs, []) == segs


def test_word_timings_preserved_through_split() -> None:
    words = _words(["Okay.", "Sure.", "Fine."])
    out = assign_speakers([_segment(words)], _turns(words, [0, 1, 0]))
    assert [w for s in out for w in s.words] == words
    assert out[1].start == words[1].start and out[1].end == words[1].end


# ---------------------------------------------------------------------------
# diarize_audio with an injected loader
# ---------------------------------------------------------------------------


@pytest.fixture
def wav(tmp_path) -> str:
    path = tmp_path / "system.wav"
    sf.write(path, np.zeros(16000, dtype=np.float32), 16000)
    return str(path)


def test_diarize_audio_returns_turns_and_restores_env(wav, monkeypatch) -> None:
    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
    seen: dict[str, object] = {}

    def fake_load(model, strict):
        seen["model"] = model
        seen["offline"] = os.environ.get("HF_HUB_OFFLINE")
        segs = [SimpleNamespace(start=0.1, end=0.5, speaker=2)]
        return SimpleNamespace(generate=lambda audio: SimpleNamespace(segments=segs))

    turns = diarize_audio(wav, model="org/diar", vad_load=fake_load)
    assert turns == [Turn(0.1, 0.5, 2)]
    assert seen == {"model": "org/diar", "offline": "1"}
    assert "HF_HUB_OFFLINE" not in os.environ


def test_diarize_audio_model_absent_raises_not_cached(wav) -> None:
    def fake_load(model, strict):
        raise OSError("not in cache")

    with pytest.raises(ModelNotCachedError, match="mr doctor --fetch-model"):
        diarize_audio(wav, model="org/diar", vad_load=fake_load)


@pytest.mark.skipif(
    importlib.util.find_spec("mlx_audio") is None, reason="mlx-audio not installed"
)
def test_vad_import_keeps_torch_and_transformers_out() -> None:
    """The smart_turn stub must keep torch out of the (frozen) process."""
    code = (
        "import sys; from mr.core.diarize import _import_vad_load; _import_vad_load(); "
        "print(sorted({'torch', 'transformers'} & set(sys.modules)))"
    )
    res = subprocess.run(
        [sys.executable, "-c", code], cwd=REPO, capture_output=True, text=True, check=True
    )
    assert res.stdout.strip() == "[]"


# ---------------------------------------------------------------------------
# CLI fail-soft wrapper
# ---------------------------------------------------------------------------


def test_cli_diarize_system_falls_back_to_them(tmp_path, monkeypatch, capsys) -> None:
    def boom(path, *, model):
        raise ModelNotCachedError("diarization model not cached")

    monkeypatch.setattr(mr.cli, "diarize_audio", boom)
    segs = [_segment(_words(["hello", "there"]))]
    out = mr.cli._diarize_system(segs, tmp_path / "system.wav", "org/diar")
    assert out == segs
    assert [s.speaker for s in out] == ["Them"]
    assert "warning: diarization failed" in capsys.readouterr().err


def test_cli_diarize_system_relabels(tmp_path, monkeypatch) -> None:
    words = _words(["Okay.", "Sure."])
    monkeypatch.setattr(
        mr.cli, "diarize_audio", lambda path, *, model: _turns(words, [7, 3])
    )
    out = mr.cli._diarize_system([_segment(words)], tmp_path / "system.wav", "org/diar")
    assert _lines(out) == [("Speaker 1", "Okay."), ("Speaker 2", "Sure.")]


def test_unpunctuated_run_uses_whisper_segment_ends() -> None:
    """Whisper sometimes drops punctuation but still cuts segments at sentence ends."""
    a = _words(["answer", "and", "respond"], start=0.0)
    b = _words(["It'll", "likely", "be", "Vinit"], start=a[-1].end + _GAP)
    c = _words(["on", "Teams?"], start=b[-1].end + _GAP)
    d = _words(["Yeah"], start=c[-1].end + _GAP)
    e = _words(["So", "that", "we"], start=d[-1].end + _GAP)
    words = a + b + c + d + e
    labels = [0, 0, 0, 0, 0, 1, 1, 0, 0, 1, 0, 0, 0]
    segs = [_segment(x) for x in (a, b, c, d, e)]
    out = assign_speakers(segs, _turns(words, labels))
    assert _lines(out) == [
        ("Speaker 1", "answer and respond"),
        ("Speaker 2", "It'll likely be Vinit"),
        ("Speaker 1", "on Teams?"),
        ("Speaker 2", "Yeah"),
        ("Speaker 1", "So that we"),
    ]
