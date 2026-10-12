#!/usr/bin/env python3
"""spike/T4: transcribe mic.wav + system.wav (16 kHz mono s16le) with mlx-whisper.

Usage: transcribe.py <dir>

Reads <dir>/mic.wav and <dir>/system.wav, transcribes each locally with
mlx-community/whisper-large-v3-turbo (offline), and writes:
  <dir>/mic.segments.json
  <dir>/system.segments.json
  <dir>/transcript.md
  <dir>/transcribe_stats.json

No ffmpeg needed: WAVs are loaded with soundfile and the raw numpy float32
array is passed to mlx_whisper.transcribe.
"""

import argparse
import json
import os
import sys
import time

# Offline: model is already in the standard HF cache.
os.environ.setdefault("HF_HUB_OFFLINE", "1")

import numpy as np
import soundfile as sf

import mlx_whisper

MODEL = "mlx-community/whisper-large-v3-turbo"
EXPECTED_SR = 16000

SPEAKERS = {"mic": "You", "system": "Them"}

# Exact kwargs passed to mlx_whisper.transcribe (recorded in settings).
TRANSCRIBE_SETTINGS = {
    "language": "en",
    "word_timestamps": True,
    "condition_on_previous_text": False,
    "no_speech_threshold": 0.6,
    "hallucination_silence_threshold": 0.0,
}


def to_plain(x):
    """Convert numpy scalars/arrays to plain Python types (json-safe)."""
    if isinstance(x, dict):
        return {k: to_plain(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [to_plain(v) for v in x]
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (np.floating,)):
        return float(x)
    if isinstance(x, np.ndarray):
        return [to_plain(v) for v in x.tolist()]
    if isinstance(x, (str, int, float, bool, type(None))):
        return x
    return str(x)


def load_audio(path: str) -> np.ndarray:
    """Load a 16 kHz mono WAV as a numpy float32 array (no ffmpeg)."""
    audio, sr = sf.read(path, dtype="float32")
    assert sr == EXPECTED_SR, f"expected {EXPECTED_SR} Hz, got {sr} Hz"
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    return audio.astype(np.float32)


def transcribe_track(path: str, speaker: str, track_name: str) -> dict:
    """Transcribe one WAV; return the segments-JSON dict (json-safe)."""
    audio = load_audio(path)
    audio_seconds = round(float(len(audio) / EXPECTED_SR), 3)

    t0 = time.monotonic()
    try:
        r = mlx_whisper.transcribe(audio, path_or_hf_repo=MODEL, **TRANSCRIBE_SETTINGS)
    except Exception as e:  # HW/HF/model errors -> clear message
        print(f"ERROR: transcription failed for {path}: {type(e).__name__}: {e}",
              file=sys.stderr)
        sys.exit(1)
    wall = round(time.monotonic() - t0, 3)

    segments = []
    for seg in r.get("segments") or []:
        text = (seg.get("text") or "").strip()
        if not text:
            continue  # drop empty-text segments
        words = []
        for w in seg.get("words") or []:
            words.append({
                "word": to_plain(w.get("word", "")),
                "start": to_plain(w.get("start", 0.0)),
                "end": to_plain(w.get("end", 0.0)),
                "probability": to_plain(w.get("probability")),
            })
        segments.append({
            "start": to_plain(seg.get("start", 0.0)),
            "end": to_plain(seg.get("end", 0.0)),
            "text": text,
            "words": words,
        })

    return {
        "track": track_name,
        "speaker": speaker,
        "model": MODEL,
        "audio_seconds": audio_seconds,
        "wall_seconds": wall,
        "settings": dict(TRANSCRIBE_SETTINGS),
        "segments": segments,
    }


def fmt_mmss(start: float) -> str:
    return f"{int(start // 60):02d}:{int(start % 60):02d}"


def write_transcript_md(out_path: str, tracks: list[dict]) -> None:
    blocks = []
    for t in tracks:
        for seg in t["segments"]:
            blocks.append((seg["start"], t["speaker"], seg["text"]))
    blocks.sort(key=lambda b: b[0])

    lines = ["# Transcript", ""]
    prev_start = None
    for start, speaker, text in blocks:
        if prev_start is not None:
            lines.append("")  # blank line between consecutive blocks
        lines.append(f"**{speaker} ({fmt_mmss(start)}):** {text}")
        prev_start = start
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser(description="Transcribe mic.wav + system.wav with mlx-whisper (offline).")
    ap.add_argument("dir", help="Directory containing mic.wav and system.wav")
    args = ap.parse_args()

    d = args.dir
    if not os.path.isdir(d):
        print(f"ERROR: not a directory: {d}", file=sys.stderr)
        sys.exit(1)

    paths = {"mic": os.path.join(d, "mic.wav"), "system": os.path.join(d, "system.wav")}
    missing = [p for p in paths.values() if not os.path.isfile(p)]
    if missing:
        for p in missing:
            print(f"ERROR: missing input file: {p}", file=sys.stderr)
        sys.exit(1)

    results = {}
    total_wall = 0.0
    for track in ("mic", "system"):
        res = transcribe_track(paths[track], SPEAKERS[track], track)
        results[track] = res
        total_wall += res["wall_seconds"]
        print(f"[{track}] audio={res['audio_seconds']}s wall={res['wall_seconds']}s "
              f"segments={len(res['segments'])}")

        out_json = os.path.join(d, f"{track}.segments.json")
        with open(out_json, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=2)
            f.write("\n")

    write_transcript_md(os.path.join(d, "transcript.md"), [results["mic"], results["system"]])

    stats = {
        "mic": {"audio_seconds": results["mic"]["audio_seconds"], "wall_seconds": results["mic"]["wall_seconds"]},
        "system": {"audio_seconds": results["system"]["audio_seconds"], "wall_seconds": results["system"]["wall_seconds"]},
        "total_wall_seconds": round(total_wall, 3),
    }
    with open(os.path.join(d, "transcribe_stats.json"), "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print(f"[total] wall={round(total_wall, 3)}s")


if __name__ == "__main__":
    main()
