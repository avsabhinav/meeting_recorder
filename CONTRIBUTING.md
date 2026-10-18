# Contributing

Welcome! Oatmeal is a local-first macOS tool: record a 1:1 call (mic + system audio) and transcribe it locally into an attributed Markdown transcript. Contributions are welcome.

## Prerequisites

- macOS 14.2+ (the system-audio capture uses a Core Audio process tap)
- Apple Silicon (transcription runs on Apple's MLX framework)
- Python 3.12+
- Xcode Command Line Tools (`swift`) for building the Swift helpers
- Full Xcode is only needed if you want to run the menu-bar XCTest suite (`swift test`)

## Setup

```sh
# Development install (editable, includes pytest + ruff)
pip install -e ".[dev]"

# Sanity-check the environment
mr doctor

# Build both Swift helpers
cd capture && ./build.sh
cd menu-bar && ./build.sh
```

`mr doctor` reports the macOS version, whether the `mr-capture` helper is found, and whether the Whisper model is cached (`mr doctor --fetch-model` downloads it).

To build the distributable DMG, run `packaging/make_dmg.sh` (produces `dist/MeetingRecorder-<version>.dmg`). End-user install instructions: [docs/installing.md](docs/installing.md).

## Checking your work before you push

Run all of these locally — CI runs the same steps:

```sh
ruff check mr tests
pytest
cd capture && ./build.sh
cd menu-bar && ./build.sh

# Optional — requires full Xcode (Command Line Tools alone may not suffice):
cd menu-bar && swift test --disable-sandbox
```

## How the repo is organized

- `mr/` — Python package: `mr` CLI and core (capture, transcribe, merge, output)
- `capture/` — SwiftPM package that builds the `mr-capture` recording helper
- `menu-bar/` — SwiftPM AppKit app that builds the `Oatmeal` menu-bar app
- `tests/` — pytest suite for the Python core (transcriber mocked)
- `examples/` — sample aligned WAVs and a generated transcript
- `docs/` — architecture notes, permissions & troubleshooting, manual-test results

The Phase 0 spike was archived out of the repo; for design decisions, read [docs/architecture.md](docs/architecture.md).

## Submitting changes

1. Branch off `main` (e.g. `git switch -c fix/...` or `feature/...`).
2. Open a pull request against `main`.
3. CI must pass before a PR can be merged.

The GitHub Actions workflow (`.github/workflows/ci.yml`) runs on an Apple Silicon macOS 15 runner on every push to `main` and on every PR: it installs the dev dependencies, runs `ruff check mr tests` and `pytest`, builds `mr-capture` and `Oatmeal`, and runs the menu-bar XCTest suite.

Please keep PRs small and focused — one fix or one feature per PR makes review much easier.

## Reporting bugs

Open an issue on GitHub with:

- macOS version and chip
- What you ran (e.g. `mr toggle`, `mr process --mic ... --system ...`) and its output
- What you expected to happen
- `mr status` / `mr doctor` output if relevant

Do not attach recordings or transcripts — those stay on your machine (see [SECURITY.md](SECURITY.md)).
