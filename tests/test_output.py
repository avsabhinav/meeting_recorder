"""Tests for ``mr.core.output`` (transcript Markdown + JSON sidecar)."""

from __future__ import annotations

import json
from datetime import date

from mr.core.output import (
    render_transcript_json,
    render_transcript_md,
    write_json,
    write_transcript,
)
from mr.core.schema import Segment


def _seg(speaker: str, start: float, end: float, text: str) -> Segment:
    return Segment(speaker=speaker, text=text, start=start, end=end)


SEGMENTS: list[Segment] = [
    _seg("You", 0.0, 2.1, "hey, can you hear me ok?"),
    _seg("Them", 2.3, 5.8, "yeah, I hear you just fine."),
    _seg("You", 6.0, 8.4, "great, thanks!"),
]


def test_render_transcript_md_exact_format() -> None:
    expected = (
        "# Meeting — 2026-08-24_1432\n"
        "\n"
        "- **Duration:** 42m 10s\n"
        "- **Participants:** You (mic), Them (system)\n"
        "- **Source:** recordings/2026-08-24_1432/\n"
        "\n"
        "## Transcript\n"
        "\n"
        "**You (00:00):** hey, can you hear me ok?\n"
        "\n"
        "**Them (00:02):** yeah, I hear you just fine.\n"
        "\n"
        "**You (00:06):** great, thanks!"
    )
    actual = render_transcript_md(
        stamp="2026-08-24_1432",
        source_dir="recordings/2026-08-24_1432/",
        segments=SEGMENTS,
        duration_seconds=2530,
    )
    assert actual == expected


def test_frontmatter_full_context() -> None:
    context = {
        "title": "Weekly 1:1",
        "start": "2026-10-15T10:00:00Z",
        "attendees": ["Alice", "Bob"],
        "notes": "Discuss Q3 roadmap",
    }
    actual = render_transcript_md(
        stamp="2026-08-24_1432",
        source_dir="recordings/2026-08-24_1432/",
        segments=SEGMENTS,
        duration_seconds=2530,
        context=context,
    )
    expected_head = (
        "---\n"
        "title: Weekly 1:1\n"
        "date: 2026-10-15T10:00:00Z\n"
        "attendees: [Alice, Bob]\n"
        "notes: Discuss Q3 roadmap\n"
        "duration: 42m 10s\n"
        "source: recordings/2026-08-24_1432/\n"
        "---\n"
        "\n"
        "# Meeting — 2026-08-24_1432\n"
    )
    assert actual.startswith(expected_head)
    # Body unchanged after the frontmatter.
    base = render_transcript_md(
        stamp="2026-08-24_1432",
        source_dir="recordings/2026-08-24_1432/",
        segments=SEGMENTS,
        duration_seconds=2530,
    )
    assert actual == expected_head + base[len("# Meeting — 2026-08-24_1432\n"):]


def test_frontmatter_title_date_only_omits_attendees_notes() -> None:
    md = render_transcript_md(
        stamp="2026-08-24_1432",
        source_dir="recordings/2026-08-24_1432/",
        segments=SEGMENTS,
        duration_seconds=2530,
        context={"title": "Sync", "start": "2026-10-15T10:00:00Z"},
    )
    block = md.split("---")[1]
    assert "attendees:" not in block
    assert "notes:" not in block
    assert block == (
        "\ntitle: Sync\ndate: 2026-10-15T10:00:00Z\nduration: 42m 10s"
        "\nsource: recordings/2026-08-24_1432/\n"
    )
    # Empty attendees list and empty notes are also omitted.
    md2 = render_transcript_md(
        stamp="s",
        source_dir="d",
        segments=SEGMENTS,
        duration_seconds=60,
        context={"title": "Sync", "attendees": [], "notes": ""},
    )
    block2 = md2.split("---")[1]
    assert "attendees:" not in block2
    assert "notes:" not in block2
    assert "date: " + date.today().isoformat() + "\n" in block2


def test_frontmatter_title_with_colon_is_quoted() -> None:
    md = render_transcript_md(
        stamp="2026-08-24_1432",
        source_dir="recordings/2026-08-24_1432/",
        segments=SEGMENTS,
        duration_seconds=2530,
        context={"title": "Q3: roadmap", "start": "2026-10-15T10:00:00Z"},
    )
    assert md.startswith('---\ntitle: "Q3: roadmap"\n')


def test_frontmatter_attendees_quoted_when_needed() -> None:
    md = render_transcript_md(
        stamp="s",
        source_dir="d",
        segments=SEGMENTS,
        duration_seconds=60,
        context={"title": "T", "attendees": ["Alice", "Bob, Jr.", "Carol: admin"]},
    )
    assert "attendees: [Alice, \"Bob, Jr.\", \"Carol: admin\"]\n" in md


def test_render_transcript_json_context_key() -> None:
    context = {"title": "Weekly 1:1", "attendees": ["Alice"]}
    with_ctx = render_transcript_json(SEGMENTS, stamp="2026-08-24_1432", context=context)
    assert with_ctx["context"] == context
    assert set(with_ctx) == {"schema_version", "stamp", "segments", "context"}
    without = render_transcript_json(SEGMENTS, stamp="2026-08-24_1432")
    assert "context" not in without
    empty = render_transcript_json(SEGMENTS, stamp="2026-08-24_1432", context={})
    assert "context" not in empty


def test_duration_formatting() -> None:
    cases = [
        (2530, "42m 10s"),
        (45, "0m 45s"),
        (3661, "61m 1s"),
    ]
    for duration, expected in cases:
        md = render_transcript_md(
            stamp="s",
            source_dir="d",
            segments=SEGMENTS,
            duration_seconds=duration,
        )
        assert f"- **Duration:** {expected}\n" in md


def test_render_transcript_json() -> None:
    data = render_transcript_json(SEGMENTS, stamp="2026-08-24_1432")
    assert data == {
        "schema_version": 1,
        "stamp": "2026-08-24_1432",
        "segments": [
            {"speaker": "You", "start": 0.0, "end": 2.1, "text": "hey, can you hear me ok?"},
            {
                "speaker": "Them",
                "start": 2.3,
                "end": 5.8,
                "text": "yeah, I hear you just fine.",
            },
            {"speaker": "You", "start": 6.0, "end": 8.4, "text": "great, thanks!"},
        ],
    }


def test_write_transcript_creates_parent_dirs(tmp_path) -> None:
    target = tmp_path / "a" / "b" / "transcript.md"
    text = "hello\nworld"
    write_transcript(target, text)
    assert target.parent.is_dir()
    assert target.read_text(encoding="utf-8") == "hello\nworld\n"


def test_write_transcript_keeps_existing_trailing_newline(tmp_path) -> None:
    target = tmp_path / "t.md"
    write_transcript(target, "hello\n")
    assert target.read_text(encoding="utf-8") == "hello\n"


def test_write_json_creates_parent_dirs(tmp_path) -> None:
    target = tmp_path / "deep" / "side" / "meta.json"
    data = render_transcript_json(SEGMENTS, stamp="2026-08-24_1432")
    write_json(target, data)
    assert target.parent.is_dir()
    content = target.read_text(encoding="utf-8")
    assert content.endswith("\n")
    assert json.loads(content) == data
