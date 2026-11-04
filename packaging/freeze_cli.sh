#!/usr/bin/env bash
# PyInstaller onedir freeze of the `mr` CLI (spike PKG-FREEZE/1).
set -euo pipefail
cd "$(dirname "$0")/.."
# Redirect PyInstaller's binary-analysis cache dir to a workspace-local path;
# `~/Library/Application Support` is not writable in a sandboxed build env.
export PYINSTALLER_CONFIG_DIR="${PYINSTALLER_CONFIG_DIR:-$(pwd)/build-freeze-cache}"
# SITE: absolute path to the dev venv site-packages (has the mlx / mlx_whisper
# packages). PyInstaller resolves --add-data paths relative to the .spec file's
# directory (packaging/), so these MUST be absolute or rooted at $(pwd).
SITE="$(pwd)/.venv/lib/python3.12/site-packages"
# EXCLUSIONS: --collect-all mlx transitively drags in torch (583 MB) and
# torchgen, which this pipeline never imports. The only torch reference in
# mlx_whisper is torch_whisper.py, a PyTorch->MLX weight-conversion helper that
# nothing imports (__init__.py pulls only audio, decoding, load_models and
# transcribe). Dropping them takes the bundle from ~948 MB to ~350 MB.
#
# DO NOT also exclude numba or scipy: mlx_whisper/timing.py imports both at
# module scope (lines 8 and 10), and __init__.py -> transcribe.py -> timing.py
# makes that unconditional. Excluding them freezes fine and then fails at
# transcription time with ModuleNotFoundError -- verified the hard way.
#
# DIARIZATION (mlx_audio): only mlx_audio.vad is needed. mlx_audio's registry
# loads model modules via importlib, so nemotron_diarization is listed as a
# hidden import. transformers/tokenizers/sentencepiece are reachable only via
# mlx_audio's STT registry (smart_turn -> stt -> granite_speech_nar), which
# mr.core.diarize stubs out before importing; they are excluded so torch
# never comes back in through them.
#
# mlx_audio/registry.py builds a table AT IMPORT TIME by listing its own
# package directory (Path(__file__).parent.iterdir()). In a onedir freeze the
# modules live in the PYZ archive, so _internal/mlx_audio does not exist and
# `import mlx_audio.vad` dies with FileNotFoundError (diarization then falls
# back to `Them`). The source tree is therefore also shipped on disk (~25 MB)
# purely so that directory listing works; imports still come from the PYZ.
.venv/bin/pyinstaller \
  --name mr-cli \
  --onedir \
  --distpath dist-freeze \
  --workpath build-freeze \
  --specpath packaging \
  --console \
  --noconfirm \
  -p . \
  --collect-all mlx \
  --collect-submodules mlx_whisper \
  --collect-submodules mlx_audio.vad \
  --hidden-import mlx_audio.vad.models.nemotron_diarization \
  --exclude-module torch \
  --exclude-module torchgen \
  --exclude-module transformers \
  --exclude-module tokenizers \
  --exclude-module sentencepiece \
  --add-data "$SITE/mlx/lib/mlx.metallib:mlx/lib" \
  --add-data "$SITE/mlx_whisper/assets:mlx_whisper/assets" \
  --add-data "$SITE/mlx_audio:mlx_audio" \
  mr/cli.py
