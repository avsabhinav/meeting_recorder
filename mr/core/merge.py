"""Merge mic (You) and system (Them) transcripts into one deduplicated stream.

Always-on safety net for residual echo that OS acoustic-echo-cancellation
(AEC) leaves behind: any ``You`` segment that time-overlaps a ``Them``
segment with similar text is treated as an echo. See
``docs/architecture.md`` decision #2 and ``spike/echo_check.py`` for the
scoring rationale.

Echo-suspected segments are **marked, not deleted** (``echo_suspected=True``):
they are omitted from the Markdown transcript but preserved in the JSON
sidecar. Textual similarity on short utterances is genuinely ambiguous — both
participants saying "yeah" is not echo — and an unrecoverable deletion is the
wrong failure mode for a tool whose promise is a faithful transcript.
"""

from __future__ import annotations

from dataclasses import replace

from rapidfuzz import fuzz

from mr.core.schema import Segment, Word

#: Minimum overlap duration (seconds) for a pair to count as time-overlapping.
_MIN_OVERLAP_S = 0.05

#: Default echo threshold (see :func:`merge_transcripts`).
_DEFAULT_THRESHOLD = 0.6

#: Word count below which a utterance is treated as a short backchannel
#: ("yeah", "right", "okay sounds good"). Two people independently saying the
#: same backchannel is ordinary conversation, not echo, but it scores very
#: high on ``token_ratio`` precisely because the token set is tiny.
_SHORT_UTTERANCE_WORDS = 4

#: Threshold (percent) required to call a short utterance echo. Near-exact
#: only: at this bar "yeah" vs "yeah, exactly" is kept, while a verbatim
#: re-recording of the same short phrase is still caught.
_SHORT_UTTERANCE_THRESHOLD_PCT = 95.0

#: Slack (seconds) added to each end of a matching ``Them`` interval when
#: deciding whether a ``You`` word is echoed. Whisper's word boundaries are
#: approximate, so a strict test leaves crumbs of the speaker's audio glued
#: to genuine speech. Measured on ``2026-10-20_1553``: "and" (0.47 s before
#: the Them start), "basis" (0.15 s past the end) and "dilu" (0.28 s past)
#: all leaked; the nearest genuine word was ~0.45 s clear of any boundary.
#: 0.3 s catches all three with margin on both sides.
_WORD_EDGE_TOLERANCE_S = 0.3


def _effective_threshold(y_text: str, t_text: str, threshold_pct: float) -> float:
    """Similarity bar for this pair, raised for short utterances.

    Backchannels are the dominant false-positive source for text dedup, so a
    pair where either side is under :data:`_SHORT_UTTERANCE_WORDS` words must
    clear :data:`_SHORT_UTTERANCE_THRESHOLD_PCT` instead of the configured
    threshold. Never lowers the caller's threshold.
    """
    if (
        len(y_text.split()) < _SHORT_UTTERANCE_WORDS
        or len(t_text.split()) < _SHORT_UTTERANCE_WORDS
    ):
        return max(threshold_pct, _SHORT_UTTERANCE_THRESHOLD_PCT)
    return threshold_pct


def _overlap_duration(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    """Overlap duration of half-open intervals ``[a_start, a_end)`` and ``[b_start, b_end)``."""
    return min(a_end, b_end) - max(a_start, b_start)


def shift_segments(segments: list[Segment], offset_s: float) -> list[Segment]:
    """Return ``segments`` with every timestamp moved later by ``offset_s``.

    The two WAVs are each written from their own first sample as if that
    sample were t=0, but the taps do not start together: whichever stream
    started later must be pushed forward by the delta before the two can be
    compared on one timeline. Without this the echo rule — which is
    overlap-based — never sees an echo and its original as concurrent, and
    speaker bleed lands in the transcript attributed to the wrong person.

    A non-positive ``offset_s`` returns the list unchanged (an unknown or
    already-aligned offset must shift nothing). Inputs are never mutated;
    word-level timestamps move with their segment so the JSON sidecar stays
    internally consistent.
    """
    if offset_s <= 0:
        return list(segments)
    shifted = []
    for s in segments:
        words = tuple(
            replace(w, start=w.start + offset_s, end=w.end + offset_s) for w in s.words
        )
        shifted.append(
            replace(s, start=s.start + offset_s, end=s.end + offset_s, words=words)
        )
    return shifted


def _echo_matches(you: Segment, them: list[Segment], threshold_pct: float) -> list[Segment]:
    """``Them`` segments that ``you`` appears to echo, in input order.

    A ``Them`` segment qualifies when it time-overlaps ``you`` (by at least
    :data:`_MIN_OVERLAP_S`) and scores ``fuzz.token_ratio >= threshold_pct``
    on stripped text. Empty/whitespace texts never count (no echo).

    Short utterances must clear a markedly higher bar — see
    :func:`_effective_threshold`.

    Returns the matches rather than a bool so the caller can trim ``you``
    against the exact intervals the speaker was talking over: a non-empty
    list means "echo somewhere in here", not "this whole segment is echo".
    """
    y_text = you.text.strip()
    if not y_text:
        return []
    matches = []
    for t in them:
        if t.speaker != "Them":
            continue
        t_text = t.text.strip()
        if not t_text:
            continue
        if fuzz.token_ratio(y_text, t_text) < _effective_threshold(
            y_text, t_text, threshold_pct
        ):
            continue
        if _overlap_duration(you.start, you.end, t.start, t.end) >= _MIN_OVERLAP_S:
            matches.append(t)
    return matches


def _word_is_echoed(word: Word, matches: list[Segment]) -> bool:
    """True if ``word``'s midpoint falls inside any matching ``Them`` interval.

    The midpoint — not the whole span — because Whisper's word boundaries are
    approximate and adjacent words routinely abut the segment edge.

    Each interval is widened by :data:`_WORD_EDGE_TOLERANCE_S` at both ends.
    A strict test left crumbs of the speaker's audio attached to genuine
    speech ("...let's see **and**", "**basis** okay that will end the
    recording") and stranded a lone echoed word as its own line — all three
    within 0.3 s of a boundary. Erring toward cutting at the seam is the
    right trade here: a crumb corrupts the sentence it lands in, while the
    word it might over-cut is already duplicated in the ``Them`` line.
    """
    mid = (word.start + word.end) / 2
    return any(
        t.start - _WORD_EDGE_TOLERANCE_S <= mid < t.end + _WORD_EDGE_TOLERANCE_S
        for t in matches
    )


def _trim_echoed_words(you: Segment, matches: list[Segment]) -> Segment | None:
    """Drop the words of ``you`` that the speaker was saying concurrently.

    Whisper segments the two tracks on different boundaries, so one mic
    segment routinely straddles echoed speaker audio *and* the user's own
    words (on ``2026-10-20_1553``, ``You 5.24–13.64`` opens with "okay
    testing it again let's see" and then runs into the speaker's audio).
    Flagging such a segment hides real speech; printing it duplicates the
    speaker's line. Removing just the echoed words does neither.

    Returns the trimmed segment with ``echo_suspected`` cleared — what
    survives is genuine speech, so it needs no marker — or ``None`` when
    every word was echoed. ``start``/``end`` are tightened to the surviving
    words. A segment with no word timings cannot be trimmed and is returned
    marked, which is the pre-trimming behaviour.
    """
    if not you.words:
        return replace(you, echo_suspected=True)
    kept = tuple(w for w in you.words if not _word_is_echoed(w, matches))
    if not kept:
        return None
    if len(kept) == len(you.words):
        return you  # nothing actually covered; leave it untouched
    text = "".join(w.text for w in kept).strip()
    if not text:
        return None
    return replace(
        you,
        text=text,
        start=kept[0].start,
        end=kept[-1].end,
        words=kept,
        echo_suspected=False,
    )


def merge_transcripts(
    you: list[Segment],
    them: list[Segment],
    *,
    dedup_threshold: float = 0.6,
) -> list[Segment]:
    """Interleave ``you`` and ``them`` chronologically, trimming echoed speech.

    A ``You`` segment is considered to echo a ``Them`` segment when the two
    time-overlap (half-open intervals, overlap >= 0.05 s) and the stripped
    texts score ``fuzz.token_ratio >= dedup_threshold * 100``. Utterances
    under four words must clear a near-exact similarity bar, so ordinary
    backchannels ("yeah", "right") survive.

    Echo is removed at **word** level, not segment level: only the words the
    speaker was saying concurrently are dropped, so a segment that straddles
    echo and genuine speech keeps the genuine half (see
    :func:`_trim_echoed_words`). A ``You`` segment every word of which was
    echoed is dropped; one that is trimmed comes back with
    ``echo_suspected=False``, since what remains is the user's own speech.
    Only a segment with no word timings — which cannot be trimmed — is
    returned marked.

    ``Them`` segments are never touched. Output is chronological; equal
    ``start`` values order ``Them`` before ``You``, then by ``text``. Inputs
    are not mutated; a new list of (possibly replaced) segments is returned.

    ``dedup_threshold`` must be in ``[0, 1]``; ``None`` is treated as 0.6.
    """
    threshold = _DEFAULT_THRESHOLD if dedup_threshold is None else float(dedup_threshold)
    if not 0.0 <= threshold <= 1.0:
        raise ValueError(f"dedup_threshold must be in [0, 1], got {dedup_threshold!r}")
    threshold_pct = threshold * 100.0

    merged = list(them)
    for s in you:
        matches = _echo_matches(s, them, threshold_pct)
        if not matches:
            merged.append(s)
            continue
        trimmed = _trim_echoed_words(s, matches)
        if trimmed is not None:
            merged.append(trimmed)

    merged.sort(key=lambda s: (s.start, 0 if s.speaker == "Them" else 1, s.text))
    return merged
