"""Transcript writers: Markdown (`.md`) and optional JSON sidecar.

Pure rendering functions plus thin path-writing helpers. All rendering is
deterministic string/dict construction — no I/O beyond ``write_transcript``
and ``write_json``.
"""

from __future__ import annotations

import json
from pathlib import Path

from mr.core.schema import Segment, format_ts

SCHEMA_VERSION = 1
PARTICIPANTS_LINE = "You (mic), Them (system)"


def _format_duration(seconds: float) -> str:
    """Format total seconds as ``<m>m <s>s`` with floored components."""
    total = int(seconds)  # floor for non-negative input
    return f"{total // 60}m {total % 60}s"


def render_transcript_md(
    *,
    stamp: str,
    source_dir: str,
    segments: list[Segment],
    duration_seconds: float,
) -> str:
    """Render the transcript Markdown as a pure string (no file I/O)."""
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
    return "\n".join(lines).rstrip("\n")


def write_transcript(md_path: str | Path, text: str) -> None:
    """Write transcript text to ``md_path``, creating parent dirs.

    Ensures the file ends with exactly one trailing newline.
    """
    path = Path(md_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not text.endswith("\n"):
        text += "\n"
    path.write_text(text, encoding="utf-8")


def render_transcript_json(segments: list[Segment], *, stamp: str) -> dict:
    """Build the JSON sidecar payload as plain dict/list (no file I/O)."""
    return {
        "schema_version": SCHEMA_VERSION,
        "stamp": stamp,
        "segments": [
            {"speaker": seg.speaker, "start": seg.start, "end": seg.end, "text": seg.text}
            for seg in segments
        ],
    }


def write_json(json_path: str | Path, data: dict) -> None:
    """Write ``data`` as pretty-printed JSON to ``json_path``, creating parent dirs."""
    path = Path(json_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
