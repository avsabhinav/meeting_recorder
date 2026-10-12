"""Merge mic (You) and system (Them) transcripts into one deduplicated stream.

Always-on safety net for residual echo that OS acoustic-echo-cancellation
(AEC) leaves behind: any ``You`` segment that time-overlaps a ``Them``
segment with similar text is treated as an echo and dropped. See
``docs/architecture.md`` decision #2 and ``spike/echo_check.py`` for the
scoring rationale.
"""

from __future__ import annotations

from rapidfuzz import fuzz

from mr.core.schema import Segment

#: Minimum overlap duration (seconds) for a pair to count as time-overlapping.
_MIN_OVERLAP_S = 0.05

#: Default echo threshold (see :func:`merge_transcripts`).
_DEFAULT_THRESHOLD = 0.6


def _overlap_duration(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    """Overlap duration of half-open intervals ``[a_start, a_end)`` and ``[b_start, b_end)``."""
    return min(a_end, b_end) - max(a_start, b_start)


def _is_echo(you: Segment, them: list[Segment], threshold_pct: float) -> bool:
    """True if ``you`` duplicates concurrent ``Them`` audio (echo).

    A ``Them`` segment that time-overlaps ``you`` (by at least
    :data:`_MIN_OVERLAP_S`) and scores ``fuzz.token_ratio >= threshold_pct``
    on stripped text marks ``you`` as echo. Empty/whitespace texts never
    count (no echo).
    """
    y_text = you.text.strip()
    if not y_text:
        return False
    for t in them:
        if t.speaker != "Them":
            continue
        if _overlap_duration(you.start, you.end, t.start, t.end) < _MIN_OVERLAP_S:
            continue
        t_text = t.text.strip()
        if not t_text:
            continue
        if fuzz.token_ratio(y_text, t_text) >= threshold_pct:
            return True
    return False


def merge_transcripts(
    you: list[Segment], them: list[Segment], *, dedup_threshold: float = 0.6
) -> list[Segment]:
    """Interleave ``you`` and ``them`` chronologically, dropping echoed ``You`` segments.

    A ``You`` segment is dropped when it time-overlaps (half-open intervals,
    overlap >= 0.05 s) any ``Them`` segment whose stripped text scores
    ``fuzz.token_ratio >= dedup_threshold * 100``. Survivors are returned in
    chronological order; equal ``start`` values order ``Them`` before
    ``You``, then by ``text``. Inputs are not mutated; a new list is
    returned.

    ``dedup_threshold`` must be in ``[0, 1]``; ``None`` is treated as 0.6.
    """
    threshold = _DEFAULT_THRESHOLD if dedup_threshold is None else float(dedup_threshold)
    if not 0.0 <= threshold <= 1.0:
        raise ValueError(f"dedup_threshold must be in [0, 1], got {dedup_threshold!r}")
    threshold_pct = threshold * 100.0

    surviving = list(them)
    surviving.extend(s for s in you if not _is_echo(s, them, threshold_pct))

    surviving.sort(key=lambda s: (s.start, 0 if s.speaker == "Them" else 1, s.text))
    return surviving
