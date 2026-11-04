"""Speaker diarization of the system track via Nemotron 3 Diarization (MLX).

Splits the remote (``system.wav``) side of a call into ``Speaker 1``,
``Speaker 2``, ... using ``mlx-community/Nemotron-3-Diarization`` through
``mlx-audio``. The model answers "who spoke when" (up to eight arrival-order
speaker ids at 10 ms resolution); it produces no text. Whisper's word timings
are then attributed to those turns here.

``mlx_audio`` is heavy and is imported lazily inside :func:`diarize_audio`
(a ``vad_load`` hook can be injected for tests). Model handling mirrors
``mr.core.transcribe``: load by HF repo id from the standard HF cache, run
cache-only (``HF_HUB_OFFLINE=1``) when ``offline=True``, and raise
:class:`~mr.core.transcribe.ModelNotCachedError` when the model is absent.

The attribution rules (:func:`assign_speakers`) were tuned on two real
recordings in ``spike/nemotron_diarize_them.py``: Whisper word boundaries and
the diarizer's frames disagree by a few hundred ms at turn changes, so a raw
midpoint lookup strands words of one sentence on the wrong speaker.
Sentence-aware snapping fixes those seams without swallowing genuine short
replies ("Yeah.", "Right.") from another speaker.
"""

from __future__ import annotations

import os
import sys
import types
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any

from mr.core.schema import Segment, Word
from mr.core.transcribe import _MODEL_ABSENT_ERRORS, ModelNotCachedError, _load_audio

DEFAULT_DIARIZATION_MODEL = "mlx-community/Nemotron-3-Diarization"

#: Label prefix for diarized system-side speakers ("Speaker 1", "Speaker 2", ...).
SPEAKER_PREFIX = "Speaker"

#: Pause (s) above which two words are never treated as one utterance.
MAX_GLUE_GAP_S = 0.3
#: How far (words) a mid-sentence speaker change may move to reach a sentence end.
SNAP_WORDS = 3
#: Longest run (words) that may be folded into a neighbouring speaker.
MAX_FRAGMENT_WORDS = 2

_SENT_END = (".", "?", "!")
_MIDSENTENCE_CAPS = {"I", "I'm", "I'll", "I've", "I'd"}

#: ``mlx_audio.vad.models`` imports ``smart_turn``, which imports the STT
#: package; its model registry imports ``transformers`` and with it ``torch``
#: (~600 MB, excluded from the frozen build). Nemotron diarization needs none
#: of that, so an empty stand-in module is registered before the import.
_SMART_TURN_MODULE = "mlx_audio.vad.models.smart_turn"


@dataclass(frozen=True)
class Turn:
    """One diarized speaking turn on the system track's own timeline."""

    start: float
    end: float
    speaker: int  # arrival-order id from the model, 0-based


def speaker_label(n: int) -> str:
    """``speaker_label(1) == "Speaker 1"``."""
    return f"{SPEAKER_PREFIX} {n}"


def _import_vad_load() -> Callable[..., Any]:
    """Import ``mlx_audio.vad.load`` without dragging in transformers/torch."""
    if _SMART_TURN_MODULE not in sys.modules:
        sys.modules[_SMART_TURN_MODULE] = types.ModuleType(_SMART_TURN_MODULE)
    from mlx_audio.vad import load  # lazy: heavy import, only at diarization time

    return load


def diarize_audio(
    path: str,
    *,
    model: str = DEFAULT_DIARIZATION_MODEL,
    offline: bool = True,
    vad_load: Callable[..., Any] | None = None,
) -> list[Turn]:
    """Diarize one 16 kHz mono WAV; return its speaking turns.

    Raises:
        ValueError: if the audio is not 16 kHz.
        ModelNotCachedError: if ``offline`` and the model is not cached.
    """
    audio = _load_audio(path)
    load = vad_load or _import_vad_load()
    prior = os.environ.get("HF_HUB_OFFLINE")
    try:
        if offline:
            os.environ["HF_HUB_OFFLINE"] = "1"
        try:
            diarizer = load(model, strict=True)
        except _MODEL_ABSENT_ERRORS as exc:
            if offline:
                raise ModelNotCachedError(
                    f"diarization model {model!r} is not in the local HF cache "
                    f"(offline mode). Run `mr doctor --fetch-model` to download it."
                ) from exc
            raise
        out = diarizer.generate(audio)
    finally:
        if prior is None:
            os.environ.pop("HF_HUB_OFFLINE", None)
        else:
            os.environ["HF_HUB_OFFLINE"] = prior
    return [Turn(float(s.start), float(s.end), int(s.speaker)) for s in out.segments]


# ---------------------------------------------------------------------------
# Attribution: Whisper words -> diarized speakers
# ---------------------------------------------------------------------------


def _speaker_for_span(start: float, end: float, turns: list[Turn]) -> int | None:
    """Speaker active at the span midpoint; on overlap, the one covering most of it."""
    mid = (start + end) / 2
    covering = {t.speaker for t in turns if t.start <= mid < t.end}
    if len(covering) == 1:
        return next(iter(covering))
    overlap: dict[int, float] = {}
    for t in turns:
        if covering and t.speaker not in covering:
            continue
        ov = min(t.end, end) - max(t.start, start)
        if ov > 0:
            overlap[t.speaker] = overlap.get(t.speaker, 0.0) + ov
    if not overlap:
        return None
    return max(overlap, key=lambda k: overlap[k])


def _fill_gaps(labels: list[int | None]) -> list[int | None]:
    """Unassigned entries take the previous assigned label, else the next one."""
    out = list(labels)
    last = None
    for i, lab in enumerate(out):
        if lab is None:
            out[i] = last
        else:
            last = lab
    nxt = None
    for i in range(len(out) - 1, -1, -1):
        if out[i] is None:
            out[i] = nxt
        else:
            nxt = out[i]
    return out


def _runs(labels: list[int | None]) -> list[tuple[int, int]]:
    """Half-open index ranges of consecutive equal labels."""
    runs, start = [], 0
    for i in range(1, len(labels) + 1):
        if i == len(labels) or labels[i] != labels[start]:
            runs.append((start, i))
            start = i
    return runs


def _ends_sentence(w: Word) -> bool:
    return w.text.strip().rstrip("\"')]").endswith(_SENT_END)


def _starts_sentence(w: Word) -> bool:
    t = w.text.strip()
    return bool(t) and t[0].isupper() and t.rstrip(".,?!") not in _MIDSENTENCE_CAPS


def _gap(words: list[Word], i: int) -> float:
    """Silence before word ``i``."""
    return words[i].start - words[i - 1].end


def _snap_boundaries(
    words: list[Word], labels: list[int | None], snap_words: int, max_gap: float
) -> list[int | None]:
    """Move mid-sentence speaker changes to the nearest sentence end.

    A change is mid-sentence when the word before it ends no sentence, the
    word after it starts none, and no pause separates them. The boundary moves
    back (A's tail goes to B) or forward (B's head goes to A) to the closest
    ``. ? !`` within ``snap_words`` words, never across a pause. Unpunctuated
    text never snaps.
    """
    labels = list(labels)
    for _ in range(len(words)):  # each pass moves one boundary; bounded
        runs = _runs(labels)
        moved = False
        for (a0, b), (_, b1) in zip(runs, runs[1:], strict=False):
            if (
                _ends_sentence(words[b - 1])
                or _starts_sentence(words[b])
                or _gap(words, b) > max_gap
            ):
                continue
            back = None
            for j in range(b - 2, max(a0 - 1, b - 1 - snap_words) - 1, -1):
                if any(_gap(words, k) > max_gap for k in range(j + 2, b)):
                    break
                if j < 0 or _ends_sentence(words[j]):
                    back = j
                    break
            fwd = None
            for k in range(b, min(b1, b + snap_words)):
                if k > b and _gap(words, k) > max_gap:
                    break
                if _ends_sentence(words[k]):
                    fwd = k
                    break
            n_back = b - 1 - back if back is not None else None
            n_fwd = fwd - b + 1 if fwd is not None else None
            if n_back is None and n_fwd is None:
                continue
            if n_fwd is None or (n_back is not None and n_back <= n_fwd):
                for k in range(back + 1, b):
                    labels[k] = labels[b]
            else:
                for k in range(b, fwd + 1):
                    labels[k] = labels[b - 1]
            moved = True
            break
        if not moved:
            break
    return labels


def _absorb_fragments(
    words: list[Word], labels: list[int | None], max_words: int, max_gap: float
) -> list[int | None]:
    """Fold short sentence fragments into the speaker they are glued to.

    Kept as their own turn: a complete short sentence ("Yeah.", "Right.") and
    a run with a pause inside it. In unpunctuated stretches (Whisper sometimes
    emits none) only a fragment sandwiched between two runs of the same
    speaker is folded in.
    """
    labels = list(labels)
    n = len(words)
    for _ in range(n):  # each pass removes one run; bounded
        absorbed = False
        for i0, i1 in _runs(labels):
            if i1 - i0 > max_words:
                continue
            complete = (
                i0 == 0 or _ends_sentence(words[i0 - 1]) or _starts_sentence(words[i0])
            ) and _ends_sentence(words[i1 - 1])
            if complete or any(_gap(words, k) > max_gap for k in range(i0 + 1, i1)):
                continue
            left = i0 > 0 and _gap(words, i0) <= max_gap
            right = i1 < n and _gap(words, i1) <= max_gap
            window = range(max(0, i0 - 10), min(n, i1 + 10))
            if not any(_ends_sentence(words[k]) for k in window):
                if not (left and right and labels[i0 - 1] == labels[i1]):
                    continue
                target = labels[i1]
            else:
                cands = []
                if left:
                    cands.append((_gap(words, i0), labels[i0 - 1]))
                if right:
                    cands.append((_gap(words, i1), labels[i1]))
                if not cands:
                    continue
                target = min(cands, key=lambda c: c[0])[1]
            labels[i0:i1] = [target] * (i1 - i0)
            absorbed = True
            break
        if not absorbed:
            break
    return labels


def _split_segment(seg: Segment, labels: list[int | None]) -> list[tuple[int | None, Segment]]:
    """Split ``seg`` at speaker changes in ``labels`` (one label per word)."""
    pieces: list[tuple[int | None, Segment]] = []
    for i0, i1 in _runs(labels):
        ws = seg.words[i0:i1]
        text = "".join(w.text for w in ws).strip()
        if not text:
            continue
        if i0 == 0 and i1 == len(seg.words):
            pieces.append((labels[i0], seg))  # unsplit: keep Whisper's text/times
        else:
            pieces.append(
                (labels[i0], replace(seg, text=text, start=ws[0].start, end=ws[-1].end, words=ws))
            )
    return pieces


def _rule_view(segments: list[Segment]) -> list[Word]:
    """All words, with each Whisper segment's last word marked as a sentence end.

    Whisper's punctuation is not stable across runs of the same audio: on
    2026-11-02_1104 one run wrote "...answer and respond." / "Yeah." and the
    next "...answer and respond" / "Yeah" -- but both cut segments at the same
    places. Treating a segment end as a sentence end keeps the seam rules
    working on unpunctuated runs. Only the rules see this view; the
    transcript text is never changed.
    """
    out: list[Word] = []
    for seg in segments:
        for i, w in enumerate(seg.words):
            if i == len(seg.words) - 1 and not _ends_sentence(w):
                w = replace(w, text=w.text.rstrip() + ".")
            out.append(w)
    return out


def assign_speakers(segments: list[Segment], turns: list[Turn]) -> list[Segment]:
    """Relabel system-track ``segments`` as ``Speaker 1..N`` using ``turns``.

    Each word gets the speaker active at its midpoint (unassigned words take
    their nearest assigned neighbour), mid-sentence speaker changes snap to a
    sentence end, and stranded fragments fold into the speaker they are
    glued to. Whisper segments are split only where the speaker changes, so
    everything downstream (echo trimming, rendering) sees the same segment
    shapes as before. A segment without word timings takes the speaker that
    dominates its interval.

    Numbering follows first appearance and is contiguous; a diarized speaker
    that ends up with no words never gets a number. With no turns, or no
    segment attributable to any turn, ``segments`` is returned unchanged.
    """
    if not turns or not segments:
        return list(segments)

    words = [w for s in segments for w in s.words]
    labels = _fill_gaps([_speaker_for_span(w.start, w.end, turns) for w in words])
    rule_words = _rule_view(segments)
    labels = _snap_boundaries(rule_words, labels, SNAP_WORDS, MAX_GLUE_GAP_S)
    labels = _absorb_fragments(rule_words, labels, MAX_FRAGMENT_WORDS, MAX_GLUE_GAP_S)

    pieces: list[tuple[int | None, Segment]] = []
    pos = 0
    for seg in segments:
        if seg.words:
            n = len(seg.words)
            pieces.extend(_split_segment(seg, labels[pos : pos + n]))
            pos += n
        else:
            pieces.append((_speaker_for_span(seg.start, seg.end, turns), seg))

    filled = _fill_gaps([spk for spk, _ in pieces])
    if all(spk is None for spk in filled):
        return list(segments)

    order: dict[int, int] = {}
    for spk, (_, seg) in sorted(zip(filled, pieces, strict=True), key=lambda p: p[1][1].start):
        if spk is not None and spk not in order:
            order[spk] = len(order) + 1
    return [
        replace(seg, speaker=speaker_label(order[spk]))
        for spk, (_, seg) in zip(filled, pieces, strict=True)
        if spk is not None
    ]
