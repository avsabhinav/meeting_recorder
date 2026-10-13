"""Tests for mr.core.merge: merge_transcripts echo dedup + chronological interleave."""

import pytest

from mr.core.merge import merge_transcripts
from mr.core.schema import Segment


def seg(speaker: str, text: str, start: float, end: float) -> Segment:
    return Segment(speaker=speaker, text=text, start=start, end=end)


def test_echo_you_dropped_when_similar_and_overlapping() -> None:
    you = [seg("You", "let's get started with the roadmap", 1.0, 3.0)]
    them = [seg("Them", "Let's get started with the roadmap!", 0.5, 3.5)]
    out = merge_transcripts(you, them)
    assert out == them  # only the Them segment survives


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


def test_threshold_one_only_drops_exact_matches() -> None:
    exact_you = seg("You", "hello world", 1.0, 2.0)
    exact_them = seg("Them", "hello world", 0.5, 2.5)
    fuzzy_you = seg("You", "hello wordz", 3.0, 4.0)
    fuzzy_them = seg("Them", "hello world", 2.5, 4.5)

    out = merge_transcripts([exact_you, fuzzy_you], [exact_them, fuzzy_them], dedup_threshold=1.0)
    assert len(out) == 3
    assert fuzzy_you in out  # near-miss kept at threshold 1.0
    assert exact_you not in out


def test_threshold_none_defaults_to_06() -> None:
    you = [seg("You", "let's get started with the roadmap", 1.0, 3.0)]
    them = [seg("Them", "Let's get started with the roadmap!", 0.5, 3.5)]
    assert merge_transcripts(you, them, dedup_threshold=None) == them
    assert merge_transcripts(you, them) == them


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


def test_you_echo_dropped_even_if_them_starts_later() -> None:
    you = [seg("You", "we should ship on friday", 0.0, 2.0)]
    them = [seg("Them", "we should ship on friday", 1.0, 3.0)]
    out = merge_transcripts(you, them)
    assert out == them


def test_delayed_you_echo_dropped_when_follows_them_within_lag() -> None:
    you = [seg("You", "Washington DC come watch", 12.0, 18.0)]
    them = [seg("Them", "Washington DC come watch", 3.0, 9.0)]
    out = merge_transcripts(you, them, echo_lag_s=9.0)
    assert out == them  # only the Them segment survives


def test_delayed_you_echo_kept_without_echo_lag() -> None:
    you = [seg("You", "Washington DC come watch", 12.0, 18.0)]
    them = [seg("Them", "Washington DC come watch", 3.0, 9.0)]
    out = merge_transcripts(you, them)  # no echo_lag_s -> backward compat
    assert len(out) == 2
    assert you[0] in out
    assert them[0] in out


def test_genuine_you_kept_when_low_similarity_even_with_lag() -> None:
    you = [seg("You", "testing one two three hello", 3.0, 11.0)]
    them = [seg("Them", "Washington DC live markets", 3.14, 9.38)]
    out = merge_transcripts(you, them, echo_lag_s=9.0)
    assert len(out) == 2
    assert you[0] in out  # low token ratio -> kept
    assert them[0] in out


def test_delayed_you_echo_beyond_lag_kept() -> None:
    you = [seg("You", "same words here", 25.0, 30.0)]
    them = [seg("Them", "same words here", 1.0, 5.0)]
    out = merge_transcripts(you, them, echo_lag_s=5.0)
    assert len(out) == 2
    assert you[0] in out  # offset 24 > 5.75 -> kept
    assert them[0] in out


def test_existing_overlap_echo_still_dropped_with_echo_lag() -> None:
    you = [seg("You", "we should ship on friday", 0.0, 2.0)]
    them = [seg("Them", "we should ship on friday", 1.0, 3.0)]
    out = merge_transcripts(you, them, echo_lag_s=9.0)
    assert out == them  # overlap rule; You precedes Them but overlaps
