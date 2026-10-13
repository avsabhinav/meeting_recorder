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

#: Tolerance (seconds) added to ``echo_lag_s`` when checking whether a ``You``
#: segment follows its ``Them`` original within the mic↔system stream offset.
_ECHO_LAG_TOLERANCE_S = 0.75


def _overlap_duration(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    """Overlap duration of half-open intervals ``[a_start, a_end)`` and ``[b_start, b_end)``."""
    return min(a_end, b_end) - max(a_start, b_start)


def _is_echo(
    you: Segment, them: list[Segment], threshold_pct: float, echo_lag_s: float | None
) -> bool:
    """True if ``you`` duplicates concurrent ``Them`` audio (echo).

    A ``Them`` segment that time-overlaps ``you`` (by at least
    :data:`_MIN_OVERLAP_S`) and scores ``fuzz.token_ratio >= threshold_pct``
    on stripped text marks ``you`` as echo. When ``echo_lag_s`` is a
    non-negative number, a ``Them`` segment that textually matches ``you``
    AND precedes it by at most ``echo_lag_s + :data:`_ECHO_LAG_TOLERANCE_S``
    seconds also marks ``you`` as echo (delayed acoustic echo).
    Empty/whitespace texts never count (no echo).
    """
    y_text = you.text.strip()
    if not y_text:
        return False
    for t in them:
        if t.speaker != "Them":
            continue
        t_text = t.text.strip()
        if not t_text:
            continue
        if fuzz.token_ratio(y_text, t_text) < threshold_pct:
            continue
        # Existing overlap rule: a textually matching Them segment that
        # time-overlaps this You segment (>= _MIN_OVERLAP_S) marks it as echo.
        if _overlap_duration(you.start, you.end, t.start, t.end) >= _MIN_OVERLAP_S:
            return True
        # Delayed acoustic echo: mic records the system audio `echo_lag_s` s after
        # it played, so the echoed You segment FOLLOWS (not overlaps) its Them
        # original. A textually matching Them segment that precedes this You
        # segment within the stream-offset window also marks it as echo.
        if echo_lag_s is not None and echo_lag_s >= 0:
            if (
                you.start >= t.start
                and (you.start - t.start) <= float(echo_lag_s) + _ECHO_LAG_TOLERANCE_S
            ):
                return True
    return False


def merge_transcripts(
    you: list[Segment],
    them: list[Segment],
    *,
    dedup_threshold: float = 0.6,
    echo_lag_s: float | None = None,
) -> list[Segment]:
    """Interleave ``you`` and ``them`` chronologically, dropping echoed ``You`` segments.

    A ``You`` segment is dropped when it time-overlaps (half-open intervals,
    overlap >= 0.05 s) any ``Them`` segment whose stripped text scores
    ``fuzz.token_ratio >= dedup_threshold * 100``. When ``echo_lag_s`` is a
    non-negative number, a ``You`` segment is also dropped when it follows
    (does not overlap) a textually matching ``Them`` segment by at most
    ``echo_lag_s + 0.75`` seconds — the delayed acoustic-echo case where the
    mic records the system audio after it was played. Survivors are returned
    in chronological order; equal ``start`` values order ``Them`` before
    ``You``, then by ``text``. Inputs are not mutated; a new list is
    returned.

    ``dedup_threshold`` must be in ``[0, 1]``; ``None`` is treated as 0.6.
    ``echo_lag_s`` of ``None`` disables the delay-aware rule (backward
    compatible).
    """
    threshold = _DEFAULT_THRESHOLD if dedup_threshold is None else float(dedup_threshold)
    if not 0.0 <= threshold <= 1.0:
        raise ValueError(f"dedup_threshold must be in [0, 1], got {dedup_threshold!r}")
    threshold_pct = threshold * 100.0

    surviving = list(them)
    surviving.extend(s for s in you if not _is_echo(s, them, threshold_pct, echo_lag_s))

    surviving.sort(key=lambda s: (s.start, 0 if s.speaker == "Them" else 1, s.text))
    return surviving
