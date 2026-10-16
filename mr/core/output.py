"""Transcript writers: Markdown (`.md`) and optional JSON sidecar.

Pure rendering functions plus thin path-writing helpers. All rendering is
deterministic string/dict construction — no I/O beyond ``write_transcript``
and ``write_json``.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from mr.core.schema import Segment, format_ts

SCHEMA_VERSION = 1
PARTICIPANTS_LINE = "You (mic), Them (system)"

# First characters that give a bare YAML scalar special meaning.
_YAML_SPECIAL_FIRST = set("-?:[]{}#&*!|>'\"%@\u0060")


def _format_duration(seconds: float) -> str:
    """Format total seconds as ``<m>m <s>s`` with floored components."""
    total = int(seconds)  # floor for non-negative input
    return f"{total // 60}m {total % 60}s"


def _yaml_scalar(value: str) -> str:
    """Emit ``value`` as an Obsidian-safe YAML scalar.

    Quoted (double, with ``"`` escaped) when the value contains ``": "``
    or starts with a YAML-meaningful character; bare otherwise.
    """
    if ": " in value or (value and value[0] in _YAML_SPECIAL_FIRST):
        return '"' + value.replace('"', '\\"') + '"'
    return value


def _attendees_flow(attendees: list[object]) -> str:
    """Render an attendees list as a YAML flow list, quoting as needed."""
    parts = []
    for a in attendees:
        s = str(a)
        if "," in s or ": " in s:
            s = '"' + s.replace('"', '\\"') + '"'
        parts.append(s)
    return "[" + ", ".join(parts) + "]"


def _render_frontmatter(
    *,
    context: dict[str, object],
    stamp: str,
    source_dir: str,
    duration_seconds: float,
) -> str:
    """Build the ``---``-delimited Obsidian YAML frontmatter block."""
    title = str(context.get("title") or stamp)
    start = context.get("start")
    date_value = str(start) if start else date.today().isoformat()
    lines = [
        "---",
        f"title: {_yaml_scalar(title)}",
        f"date: {_yaml_scalar(date_value)}",
    ]
    attendees = context.get("attendees")
    if isinstance(attendees, list) and attendees:
        lines.append(f"attendees: {_attendees_flow(attendees)}")
    notes = context.get("notes")
    if isinstance(notes, str) and notes:
        lines.append(f"notes: {_yaml_scalar(notes)}")
    lines.append(f"duration: {_format_duration(duration_seconds)}")
    lines.append(f"source: {_yaml_scalar(source_dir)}")
    lines.append("---")
    return "\n".join(lines)


def render_transcript_md(
    *,
    stamp: str,
    source_dir: str,
    segments: list[Segment],
    duration_seconds: float,
    context: dict[str, object] | None = None,
) -> str:
    """Render the transcript Markdown as a pure string (no file I/O).

    When ``context`` is a non-empty dict, an Obsidian YAML frontmatter
    block is prepended; otherwise the output is unchanged.
    """
    lines = [
        f"# Meeting — {stamp}",
        "",
        f"- **Duration:** {_format_duration(duration_seconds)}",
        f"- **Participants:** {PARTICIPANTS_LINE}",
        f"- **Source:** {source_dir}",
        "",
        "## Transcript",
        "",
    ]
    for seg in segments:
        lines.append(f"**{seg.speaker} ({format_ts(seg.start)}):** {seg.text}")
        lines.append("")
    # Join and drop the trailing blank line added after the last segment.
    body = "\n".join(lines).rstrip("\n")
    if not context:
        return body
    return _render_frontmatter(
        context=context, stamp=stamp, source_dir=source_dir, duration_seconds=duration_seconds
    ) + "\n\n" + body


def write_transcript(md_path: str | Path, text: str) -> None:
    """Write transcript text to ``md_path``, creating parent dirs.

    Ensures the file ends with exactly one trailing newline.
    """
    path = Path(md_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not text.endswith("\n"):
        text += "\n"
    path.write_text(text, encoding="utf-8")


def render_transcript_json(
    segments: list[Segment], *, stamp: str, context: dict[str, object] | None = None
) -> dict:
    """Build the JSON sidecar payload as plain dict/list (no file I/O).

    When ``context`` is a non-empty dict, it is included as a ``"context"``
    key (the raw passed-in dict); otherwise the output is unchanged.
    """
    payload: dict = {
        "schema_version": SCHEMA_VERSION,
        "stamp": stamp,
        "segments": [
            {"speaker": seg.speaker, "start": seg.start, "end": seg.end, "text": seg.text}
            for seg in segments
        ],
    }
    if context:
        payload["context"] = context
    return payload


def write_json(json_path: str | Path, data: dict) -> None:
    """Write ``data`` as pretty-printed JSON to ``json_path``, creating parent dirs."""
    path = Path(json_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
