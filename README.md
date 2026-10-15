# meeting-recorder

A tiny, private macOS tool that records a 1:1 call — your voice and the other
side's voice — and transcribes it **entirely on your Mac** into a **plain
Markdown file** where every line is labeled `You` or `Them`. No cloud, no
account, no bloat.

It's made for people who keep their own context: if you run a personal agent
and have an Obsidian vault (or any local second brain), this hands your agent
a clean transcript and lets **it** do the thinking — not a built-in
summarizer that only saw the meeting.

No cloud, no LLM on your behalf: capture → local transcription → a `.md` file
that stays on your Mac. That's the whole product.

---

## Why this exists (and why you might want it)

I built this to solve my own small problem, and I'm sharing it in case it
helps someone else.

I was tired of meeting-summary apps — Granola, OpenWhispr, Meetily, and the
rest. They're packed with features I never asked for, and the summaries they
spit out always felt off. Here's why: a summary is only as good as the context
behind it, and those tools only see the meeting. The person who actually has
context is **you** — your notes, your memory, your Obsidian vault, your
personal agent.

So I stopped asking a summarizer to think for me, and started asking **my own
agent** to do the thinking.

**What this tool does is deliberately small.** It records a one-on-one call
(your mic plus the other side's voice), transcribes it **on your Mac**, and
drops a clean Markdown file into a folder. Every line is labeled `You` or
`Them`, so your agent can clearly read who said what.

That's it. No built-in summaries, no fancy UI, no cloud, no account. The
summary is your personal agent's job — because that's where the real context
lives.

**The workflow is two keypresses:**

1. Tap your hotkey before the call → it starts recording.
2. Tap it again after → it stops, transcribes in the background, and writes a
   `.md` file to `~/Meetings/transcripts/`.

Then your personal agent picks up that Markdown file, runs it against your
memory and your vault's context, and turns it into something genuinely useful
to *you* — not a generic summary.

It keeps three promises the big tools can't:

- **Private by default.** Nothing leaves your machine. Recording, transcription,
  and the transcript are all local.
- **Your format.** Plain Markdown files. Drop them straight into your Obsidian
  vault or point your agent at the folder. No lock-in, no proprietary export.
- **Built for your workflow.** The output is a raw conversation your own agent
  can sort through with the context only you (and it) have.

If your setup sounds like this — personal agents, an Obsidian second brain, and
a preference for local, no-bloat software — this recorder is for you.

## The 30-second mental model

| You do | What happens |
| --- | --- |
| Tap your hotkey | It records your voice + the other side's voice. Private, on your Mac. |
| Tap it again | It stops, transcribes both sides **locally**, and writes a Markdown file. |
| Your agent reads it | It uses the `.md` transcript with *its* context to give you real insight. |

The tool handles the boring part — getting a faithful, clearly-attributed
transcript. **You** decide what it means.

## Getting started in three steps

Setup is a one-time thing (a little terminal, but only once — after that it's
just two keypresses).

```sh
# 1. Install + build (one time; needs command line tools)
pip install -e ".[dev]"
bash capture/install.sh

# 2. Check the setup, then fetch the transcription model (needs network, once)
mr doctor
mr doctor --fetch-model
```

Then record **any** call:

```sh
mr toggle   # start recording — take the call on your speakers
mr toggle   # stop — transcribes locally in the background, writes transcripts/<stamp>.md
```

You'll get a macOS notification when the transcript is ready. Point your agent
at `~/Meetings/transcripts/` (or your Obsidian vault) and let it do the rest.

Prefer a button over the terminal? There's an optional menu-bar app
(`mrBar`), and a step-by-step guide to binding `mr toggle` to a hotkey further
down (`## Hotkey`). The full, detailed setup instructions are in the
[Quick start](#quick-start) section.

---

## How it works

1. `mr toggle` (or `mr start`) spawns a small Swift helper, `mr-capture`,
   which records two 16 kHz mono streams at the same time:
   - **mic** — your microphone, recorded **raw** (no voice processing) so
     recording never lowers call volume or ducks the remote participant →
     attributed **You**
   - **system** — your speakers, tapped through a Core Audio process tap
     (macOS 14.2+) → attributed **Them**
   The helper writes `mic.wav` and `system.wav` into a per-session folder.
2. `mr toggle` (or `mr stop`) signals the helper to stop; once the WAVs flush
   (~seconds) transcription runs automatically **in the background** (a detached
   process): **both tracks locally** with [mlx-whisper]
   (`mlx-community/whisper-large-v3-turbo` on Apple Silicon), interleaving the
   two streams by timestamp, and running an always-on **text-overlap dedup**
   (rapidfuzz token similarity ≥ threshold) so words both sides "heard" via the
   other's speakers are not duplicated.
3. The result is written to `~/Meetings/transcripts/<stamp>.md`, and a macOS
   notification is posted when the transcript is ready. `mr stop` returns
   immediately, so you can start a new recording right away (back-to-back
   meetings); long transcriptions just take longer in the background.

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
mr toggle        # stop → returns immediately; transcribes in the background → writes transcripts/<stamp>.md
```

You'll get a macOS notification when the transcript is written.

## CLI reference

The entry point is `mr` (installed by `pip install -e .`).

| Command | Purpose |
| --- | --- |
| `mr toggle` | **Primary action.** Start recording if idle, else stop (transcribe in background). Ideal for a hotkey. |
| `mr start` | Start recording. |
| `mr stop` | Stop recording; transcribe in the background. |
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
`meta.json` to flush, clears the recording state, and **returns immediately**.
Transcription continues in a detached background process, which writes
`transcripts/<stamp>.md` and posts a macOS notification when done. You can
start a new recording right away even if the previous transcription is still
running. Prints `not recording` if there is no active session.

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
same `mr` CLI: **Start Recording**, **Stop Recording & Transcribe**, **Check
Active Transcriptions…**, **Change Storage Location…**, **Open Folder ▸ Recordings /
Transcripts**, and **Quit**. Stop returns immediately; transcription continues in
the background and is surfaced via **Check Active Transcriptions…** and a
completion notification. It is a pure shell around `mr` — it never spawns
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

## Continuous integration

A GitHub Actions workflow (`.github/workflows/ci.yml`) runs on every push to `main`
and on every pull request. It executes on an Apple Silicon macOS 15 runner and:

1. Installs the Python package (`pip install -e ".[dev]"`)
2. Lints and tests the Python core — `ruff check mr tests` and `pytest`
3. Builds both Swift helpers — `capture/build.sh` (`mr-capture`) and
   `menu-bar/build.sh` (`mrBar`), then runs the menu-bar XCTest suite with
   `swift test`

Once the repo is pushed to GitHub, the check will run automatically there; a CI
status badge can be added to the README after the repository has a final
<owner>/<repo> URL.

## License

See [LICENSE](LICENSE).

[mlx-whisper]: https://github.com/ml-explore/mlx-whisper
