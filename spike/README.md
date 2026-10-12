# mr-capture — Phase 0 spike (capture)

Prove that on Apple Silicon macOS we can capture system audio (Core Audio
process tap) + mic (with AEC) into two aligned 16 kHz mono WAVs, and
transcribe locally with mlx-whisper. See `../PHASE0_SPIKE.md`, `../PLAN.md` §7.

## Build & run

```sh
cd capture
CLANG_MODULE_CACHE_PATH="$TMPDIR/mcache" swift build --disable-sandbox   # debug, inside DSH sandbox
# or: ./build.sh   # release build with embedded Info.plist + adhoc codesign
```

Run (binary at `capture/.build/debug/mr-capture` or `.build/release/mr-capture`):

```sh
mkdir -p out
./capture/.build/debug/mr-capture --out out          # mic.wav + system.wav (+ meta.json)
./capture/.build/debug/mr-capture --out out --no-aec # AEC off comparison
# Ctrl-C to stop; two WAVs + meta.json are finalized.
```

## Transcribe + metrics

```sh
spike/.venv/bin/python transcribe.py out        # both tracks -> segments JSON + transcript.md
spike/.venv/bin/python align_check.py out       # offset / drift between mic and system
spike/.venv/bin/python echo_check.py out        # echo scoring between You/Them segments
```

## CLI contract

`mr-capture --out <dir> [--no-aec]` — records until SIGINT/SIGTERM, then
finalizes `mic.wav`, `system.wav` (16 kHz mono 16-bit PCM) and `meta.json`.

## Notes / gotchas
- Inside the DSH sandbox, SwiftPM needs `--disable-sandbox` and a temp
  module-cache path; building outside the sandbox doesn't need them.
- No `ffmpeg` on this machine: mlx-whisper is fed numpy float32 arrays loaded
  by `soundfile`, never a file path.
- Model is cached at `~/.cache/huggingface/hub/models--mlx-community--whisper-large-v3-turbo`;
  `transcribe.py` runs with `HF_HUB_OFFLINE=1`.