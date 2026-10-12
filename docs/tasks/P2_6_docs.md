TASK: P2.6 Write README + hotkey + permissions + troubleshooting docs

GOAL: Replace the README stub with a complete, accurate, user-facing README for the shipped
`mr` tool, plus a dedicated permissions/troubleshooting doc. It must document how to install &
build, every CLI command (`process`, `start`, `stop`, `toggle`, `status`, `doctor`), the config
file, the hotkey (macOS Shortcuts / Raycast binding `mr toggle`), the required permissions, and
troubleshooting. This is documentation only — do NOT change any code.

CONTEXT:
- Repo: `meeting recorder/` (space in path — quote paths).
- The tool is real and works (verified end-to-end). Read the code/docs to write accurate docs:
  - `README.md` (stub — replace with full content).
  - `mr/cli.py` — exact commands + options: `process --mic/--system [--model --language --dedup-threshold --json --stamp --out-dir]`, `start [--aec/--no-aec]`, `status`, `stop [--json]`, `toggle [--aec/--no-aec --json]`, `doctor [--fetch-model]`. Exit codes: 0 success, 2 usage/param, 3 model-not-cached, 1 `doctor --fetch-model` download failure.
  - `mr/config.py` — config file `~/.config/mr/config.toml`, keys `out_root`, `model`, `language`, `dedup_threshold`, `keep_audio`; defaults; the repo `config.toml.example`.
  - `mr/core/*` — the pipeline (capture, transcribe, merge echo dedup, output .md/JSON).
  - `capture/build.sh` and `capture/install.sh` — how to build the Swift helper.
  - `docs/architecture.md` and `PLAN.md` — the locked design (attribution stream-based: mic→You, system→Them; echo dedup; local model cache).
  - `PLAN.md` §9 / `docs/checkpoint.md` for the suggested hotkey (`⌥⌘R`).
- The product: `mr toggle` (bound to a hotkey) starts/stops recording; stop→auto-transcribe→attributed `.md` under `~/Meetings/transcripts/` + mac notification (P2.5 osascript). Recording WAVs under `~/Meetings/recordings/<stamp>/`.
- Permissions that matter (from spike findings, `docs/manual-test-result.md`): microphone (mic capture via AVAudioEngine/VPIO) and System Audio Recording (system tap via Core Audio process tap, macOS 14.2+). Both TCC prompts surface when `mr-capture` first starts. `mr doctor` reports helper + model-cache status (not permissions directly — be honest about that).

FILES (create/modify only):
- `README.md` (REWRITE — full content)
- `docs/permissions-troubleshooting.md` (CREATE — new, dedicated)

READ FIRST:
1. `mr/cli.py` (full) — exact command signatures/options/exit codes.
2. `mr/config.py` — config keys/defaults.
3. `capture/build.sh`, `capture/install.sh`, `capture/Info.plist` — build/install + permission strings.
4. `config.toml.example` — the sample config.
5. `docs/architecture.md`, `PLAN.md`, `docs/checkpoint.md` — design decisions, hotkey suggestion.
6. `README.md` — current stub.

STEPS:
1. Rewrite `README.md` with these sections (accurate to the code):
   - Title + one-paragraph pitch (local-first, You/Them attributed Markdown, no cloud) + a short "How it works" (record mic+system → transcribe → merge → `.md` + notification).
   - **Requirements**: macOS 14.2+, Apple Silicon, Python 3.12+.
   - **Quick start**: install Python deps (`pip install -e ".[dev]"`), build the helper (`capture/build.sh` or `bash capture/install.sh` — mention both, and `MR_CAPTURE_BIN` override), run `mr doctor` to check the environment, `mr doctor --fetch-model` to pre-download the model.
   - **CLI reference**: a table or list of every subcommand with its options and exit codes (match `mr/cli.py` exactly). Include `mr toggle` as the primary "record a call" action.
   - **Config**: path, all 5 keys + defaults, point to `config.toml.example`.
   - **Hotkey**: bind `mr toggle` via macOS **Shortcuts** (a "Run Shell Script" shortcut calling `mr toggle`, assigned a keyboard shortcut) or **Raycast** (Script Command); example suggested key `⌥⌘R`. Give concrete Shortcuts steps.
   - **Permissions**: list microphone + System Audio Recording; note both are macOS TCC prompts surfaced when recording first starts; direct the reader to `docs/permissions-troubleshooting.md`.
   - **Output layout**: `~/Meetings/recordings/<stamp>/` (mic.wav, system.wav, meta.json) + `~/Meetings/transcripts/<stamp>.md` (+ `.json` with `--json`).
   - **How transcription works** (1-2 paragraphs): local mlx-whisper `large-v3-turbo`, standard HF cache, offline cache-only at call time, `ModelNotCachedError` → `mr doctor --fetch-model`; echo handling (AEC + text-overlap dedup).
   - **Project layout** (brief) + **Developing** (lint/test): `ruff check mr tests`, `pytest`.
   - Keep the whole README concise but complete (~150-250 lines). Use real, copy-pasteable commands with the `meeting recorder` path in quotes where a path with a space matters.
2. Create `docs/permissions-troubleshooting.md`:
   - **Permissions**: what each records; how to grant/check in System Settings ▸ Privacy & Security (Microphone; Screen & System Audio in newer macOS); that the mic-permission prompt and System Audio Recording prompt appear on first `mr-capture` start; and that if denied the stream may run but deliver silence (from spike findings in `docs/manual-test-result.md`).
   - **`mr doctor`**: what it checks (macOS version, helper binary, model cache) and honest note that it does NOT verify TCC permissions — how to confirm a recording actually captured audio (check `~/.cache`/out dir WAV sizes, `meta.json` `samples_written`).
   - **Troubleshooting Q&A**:
     - Helper missing → build it or set `MR_CAPTURE_BIN`.
     - "model not cached" / exit 3 → `mr doctor --fetch-model`.
     - No audio in `mic.wav`/`system.wav` (mic denied / system tap denied / silent) → check permissions, `meta.json`, output file sizes.
     - One side missing (only You or only Them) → attribution is stream-based; if system tap recorded nothing, check System Audio Recording permission.
     - If `mr stop` says "not recording" but you think it is → stale pidfile; `mr status` shows it.
     - Speed: transcription is sequential, so a long call takes a bit — this is expected.
   - Be honest/accurate; do not invent commands/permissions that don't exist.
3. Both files: correct Markdown, no code changes, no stub placeholders. Do NOT modify any `mr/`, `capture/`, `tests/`, pyproject, or existing docs except README.md.

ACCEPTANCE:
- `README.md` exists, is non-stub and self-consistent with the actual CLI (spot-check a few command names/options against `mr/cli.py`).
- `docs/permissions-troubleshooting.md` exists.
- `git diff --stat` shows only `README.md` (rewrite) + the new doc file.
- Optional sanity: `./spike/.venv/bin/python -m mr.cli --help` output matches what the README claims are the subcommands.

OUT OF SCOPE:
- Do NOT change any code (`mr/`, `capture/`, `tests/`, pyproject.toml) or other docs.
- Do NOT add screenshots/images.
- Do NOT fabricate features. If unsure about a permission name or any behavior, write it generically and reference `mr doctor` / the code rather than inventing specifics.
- Do NOT commit (CTO agent owns git).

REPORT: reply with STATUS, FILES CHANGED, VERIFICATION (what you checked / `git diff --stat`), NOTES.