#!/usr/bin/env python3
"""Automated transcript verification (Step 3 of the simulated-conversation test).

Parses an attributed transcript Markdown file (``**You (MM:SS):** text`` /
``**Them (MM:SS):** text`` lines, as written by ``mr.core.output``) and, when a
recording dir is given, its ``meta.json``. Prints a ``[PASS]``/``[FAIL]``/
``[WARN]`` summary per check and an ``OVERALL: PASS|FAIL`` verdict.

Usage:
    verify_transcript.py <transcript.md> [--recording <recording_dir>]

Exit codes: 0 = all hard checks passed, 1 = one or more hard checks failed,
2 = usage/IO error (e.g. transcript file missing).

Stdlib only — standalone diagnostic, not part of the ``mr`` package.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# One line per segment, e.g. ``**You (00:00):** hello`` / ``**Them (01:07):** hi``.
SEGMENT_RE = re.compile(r"^\*\*(You|Them) \((\d+):(\d+)\):\*\* (.*)$")


def _normalize(text: str) -> str:
    """Lowercase and collapse internal whitespace for echo comparison."""
    return " ".join(text.lower().split())


def parse_transcript(text: str) -> list[dict]:
    """Parse transcript Markdown into segment records.

    Returns a list of ``{"speaker", "mm", "ss", "seconds", "text", "lineno"}``
    in file order. Header lines and anything not matching the segment pattern
    are ignored.
    """
    segments: list[dict] = []
    for lineno, raw_line in enumerate(text.splitlines(), start=1):
        m = SEGMENT_RE.match(raw_line.strip())
        if m is None:
            continue
        speaker, mm_s, ss_s, seg_text = m.groups()
        mm, ss = int(mm_s), int(ss_s)
        segments.append(
            {
                "speaker": speaker,
                "mm": mm,
                "ss": ss,
                "seconds": mm * 60 + ss,
                "text": seg_text,
                "lineno": lineno,
            }
        )
    return segments


def verify(segments: list[dict], meta: dict | None = None) -> list[dict]:
    """Run all checks over parsed segments and optional recording meta.

    Returns a list of result dicts ``{"name", "status", "detail"}`` where
    status is ``"PASS"``, ``"FAIL"``, ``"WARN"``, or ``"SKIP"`` (meta check
    when no meta was provided). ``WARN``/``"SKIP"`` never count as failures.
    """
    results: list[dict] = []

    if len(segments) == 0:
        results.append(
            {"name": "segments", "status": "FAIL", "detail": "no segments parsed"}
        )
        return results

    speakers = {seg["speaker"] for seg in segments}
    n_you = sum(1 for s in segments if s["speaker"] == "You")
    n_them = sum(1 for s in segments if s["speaker"] == "Them")
    if "You" in speakers and "Them" in speakers:
        results.append(
            {
                "name": "both_speakers",
                "status": "PASS",
                "detail": f"{n_you} You, {n_them} Them",
            }
        )
    else:
        missing = sorted({"You", "Them"} - speakers)
        results.append(
            {
                "name": "both_speakers",
                "status": "FAIL",
                "detail": f"missing speaker(s): {', '.join(missing)}",
            }
        )

    # Time order: seconds non-decreasing across the walk (equal allowed).
    order_detail = "timestamps non-decreasing"
    order_fail_at = None
    prev: int | None = None
    for seg in segments:
        if prev is not None and seg["seconds"] < prev:
            order_fail_at = seg["lineno"]
            break
        prev = seg["seconds"]
    if order_fail_at is not None:
        results.append(
            {
                "name": "time_order",
                "status": "FAIL",
                "detail": f"out of order at line {order_fail_at}",
            }
        )
    else:
        results.append(
            {"name": "time_order", "status": "PASS", "detail": order_detail}
        )

    # No full echo: identical normalized text on both speakers → WARN.
    by_speaker: dict[str, set[str]] = {"You": set(), "Them": set()}
    for seg in segments:
        by_speaker[seg["speaker"]].add(_normalize(seg["text"]))
    overlap = by_speaker["You"] & by_speaker["Them"]
    if overlap:
        sample = sorted(overlap)[0]
        results.append(
            {
                "name": "no_full_echo",
                "status": "WARN",
                "detail": "duplicated across speakers (possible echo): "
                f"{len(overlap)} shared text(s), e.g. {sample[:60]!r}",
            }
        )
    else:
        results.append(
            {
                "name": "no_full_echo",
                "status": "PASS",
                "detail": "no text shared across speakers",
            }
        )

    # Meta samples: only when meta provided (else SKIP with a note).
    if meta is None:
        results.append(
            {
                "name": "meta_samples",
                "status": "SKIP",
                "detail": "no --recording given or meta.json missing; skipped",
            }
        )
    else:
        for track in ("mic", "system"):
            samples = (meta.get(track) or {}).get("samples_written")
            if isinstance(samples, int) and samples > 0:
                results.append(
                    {
                        "name": "meta_samples",
                        "status": "PASS",
                        "detail": f"{track} track: {samples} samples written",
                    }
                )
            else:
                results.append(
                    {
                        "name": "meta_samples",
                        "status": "FAIL",
                        "detail": f"track silent: {track} (samples_written={samples!r})",
                    }
                )

    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Automated PASS/FAIL verdict for an attributed transcript."
    )
    parser.add_argument("transcript", help="path to the transcript .md file")
    parser.add_argument(
        "--recording",
        default=None,
        help="recording directory containing meta.json (optional; check skipped if absent)",
    )
    args = parser.parse_args(argv)

    transcript_path = Path(args.transcript)
    if not transcript_path.is_file():
        print(f"error: transcript file not found: {transcript_path}", file=sys.stderr)
        return 2

    segments = parse_transcript(transcript_path.read_text(encoding="utf-8"))

    meta: dict | None = None
    if args.recording is not None:
        meta_path = Path(args.recording) / "meta.json"
        if meta_path.is_file():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                print(f"error: cannot read {meta_path}: {exc}", file=sys.stderr)
                return 2
        else:
            print(f"note: {meta_path} not found; skipping meta check", file=sys.stderr)

    results = verify(segments, meta=meta)

    fails = 0
    for r in results:
        print(f"[{r['status']}] {r['name']}: {r['detail']}")
        if r["status"] == "FAIL":
            fails += 1

    if fails:
        print("OVERALL: FAIL")
        return 1
    print("OVERALL: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
