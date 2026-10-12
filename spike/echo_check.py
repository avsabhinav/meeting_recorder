#!/usr/bin/env python3
"""Score text-overlap echo between "You" (mic) and "Them" (system) transcript segments.

Usage:
    echo_check.py <dir>

Reads <dir>/mic.segments.json (You) and <dir>/system.segments.json (Them), each with schema:
    {"segments": [{"start": 0.0, "end": 2.1, "text": "hello"}, ...]}

For each You segment that time-overlaps at least one Them segment (overlap > 0,
segments treated as [start, end) seconds), compute max_ratio = max of
rapidfuzz.fuzz.token_ratio(you_text, them_text) over those Them segments.
Report counts, echo flags at thresholds 0.5/0.6/0.7, example pairs, and a
distribution summary. stdout only.
"""

import json
import os
import sys

import numpy as np
from rapidfuzz import fuzz

THRESHOLDS = (0.5, 0.6, 0.7)


def load_segments(path: str) -> list:
    """Load segments from a segments JSON file; exit 1 with a clear error if missing."""
    if not os.path.isfile(path):
        print(f"ERROR: required file not found: {path}", file=sys.stderr)
        sys.exit(1)
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        data = {}
    segs = data.get("segments", [])
    if not isinstance(segs, list):
        segs = []
    return [s for s in segs if isinstance(s, dict)]


def overlap(a_start, a_end, b_start, b_end) -> bool:
    """True if half-open intervals [a_start,a_end) and [b_start,b_end) overlap by > 0."""
    try:
        a_start, a_end = float(a_start), float(a_end)
        b_start, b_end = float(b_start), float(b_end)
    except (TypeError, ValueError):
        return False
    return a_start < b_end and b_start < a_end


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: echo_check.py <dir>", file=sys.stderr)
        sys.exit(2)
    d = sys.argv[1]

    you = load_segments(os.path.join(d, "mic.segments.json"))
    them = load_segments(os.path.join(d, "system.segments.json"))

    # Pre-compute Them (start, end, text) for cheap comparison.
    them_list = [(float(s["start"]), float(s["end"]), str(s.get("text", "")).strip())
                 for s in them if "start" in s and "end" in s]

    ratios = []          # max_ratio per overlapping You segment
    pairs = []           # (you_start, you_text, them_text, ratio) for the argmax pair
    overlapping = 0
    non_overlapping = 0

    for s in you:
        if "start" not in s or "end" not in s:
            non_overlapping += 1
            continue
        y_start, y_end = float(s["start"]), float(s["end"])
        y_text = str(s.get("text", "")).strip()
        if not y_text:
            non_overlapping += 1
            continue

        best_ratio = -1.0
        best_them = None
        for t_start, t_end, t_text in them_list:
            if not t_text:
                continue
            if overlap(y_start, y_end, t_start, t_end):
                r = fuzz.token_ratio(y_text, t_text)
                if r > best_ratio:
                    best_ratio = r
                    best_them = t_text

        if best_ratio < 0:
            non_overlapping += 1
            continue
        overlapping += 1
        ratios.append(best_ratio)
        pairs.append((y_start, y_text, best_them, best_ratio))

    print("=== Echo check: text-overlap between You (mic) and Them (system) ===")
    print()
    print("Counts:")
    print(f"  total You segments:      {len(you)}")
    print(f"  total Them segments:     {len(them)}")
    print(f"  You overlapping >=1:     {overlapping}")
    print(f"  You overlapping none:    {non_overlapping}")
    print()

    ratios_arr = np.asarray(ratios, dtype=float) if ratios else np.asarray([])
    print("Likely-echo You segments (max_ratio >= threshold):")
    for th in THRESHOLDS:
        n = int((ratios_arr >= th * 100).sum()) if ratios else 0
        print(f"  threshold {th}: {n}")
    print()

    # Example pairs above the 0.5 threshold, highest ratio first.
    above = [p for p in pairs if p[3] >= 50.0]
    above.sort(key=lambda p: p[3], reverse=True)
    examples = above[:10]
    if examples:
        print(f"Example pairs above 0.5 (top {len(examples)}):")
        for y_start, y_text, t_text, r in examples:
            yt = y_text if len(y_text) <= 60 else y_text[:57] + "..."
            tt = t_text if len(t_text) <= 60 else t_text[:57] + "..."
            print(f"  ({y_start:.1f}s) {yt!r} | {tt!r}  -> {r}")
    else:
        print("Example pairs above 0.5: (none)")
    print()

    if ratios:
        mean = float(ratios_arr.mean())
        p90 = float(np.percentile(ratios_arr, 90))
        exact100 = int((ratios_arr == 100).sum())
        print("max_ratio distribution (overlapping You segments):")
        print(f"  mean:            {mean:.1f}")
        print(f"  90th percentile: {p90:.1f}")
        print(f"  max_ratio == 100 exactly: {exact100}")
        print()

        # Heuristic: pick the smallest standard threshold that keeps the fraction
        # of flagged You lines low relative to the observed spread; if even 0.5
        # flags a large share, suggest a higher bar.
        frac5 = float((ratios_arr >= 50).sum()) / len(ratios)
        frac6 = float((ratios_arr >= 60).sum()) / len(ratios)
        frac7 = float((ratios_arr >= 70).sum()) / len(ratios)
        if frac7 <= 0.25:
            best, frac = 0.7, frac7
        elif frac6 <= 0.25:
            best, frac = 0.6, frac6
        else:
            best, frac = 0.5, frac5
        print(
            f"Heuristic suggestion: use threshold {best} "
            f"(flags {frac:.0%} of overlapping You segments at this bar, "
            f"vs 0.5/0.6/0.7 = {frac5:.0%}/{frac6:.0%}/{frac7:.0%}); "
            f"raise it if non-echo lines are still being dropped."
        )
    else:
        print("max_ratio distribution: (no overlapping You segments)")


if __name__ == "__main__":
    main()
