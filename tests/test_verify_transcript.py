"""Light offline tests for ``examples/manual/verify_transcript.py``.

Imports the standalone example module by path (it is not an installed package)
and exercises ``parse_transcript`` / ``verify`` with in-memory strings.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MODULE_PATH = REPO_ROOT / "examples" / "manual" / "verify_transcript.py"

_spec = importlib.util.spec_from_file_location("verify_transcript", MODULE_PATH)
assert _spec is not None and _spec.loader is not None
vt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vt)

parse_transcript = vt.parse_transcript
verify = vt.verify

WELL_FORMED = """# Meeting — sample

- **Participants:** You (mic), Them (system)

## Transcript

**You (00:00):** hello there

**Them (00:05):** hi, how are you

**You (01:07):** this is a longer line
"""

MISSING_THEM = """## Transcript

**You (00:00):** solo line

**You (00:10):** another solo line
"""

OUT_OF_ORDER = """## Transcript

**You (00:00):** first

**Them (00:30):** later

**You (00:10):** back in time
"""


def _status(results, name):
    return [r["status"] for r in results if r["name"] == name]


def test_parse_transcript_segments():
    segs = parse_transcript(WELL_FORMED)
    assert len(segs) == 3
    assert [s["speaker"] for s in segs] == ["You", "Them", "You"]
    assert [s["seconds"] for s in segs] == [0, 5, 67]
    assert segs[0]["text"] == "hello there"
    assert [s["lineno"] for s in segs] == [7, 9, 11]


def test_verify_well_formed_passes():
    results = verify(parse_transcript(WELL_FORMED))
    assert "FAIL" not in [r["status"] for r in results]
    assert _status(results, "both_speakers") == ["PASS"]
    assert _status(results, "time_order") == ["PASS"]
    assert _status(results, "no_full_echo") == ["PASS"]
    assert _status(results, "meta_samples") == ["SKIP"]


def test_verify_missing_speaker_fails():
    results = verify(parse_transcript(MISSING_THEM))
    assert _status(results, "both_speakers") == ["FAIL"]


def test_verify_out_of_order_fails():
    results = verify(parse_transcript(OUT_OF_ORDER))
    order = [r for r in results if r["name"] == "time_order"]
    assert order[0]["status"] == "FAIL"
    assert "out of order at line" in order[0]["detail"]


def test_verify_empty_fails():
    results = verify(parse_transcript("## Transcript\n"))
    assert any(r["status"] == "FAIL" and "no segments parsed" in r["detail"] for r in results)


def test_verify_echo_is_warn_not_fail():
    text = (
        "## Transcript\n\n"
        "**You (00:00):** duplicate line\n\n"
        "**Them (00:05):** duplicate line\n"
    )
    results = verify(parse_transcript(text))
    assert "FAIL" not in [r["status"] for r in results]
    assert _status(results, "no_full_echo") == ["WARN"]


def test_verify_meta_samples():
    segs = parse_transcript(WELL_FORMED)
    good = verify(segs, meta={"mic": {"samples_written": 1000, "device_name": "m"},
                              "system": {"samples_written": 2000, "device_name": "s"}})
    assert _status(good, "meta_samples") == ["PASS", "PASS"]

    bad = verify(segs, meta={"mic": {"samples_written": 0}, "system": {"samples_written": 2000}})
    assert _status(bad, "meta_samples") == ["FAIL", "PASS"]
