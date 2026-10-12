#!/usr/bin/env python3
"""Manual test driver: run production mr.core pipeline on a captured recording dir.

Usage: driver.py <out_dir>

Reads <out_dir>/mic.wav + <out_dir>/system.wav (16 kHz mono), transcribes both with
the production mr.core.transcribe (real mlx-whisper, offline), merges with echo dedup,
and writes transcript.md + transcript.json next to them.

Throwaway test harness — NOT part of the shipped package.
"""

import json
import os
import sys

os.environ.setdefault("HF_HUB_OFFLINE", "1")  # cache-only at test time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from mr.core.merge import merge_transcripts  # noqa: E402
from mr.core.output import (  # noqa: E402
    render_transcript_json,
    render_transcript_md,
)
from mr.core.schema import Segment  # noqa: E402
from mr.core.transcribe import transcribe_audio  # noqa: E402


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: driver.py <out_dir>", file=sys.stderr)
        sys.exit(2)
    d = sys.argv[1]
    for f in ("mic.wav", "system.wav", "meta.json"):
        p = os.path.join(d, f)
        if not os.path.isfile(p):
            print(f"ERROR: missing {p}", file=sys.stderr)
            sys.exit(1)

    you = transcribe_audio(os.path.join(d, "mic.wav"), speaker="You")
    them = transcribe_audio(os.path.join(d, "system.wav"), speaker="Them")
    for res in (you, them):
        print(
            f"[{res.track}] speaker={res.speaker} audio={res.audio_seconds:.1f}s "
            f"wall={res.wall_seconds:.2f}s segments={len(res.segments)}"
        )

    merged = merge_transcripts(list(you.segments), list(them.segments), dedup_threshold=0.6)
    duration = max(seg.end for seg in you.segments + them.segments) if (you.segments or them.segments) else 0.0

    base = os.path.splitext(os.path.basename(d))[0] or "manual"
    md = render_transcript_md(
        stamp=base, source_dir=f"recordings/{base}",
        segments=merged, duration_seconds=duration,
    )
    md_path = os.path.join(d, "transcript.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md + "\n")

    jp = os.path.join(d, "transcript.json")
    with open(jp, "w", encoding="utf-8") as f:
        json.dump(render_transcript_json(merged, stamp=base), f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"\nwrote {md_path}\nwrote {jp}")
    print("\n==== transcript.md ====")
    print(md)
    print("segments kept:", len(merged))


if __name__ == "__main__":
    main()
