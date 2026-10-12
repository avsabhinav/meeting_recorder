# Permissions & Troubleshooting

Covers the two macOS permissions `mr` needs, what `mr doctor` does (and does
not) check, and answers to common problems.

## Required permissions

`mr-capture` records two streams, each gated by a separate macOS (TCC)
permission:

| Permission | What it records | Where it is granted |
| --- | --- | --- |
| **Microphone** | Your mic track (`mic.wav` → *You*) | System Settings ▸ Privacy & Security ▸ **Microphone** |
| **System audio capture** (macOS 14.2+, Core Audio process tap) | Your speakers' output (`system.wav` → *Them*) | System Settings ▸ Privacy & Security — the system-audio / Screen Recording entry for the capturing process |

### How the prompts appear

- Both TCC prompts surface **the first time a capture starts** (first
  `mr start` / `mr toggle` / `mr process` from a launcher). The helper is
  built with an embedded `Info.plist` (`NSMicrophoneUsageDescription`,
  `NSAudioCaptureUsageDescription`) and an adhoc code signature so the prompts
  show proper usage text.
- The permission may be attributed to `mr-capture` **or to the app that
  launched it** (Terminal, Shortcuts, Raycast). If you switch launchers, you
  may need to grant the permission again for the new one.
- **Denied permission → possibly-silent stream.** If you decline a prompt, the
  capture may still run, write a WAV, and look normal — but the track can be
  all silence. Verify with the "Confirm capture" section below.

### Granting / re-granting

1. Start a capture: `mr start`.
2. macOS shows the prompt(s) — choose **Allow**.
3. If a prompt never appeared (or was denied earlier):
   System Settings ▸ Privacy & Security → find the entry for `mr-capture`
   (or Terminal/Shortcuts) under **Microphone** and the system-audio entry →
   toggle it **On**.
4. Quit and relaunch the capture (`mr stop`, then `mr start`) — permission
   changes take effect on next launch.

### Confirming capture actually has audio

`mr doctor` does **not** check permissions. After a short test recording,
check the session folder (`~/Meetings/recordings/<stamp>/`):

- `meta.json` → `mic.samples_written` and `system.samples_written`: both should
  be large (thousands+ per second of recording). Near-zero ⇒ that track was
  silent (permission denied or wrong device).
- `mic.wav` / `system.wav` file sizes: silence produces near-empty WAVs.
- `mr status` shows the active session and `out_dir` while recording.

## What `mr doctor` does (honest scope)

`mr doctor` checks:

- **macOS version** (the system-audio tap needs macOS 14.2+),
- **helper binary** — `mr-capture` present at `MR_CAPTURE_BIN` or the default
  `capture/.build/release/mr-capture`; otherwise prints
  `helper: MISSING (build capture/ or set MR_CAPTURE_BIN)`,
- **model cache** — whether the configured mlx-whisper model is in the local
  Hugging Face cache.

It does **not** check: microphone / system-audio TCC permissions, network
connectivity (except via `--fetch-model`), or that your audio device is sane.
Use the WAV-size / `meta.json` check above to confirm real capture.

## Troubleshooting

### `helper: MISSING` / "install mr-capture (MR_CAPTURE_BIN) or build the Swift package"

The Swift helper isn't built where the CLI looks for it.

```sh
cd capture && ./build.sh       # or: bash capture/install.sh
mr doctor                      # should now show "helper: capture/.build/release/mr-capture"
```

Installed it elsewhere? `export MR_CAPTURE_BIN=/path/to/mr-capture`.

### Exit code 3: "model … is not in the local HF cache (offline mode)"

Transcription at call time is **cache-only** (offline). The model was never
downloaded. Fix:

```sh
mr doctor --fetch-model        # downloads it once (network); exit 1 on failure
mr stop                        # retry — the state was kept precisely so you can
```

`mr doctor --fetch-model` exits `1` with an error if the download itself
fails (network / Hugging Face issue); check connectivity and retry.

### No audio in `mic.wav` or `system.wav` (silence)

Most likely a **denied permission** (see above) — the stream runs but delivers
silence. Check `meta.json` `samples_written` for that track, then grant the
permission and restart the capture. Also make sure the intended input device
is selected in System Settings ▸ Sound during the call.

### Only one side (You *or* Them) appears in the transcript

Attribution is **stream-based**: whatever was in `mic.wav` becomes *You*,
whatever was in `system.wav` becomes *Them*. One side missing means that
track's audio was silent or absent:

- Check `meta.json`: the silent track's `samples_written` will be ~0.
- Check the matching permission (Microphone for `mic`, system-audio for
  `system`) — see the table above.
- Take the call on **speakers**, not a headset/earbuds — a headset routes the
  far side out of your speakers, so the system tap hears nothing.

### `mr stop` says "not recording" but I thought I was

- Run `mr status`. If it says `recording: no`, the state is genuinely clear —
  the helper may have already stopped/crashed.
- If it shows `stale pidfile; run \`mr stop\` to clear`: the helper process
  died but the state file (`~/Meetings/.state/recording.json`) was left
  behind. `mr stop` will transcribe the WAVs that exist and clear the state.
- Check `recordings/<stamp>/` for the WAVs before re-running `mr start`.

### Transcription feels slow

Both tracks are transcribed **sequentially** (mic, then system) on the local
MLX stack. Speed scales with audio length; silence is trimmed by VAD, so a
quiet call is faster than a wall-to-wall talk. This is expected — there is no
parallel/remote path by design (local-first).

### `mr start` says "already recording (stamp …)"

A session is already active (state file present and pid alive). Either `mr
stop` to finish it, or check `mr status` for where it's writing.

### Where do outputs go?

- Recordings: `~/Meetings/recordings/<stamp>/` (`mic.wav`, `system.wav`,
  `meta.json`)
- Transcripts: `~/Meetings/transcripts/<stamp>.md` (+ `.json` with `--json`)
- State: `~/Meetings/.state/recording.json`

Change the root with `out_root` in `~/.config/mr/config.toml`.
