"""Tests for mr.core.merge: merge_transcripts echo dedup + chronological interleave."""

from dataclasses import replace

import pytest

from mr.core.merge import merge_transcripts, shift_segments
from mr.core.schema import Segment, Word


def seg(speaker: str, text: str, start: float, end: float) -> Segment:
    return Segment(speaker=speaker, text=text, start=start, end=end)


def kept(out: list[Segment]) -> list[Segment]:
    """Segments that reach the Markdown transcript (echo-suspected omitted)."""
    return [s for s in out if not s.echo_suspected]


def flagged(out: list[Segment]) -> list[Segment]:
    """Segments marked as suspected echo (kept in the JSON sidecar only)."""
    return [s for s in out if s.echo_suspected]


def test_echo_you_marked_when_similar_and_overlapping() -> None:
    you = [seg("You", "let's get started with the roadmap", 1.0, 3.0)]
    them = [seg("Them", "Let's get started with the roadmap!", 0.5, 3.5)]
    out = merge_transcripts(you, them)
    # Marked, not deleted: the Them segment is what the transcript shows,
    # but the You segment is still present and recoverable.
    assert kept(out) == them
    assert [s.text for s in flagged(out)] == ["let's get started with the roadmap"]
    assert len(out) == 2


def test_real_interruption_you_kept_when_not_similar() -> None:
    you = [seg("You", "wait, I disagree with that point", 1.0, 3.0)]
    them = [seg("Them", "the quarterly numbers are solid", 0.5, 3.5)]
    out = merge_transcripts(you, them)
    assert out == sorted([*them, *you], key=lambda s: s.start)


def test_no_overlap_keeps_all_sorted_chronologically() -> None:
    you = [seg("You", "hello", 10.0, 11.0), seg("You", "thanks", 0.0, 1.0)]
    them = [seg("Them", "hi there", 5.0, 6.0)]
    out = merge_transcripts(you, them)
    assert [s.start for s in out] == [0.0, 5.0, 10.0]
    assert [s.speaker for s in out] == ["You", "Them", "You"]


def test_same_start_them_sorts_before_you() -> None:
    you = [seg("You", "hello", 2.0, 4.0)]
    them = [seg("Them", "goodbye", 2.0, 3.0)]  # no text similarity; both survive
    out = merge_transcripts(you, them)
    assert [(s.speaker, s.text) for s in out] == [("Them", "goodbye"), ("You", "hello")]


def test_same_start_tie_breaks_by_text_after_speaker() -> None:
    them = [seg("Them", "zeta", 1.0, 2.0), seg("Them", "alpha", 1.0, 2.0)]
    out = merge_transcripts([], them)
    assert [s.text for s in out] == ["alpha", "zeta"]


def test_empty_text_you_kept_without_crash() -> None:
    you = [seg("You", "   ", 1.0, 2.0)]
    them = [seg("Them", "   ", 0.5, 2.5)]
    out = merge_transcripts(you, them)
    assert len(out) == 2
    assert seg("You", "   ", 1.0, 2.0) in out


def test_you_empty_text_them_real_kept() -> None:
    you = [seg("You", "", 1.0, 2.0)]
    them = [seg("Them", "real content", 0.5, 2.5)]
    out = merge_transcripts(you, them)
    assert len(out) == 2


def test_overlap_below_min_duration_kept() -> None:
    # Overlap of exactly 0.04 s (< 0.05) must not count as concurrent.
    you = [seg("You", "same words here", 2.96, 3.96)]
    them = [seg("Them", "same words here", 2.0, 3.0)]
    out = merge_transcripts(you, them)
    assert len(out) == 2


def test_threshold_one_only_flags_exact_matches() -> None:
    exact_you = seg("You", "hello world", 1.0, 2.0)
    exact_them = seg("Them", "hello world", 0.5, 2.5)
    fuzzy_you = seg("You", "hello wordz", 3.0, 4.0)
    fuzzy_them = seg("Them", "hello world", 2.5, 4.5)

    out = merge_transcripts([exact_you, fuzzy_you], [exact_them, fuzzy_them], dedup_threshold=1.0)
    assert len(out) == 4  # nothing is dropped
    assert len(kept(out)) == 3
    assert fuzzy_you in kept(out)  # near-miss kept at threshold 1.0
    assert [s.text for s in flagged(out)] == ["hello world"]


def test_threshold_none_defaults_to_06() -> None:
    you = [seg("You", "let's get started with the roadmap", 1.0, 3.0)]
    them = [seg("Them", "Let's get started with the roadmap!", 0.5, 3.5)]
    assert kept(merge_transcripts(you, them, dedup_threshold=None)) == them
    assert kept(merge_transcripts(you, them)) == them


def test_invalid_threshold_raises() -> None:
    with pytest.raises(ValueError, match="dedup_threshold"):
        merge_transcripts([], [], dedup_threshold=1.5)
    with pytest.raises(ValueError, match="dedup_threshold"):
        merge_transcripts([], [], dedup_threshold=-0.1)


def test_inputs_not_mutated() -> None:
    you = [seg("You", "echoed line", 1.0, 2.0), seg("You", "kept line", 5.0, 6.0)]
    them = [seg("Them", "echoed line", 0.5, 2.5)]
    you_before = list(you)
    them_before = list(them)
    out = merge_transcripts(you, them)
    assert you == you_before
    assert them == them_before
    assert out is not you
    assert out is not them


def test_empty_inputs() -> None:
    assert merge_transcripts([], []) == []


def test_only_you_no_echo() -> None:
    you = [seg("You", "a", 0.0, 1.0), seg("You", "b", 1.0, 2.0)]
    out = merge_transcripts(you, [])
    assert out == you


def test_you_echo_flagged_even_if_them_starts_later() -> None:
    you = [seg("You", "we should ship on friday", 0.0, 2.0)]
    them = [seg("Them", "we should ship on friday", 1.0, 3.0)]
    out = merge_transcripts(you, them)
    assert kept(out) == them
    assert flagged(out) == [replace(you[0], echo_suspected=True)]


def test_matching_but_non_overlapping_you_is_kept() -> None:
    """Echo detection is overlap-only: a later match is not echo.

    The delay-aware rule was removed — it keyed off a mic/system start-time
    difference that measured tap-callback scheduling, not acoustic delay, and
    bought a ~10 s deletion window on that basis. Repetition at a distance is
    ordinary conversation ("Washington DC" said again a few seconds later).
    """
    you = [seg("You", "Washington DC come watch", 12.0, 18.0)]
    them = [seg("Them", "Washington DC come watch", 3.0, 9.0)]
    out = merge_transcripts(you, them)
    assert flagged(out) == []
    assert you[0] in kept(out)
    assert them[0] in kept(out)


def test_genuine_you_kept_when_low_similarity() -> None:
    you = [seg("You", "testing one two three hello", 3.0, 11.0)]
    them = [seg("Them", "Washington DC live markets", 3.14, 9.38)]
    out = merge_transcripts(you, them)
    assert flagged(out) == []  # low token ratio -> kept despite overlapping
    assert len(kept(out)) == 2


# ---------------------------------------------------------------------------
# Short-utterance guard: backchannels are the dominant dedup false positive.
# Both people saying "yeah" is conversation, not echo.
# ---------------------------------------------------------------------------


def test_backchannel_yeah_survives_overlap() -> None:
    """Both sides saying "yeah" within the window: the You segment must survive."""
    you = [seg("You", "yeah", 1.0, 1.4)]
    them = [seg("Them", "Yeah.", 0.9, 1.6)]
    out = merge_transcripts(you, them)
    assert flagged(out) == []
    assert you[0] in kept(out)
    assert len(kept(out)) == 2


@pytest.mark.parametrize(
    ("you_text", "them_text"),
    [
        ("right", "Right?"),
        ("exactly", "Exactly!"),
        ("okay sounds good", "Okay, sounds good."),
        ("mm hmm", "mhm"),
    ],
)
def test_short_backchannels_survive(you_text: str, them_text: str) -> None:
    you = [seg("You", you_text, 2.0, 2.6)]
    them = [seg("Them", them_text, 1.8, 2.8)]
    out = merge_transcripts(you, them)
    assert flagged(out) == [], f"{you_text!r} vs {them_text!r} wrongly flagged as echo"
    assert len(kept(out)) == 2


def test_short_utterance_guard_does_not_protect_long_echo() -> None:
    """The guard applies to short utterances only — real echo is still caught."""
    you = [seg("You", "so the migration lands on thursday morning", 1.0, 4.0)]
    them = [seg("Them", "So the migration lands on Thursday morning.", 0.8, 4.2)]
    out = merge_transcripts(you, them)
    assert len(flagged(out)) == 1
    assert kept(out) == them


def test_identical_short_utterance_still_flagged() -> None:
    """A verbatim short phrase still clears the raised bar (near-exact match)."""
    you = [seg("You", "sounds good", 1.0, 1.8)]
    them = [seg("Them", "sounds good", 0.9, 1.9)]
    out = merge_transcripts(you, them)
    assert len(flagged(out)) == 1


def test_segments_without_word_timings_are_marked_never_dropped() -> None:
    """The no-word-timings fallback: judged whole, marked, but never deleted.

    Segments carrying word timings are trimmed instead (and a fully echoed
    one IS dropped) — see the word-level trimming tests below. Everything
    from the real pipeline has words, so this path is the exception.
    """
    you = [seg("You", f"echoed line number {i}", float(i), i + 1.0) for i in range(5)]
    them = [seg("Them", f"echoed line number {i}", i - 0.1, i + 1.1) for i in range(5)]
    out = merge_transcripts(you, them)
    assert len(out) == 10
    assert len(flagged(out)) == 5  # all You segments suspected
    assert all(s.words == () for s in flagged(out))  # why they were not trimmed
    assert {s.text for s in out} == {f"echoed line number {i}" for i in range(5)}


# ---------------------------------------------------------------------------
# shift_segments: the two WAVs each start at their own first sample, so one
# track must be pushed forward before the overlap rule can compare them.
# ---------------------------------------------------------------------------


def test_shift_segments_moves_start_and_end() -> None:
    out = shift_segments([seg("Them", "hello", 1.0, 3.0)], 10.49)
    assert [(s.start, s.end) for s in out] == [(11.49, 13.49)]
    assert out[0].text == "hello"
    assert out[0].speaker == "Them"


def test_shift_segments_zero_and_negative_are_no_ops() -> None:
    segments = [seg("Them", "hello", 1.0, 3.0)]
    assert shift_segments(segments, 0.0) == segments
    assert shift_segments(segments, -5.0) == segments


def test_shift_segments_does_not_mutate_inputs() -> None:
    segments = [seg("Them", "hello", 1.0, 3.0)]
    before = list(segments)
    out = shift_segments(segments, 2.0)
    assert segments == before
    assert out is not segments


def test_shift_segments_moves_word_timestamps_too() -> None:
    """Word timings are exposed in the JSON sidecar; they must stay consistent."""
    word = Word(text=" hello", start=1.0, end=1.5, probability=0.9)
    s = Segment(speaker="Them", text=" hello", start=1.0, end=1.5, words=(word,))
    out = shift_segments([s], 10.0)
    assert (out[0].start, out[0].end) == (11.0, 11.5)
    assert [(w.start, w.end) for w in out[0].words] == [(11.0, 11.5)]
    assert out[0].words[0].text == " hello"


def test_shift_segments_preserves_echo_flag() -> None:
    s = replace(seg("You", "echoed", 1.0, 2.0), echo_suspected=True)
    assert shift_segments([s], 3.0)[0].echo_suspected is True


def test_shift_segments_empty_list() -> None:
    assert shift_segments([], 5.0) == []


# ---------------------------------------------------------------------------
# Word-level trimming: Whisper segments the two tracks on different
# boundaries, so a mic segment routinely holds echo AND genuine speech.
# Only the echoed words are removed.
# ---------------------------------------------------------------------------


def wseg(speaker: str, text_times: list[tuple[str, float, float]]) -> Segment:
    """Build a Segment with word timings from ``(text, start, end)`` triples."""
    words = tuple(
        Word(text=t, start=s, end=e, probability=0.9) for t, s, e in text_times
    )
    return Segment(
        speaker=speaker,
        text="".join(w.text for w in words).strip(),
        start=words[0].start,
        end=words[-1].end,
        words=words,
    )


def test_trim_keeps_genuine_words_before_the_echo() -> None:
    """The 2026-10-20_1553 case: real speech, then the speaker's audio."""
    you = [
        wseg(
            "You",
            [(" okay", 5.3, 6.0), (" testing", 6.0, 7.0), (" roadmap", 11.0, 12.0)],
        )
    ]
    them = [seg("Them", "okay testing roadmap", 10.5, 13.0)]
    out = merge_transcripts(you, them)
    survivor = [s for s in out if s.speaker == "You"]
    assert len(survivor) == 1
    assert survivor[0].text == "okay testing"
    assert survivor[0].echo_suspected is False  # trimmed speech needs no marker
    assert (survivor[0].start, survivor[0].end) == (5.3, 7.0)


def test_trim_keeps_genuine_words_after_the_echo() -> None:
    """Echo first, then the user's own words (the 'that will end it' case)."""
    you = [
        wseg(
            "You",
            [(" roadmap", 24.5, 25.5), (" end", 26.5, 27.0), (" recording", 27.0, 28.0)],
        )
    ]
    them = [seg("Them", "roadmap end recording", 24.2, 26.0)]
    out = merge_transcripts(you, them)
    survivor = [s for s in out if s.speaker == "You"]
    assert [s.text for s in survivor] == ["end recording"]
    assert survivor[0].start == 26.5


def test_fully_echoed_segment_is_dropped() -> None:
    you = [wseg("You", [(" same", 1.0, 1.5), (" words", 1.5, 2.0)])]
    them = [seg("Them", "same words", 0.5, 3.0)]
    out = merge_transcripts(you, them)
    assert [s.speaker for s in out] == ["Them"]


def test_segment_without_word_timings_is_marked_not_trimmed() -> None:
    """No words to trim: fall back to flagging the whole segment."""
    you = [seg("You", "let's get started with the roadmap", 1.0, 3.0)]
    them = [seg("Them", "Let's get started with the roadmap!", 0.5, 3.5)]
    out = merge_transcripts(you, them)
    assert len(flagged(out)) == 1
    assert flagged(out)[0].words == ()


def test_trim_leaves_non_echoed_segment_untouched() -> None:
    """No textual match: the segment is returned as-is, words intact."""
    you = [wseg("You", [(" wait", 1.0, 1.5), (" disagree", 1.5, 2.0)])]
    them = [seg("Them", "the quarterly numbers are solid", 0.5, 3.0)]
    out = merge_transcripts(you, them)
    assert you[0] in out


def test_trim_cuts_crumbs_within_the_edge_tolerance() -> None:
    """A word brushing the Them boundary is echo, not speech.

    From 2026-10-20_1553: a strict midpoint test left "and" (the speaker's
    first word) glued to the end of genuine speech. Its midpoint sat just
    outside the Them interval, well inside the tolerance.
    """
    you = [
        wseg(
            "You",
            [(" okay", 5.3, 6.0), (" testing", 6.0, 7.0), (" and", 10.9, 11.36)],
        )
    ]
    them = [seg("Them", "okay testing and she used to write", 11.0, 16.0)]
    out = merge_transcripts(you, them)
    survivor = [s for s in out if s.speaker == "You"]
    assert [s.text for s in survivor] == ["okay testing"]


def test_trim_keeps_word_clear_of_the_boundary() -> None:
    """Beyond the tolerance, genuine speech next to echo still survives."""
    you = [wseg("You", [(" hello", 4.0, 4.6), (" there", 5.5, 6.5)])]
    them = [seg("Them", "hello there", 5.2, 9.0)]
    out = merge_transcripts(you, them)
    survivor = [s for s in out if s.speaker == "You"]
    # "hello" midpoint 4.3 is 0.9 s clear of 5.2; "there" is covered outright.
    assert [s.text for s in survivor] == ["hello"]


def test_trim_tolerance_drops_an_overhanging_last_word() -> None:
    """The "dilu" case: the last word overhung the Them end and survived alone.

    Under a strict boundary test this segment trimmed down to its final
    word, which then printed as a meaningless one-word line. The word must
    be inside the matching segment — a genuinely isolated short utterance is
    protected by the short-utterance guard and never reaches trimming (see
    :func:`test_short_backchannels_survive`).
    """
    you = [
        wseg(
            "You",
            [
                (" english", 13.7, 14.3),
                (" even", 14.3, 14.9),
                (" that", 14.9, 15.3),
                (" i", 15.3, 15.6),
                (" used", 15.6, 15.92),
                (" dilu", 15.92, 16.2),
            ],
        )
    ]
    them = [seg("Them", "English, even that I used to write in Telugu", 10.89, 16.05)]
    out = merge_transcripts(you, them)
    assert [s.speaker for s in out] == ["Them"]  # nothing survives — all echo


def test_trim_does_not_mutate_inputs() -> None:
    you = [wseg("You", [(" a", 1.0, 1.5), (" b", 11.0, 11.5)])]
    them = [seg("Them", "a b", 10.5, 13.0)]
    before = list(you)
    merge_transcripts(you, them)
    assert you == before
    assert you[0].words[1].text == " b"


def test_echo_only_overlaps_after_shifting_is_detected() -> None:
    """The misalignment case: the system tap started ~10.5 s after the mic.

    As captured, the echoed ``You`` segment sits ~10.5 s *after* its ``Them``
    original and nothing overlaps, so the overlap rule never fires and the
    speaker's words land in the transcript under ``You``. Shifting the late
    system track forward restores the concurrency the rule depends on.
    """
    you = [seg("You", "i'll talk only in english even that i used to write", 13.0, 19.0)]
    them = [seg("Them", "I'll talk only in English, even that I used to write", 0.5, 6.5)]

    # Unshifted: no overlap, so no echo is detected.
    assert flagged(merge_transcripts(you, them)) == []

    # Shifted onto one timeline: the pair overlaps and the echo is caught.
    out = merge_transcripts(you, shift_segments(them, 10.49))
    assert len(flagged(out)) == 1
    assert flagged(out)[0].speaker == "You"
    assert len(kept(out)) == 1
    assert kept(out)[0].speaker == "Them"
