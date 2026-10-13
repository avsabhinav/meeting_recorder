# meeting-recorder

A local-first macOS tool that records a 1:1 call (your mic **and** the other
side via system audio) and transcribes it **locally** into an **attributed
Markdown transcript** — every line marked as *You* or *Them* — ready for you or
other AI agents to consume.

No cloud, no LLM: capture → local Whisper transcription → attributed Markdown.
Everything (recording, transcription, output) stays on your Mac.

## How it works

1. `mr toggle` (or `mr start`) spawns a small Swift helper, `mr-capture`,
   which records two 16 kHz mono streams at the same time:
   - **mic** — your microphone, recorded **raw** (no voice processing) so
     recording never lowers call volume or ducks the remote participant →
     attributed **You**
   - **system** — your speakers, tapped through a Core Audio process tap
     (macOS 14.2+) → attributed **Them**
   The helper writes `mic.wav` and `system.wav` into a per-session folder.
2. `mr toggle` (or `mr stop`) signals the helper to stop, waits for the WAVs,
   transcribes **both tracks locally** with [mlx-whisper]
   (`mlx-community/whisper-large-v3-turbo` on Apple Silicon), interleaves the
   two streams by timestamp, and runs an always-on **text-overlap dedup**
   (rapidfuzz token similarity ≥ threshold) so words both sides "heard" via the
   other's speakers are not duplicated.
3. The result is written to `~/Meetings/transcripts/<stamp>.md`, and a macOS
   notification is posted when the transcript is ready.

Attribution is **stream-based and deterministic**: mic → `You`, system →
`Them`. No speech-identification model, no guessing.

## Requirements

- macOS 14.2 or later (the system-audio tap uses a Core Audio process tap)
- Apple Silicon (transcription runs on Apple's MLX framework)
- Python 3.12+
- Xcode Command Line Tools (`swift`), for building the capture helper

## Quick start

```sh
cd "meeting recorder"          # or wherever you cloned the repo

# 1. Install the Python package (editable, with dev tools)
pip install -e ".[dev]"

# 2. Build + install the mr-capture helper (Swift release build, adhoc-signed)
bash capture/install.sh        # or: cd capture && ./build.sh

# 3. Sanity-check the environment
mr doctor

# 4. Pre-download the Whisper model (once; needs network)
mr doctor --fetch-model
```

`mr doctor` prints the macOS version, the location (or absence) of the
`mr-capture` helper, and whether the model is in the local Hugging Face cache.

If you install `mr-capture` somewhere else (e.g. `/usr/local/bin`), point the
CLI at it with:

```sh
export MR_CAPTURE_BIN=/usr/local/bin/mr-capture
```

(Otherwise the CLI looks for `capture/.build/release/mr-capture` inside the
repo.)

Then record a call:

```sh
mr toggle        # start recording
# ... take the call on your speakers ...
mr toggle        # stop → transcribes → writes ~/Meetings/transcripts/<stamp>.md
```

You'll get a macOS notification when the transcript is written.

## CLI reference

The entry point is `mr` (installed by `pip install -e .`).

| Command | Purpose |
| --- | --- |
| `mr toggle` | **Primary action.** Start recording if idle, else stop + transcribe. Ideal for a hotkey. |
| `mr start` | Start recording. |
| `mr stop` | Stop recording, transcribe, write the transcript. |
| `mr status` | Show whether a capture is active (pid, output dir, stamp) and the last transcript. |
| `mr process` | Transcribe an existing `--mic`/`--system` WAV pair (no capture needed). |
| `mr doctor` | Check the environment (macOS version, helper binary, model cache). |

### `mr toggle`

```
mr toggle [--json]
```

- `--json` — also write a JSON sidecar when *stopping*.

### `mr start`

```
mr start
```

Spawns `mr-capture` (it keeps running after `mr start` exits) and records the
state. If a capture is already active it prints
`already recording (stamp …)` and exits 0.

### `mr stop`

```
mr stop [--json]
```

Sends SIGINT to the capture helper, waits (up to ~15 s) for the WAVs and
`meta.json` to be flushed, transcribes both tracks, writes
`transcripts/<stamp>.md`, then clears the state. Prints `not recording` if
there is no active session.

### `mr status`

Shows `recording: yes/no`, and when active: `pid`, `out_dir`, `stamp`,
`started_at` — plus a `stale pidfile` warning if the helper died. Also prints
the path of the most recent transcript.

### `mr process`

Transcribe an existing WAV pair (handy for re-processing or testing):

```
mr process --mic <wav> --system <wav>
          [--model <hf-repo-id>] [--language <code>]
          [--dedup-threshold <0.0-1.0>] [--json]
          [--stamp <label>] [--out-dir <dir>]
```

- `--mic` — you-side 16 kHz mono WAV (required)
- `--system` — them-side 16 kHz mono WAV (required)
- `--model` — Hugging Face repo id (default: `mlx-community/whisper-large-v3-turbo`)
- `--language` — forced language code (default: `en`)
- `--dedup-threshold` — echo-dedup similarity threshold, 0–1 (default: `0.6`)
- `--json` — also write `<stamp>.json`
- `--stamp` — label for the transcript file (default: the system WAV's stem)
- `--out-dir` — output directory (default: the system WAV's directory)

Writes `<stamp>.md` (and `<stamp>.json` with `--json`) into the output dir.

### `mr doctor`

```
mr doctor [--fetch-model]
```

Prints the macOS version, `out_root`, the helper binary path (or
`helper: MISSING (build capture/ or set MR_CAPTURE_BIN)`), the configured
model, and whether it is cached. With `--fetch-model`, downloads the model
into the standard Hugging Face cache if it is not already present.

> Note: `mr doctor` does **not** check microphone / system-audio permissions —
> see [docs/permissions-troubleshooting.md](docs/permissions-troubleshooting.md).

### Exit codes

| Code | Meaning |
| --- | --- |
| `0` | Success (including `mr stop` with nothing to stop, and `mr start` when already recording). |
| `1` | `mr doctor --fetch-model` failed to download the model (network/HF error). |
| `2` | Usage / parameter error (e.g. `--mic` file not found, bad `--dedup-threshold`). |
| `3` | Model not cached (offline cache-only transcription). Fix: `mr doctor --fetch-model`, then re-run `mr stop` (state is intentionally kept so you can retry). |

## Configuration

Config file: `~/.config/mr/config.toml` (optional — defaults are used when the
file or individual keys are absent). See [config.toml.example](config.toml.example):

```sh
mkdir -p ~/.config/mr && cp config.toml.example ~/.config/mr/config.toml
```

| Key | Default | Meaning |
| --- | --- | --- |
| `out_root` | `~/Meetings` | Root directory holding `recordings/` and `transcripts/`. |
| `model` | `mlx-community/whisper-large-v3-turbo` | mlx-whisper model (HF repo id or local path). |
| `language` | `en` | Forced transcription language (ISO code). |
| `dedup_threshold` | `0.6` | Echo-dedup similarity threshold (0–1) when merging the two streams. |
| `keep_audio` | `true` | Keep the raw WAV files after transcription (re-processable). |

Recording state lives in `<out_root>/.state/recording.json` (pid, out_dir,
stamp, start time).

## Hotkey: bind `mr toggle`

The intended workflow is: press a hotkey before a call, press it again after.

### macOS Shortcuts (recommended)

1. Open **Shortcuts** → New Shortcut.
2. Add a **Run Shell Script** action with the script `mr toggle`.
3. Bind the shortcut to a global hotkey (e.g. **⌥⌘R**):
   **System Settings ▸ Keyboard ▸ Keyboard Shortcuts ▸ Shortcuts** → set your
   shortcut. (Or use the shortcut's own "Keyboard Shortcut" setting in the
   Shortcuts editor.)

> Tip: make sure `mr` is on the `PATH` that Shortcuts uses; if you installed
> with a venv, use the full path (e.g. `~/.venvs/mr/bin/mr toggle`).

### Raycast (Script Command)

Add a Script Command with:

- Command: `mr toggle`
- Input: none (stdout = output)
- Then assign a hotkey (e.g. **⌥⌘R**) to the command.

## Menu-bar app (beta)

`mrBar` is an optional menu-bar app (no Dock icon — `LSUIElement`) that drives the
same `mr` CLI: **Start Recording**, **Stop Recording & Transcribe** (with a live
**Transcribing:** list), **Change Storage Location…**, **Open Folder ▸ Recordings /
Transcripts**, and **Quit**. It is a pure shell around `mr` — it never spawns
`mr-capture` or writes config/state itself, and it only refreshes when you open the
menu (no polling).

- **Build + install:** `cd menu-bar && ./install.sh` →
  `menu-bar/.build/Release/mrBar.app` (drag into `/Applications` or launch in place).
- **Make `mr` reachable:** either put it on `PATH` (`pip install -e .`), or launch the
  app with `MR_PYTHON=<venv>/bin/python` set (the app resolves `mr` from `PATH` first,
  then `MR_PYTHON`).
- **Manual test + permissions:** see
  [docs/menu-bar-manual-test.md](docs/menu-bar-manual-test.md) — the app is the
  responsible process for the Microphone / System Audio TCC prompts.

## Permissions

`mr-capture` needs **two** permissions, both granted the first time a capture
starts (TCC prompt; the binary embeds usage descriptions and is adhoc-signed):

- **Microphone** — records your mic stream (You).
- **System Audio Recording** (macOS 14.2+) — records the speaker audio
  (Them).

Grant them under **System Settings ▸ Privacy & Security** — enable the entry
for the capturing process under **Microphone**, and the corresponding system
audio / Screen Recording entry for the system-audio capture. The entry may
show the `mr-capture` helper or the app that launched it (Terminal /
Shortcuts). **If a permission is denied, the recording may still appear to
work but the track can be silent** — see
[docs/permissions-troubleshooting.md](docs/permissions-troubleshooting.md)
for how to verify your capture actually has audio.

## Output layout

```
~/Meetings/                          # out_root
├── .state/recording.json            # active-session state (pid, out_dir, stamp)
├── recordings/<stamp>/              # <stamp> = YYYY-MM-DD_HHMM
│   ├── mic.wav                      # You track (16 kHz mono)
│   ├── system.wav                   # Them track (16 kHz mono)
│   └── meta.json                    # capture metadata (device, samples_written, …)
└── transcripts/
    ├── <stamp>.md                   # attributed transcript (You / Them)
    └── <stamp>.json                 # optional, with --json
```

## Transcription notes

- **Local & offline at call time**: transcription uses the local Hugging Face
  cache only (`HF_HUB_OFFLINE=1`). If the model isn't cached you get a clear
  error and exit code 3 — run `mr doctor --fetch-model` (network) once.
- **Model**: `mlx-community/whisper-large-v3-turbo` (fast on Apple Silicon).
- **Both tracks are transcribed sequentially** (mic, then system); expect it to
  scale with call length.
- **Echo handling**: there is **no capture-time AEC** — the live call is
  untouched — so the merge step's text-overlap dedup (rapidfuzz token
  similarity ≥ `dedup_threshold`) is what removes echo.
- **Attribution is deterministic** (stream origin), not speaker-ID.

## Project layout

```
mr/            # Python package: cli, config, state, core/ (capture, transcribe, merge, output)
capture/       # SwiftPM package → mr-capture helper (build.sh, install.sh, Info.plist)
tests/         # core unit tests (transcriber mocked)
examples/      # sample aligned WAVs + generated transcript
docs/          # architecture, permissions & troubleshooting, test results
spike/         # Phase 0 spike (findings, investigation notes)
config.toml.example
pyproject.toml # `mr` entry point, deps (mlx-whisper, typer, soundfile, rapidfuzz)
```

## Developing

```sh
pip install -e ".[dev]"
ruff check mr tests
pytest
```

Rebuild the capture helper after Swift changes: `cd capture && ./build.sh`.

## License

See [LICENSE](LICENSE).

[mlx-whisper]: https://github.com/ml-explore/mlx-whisper
