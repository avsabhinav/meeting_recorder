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
  --exclude-module torch \
  --exclude-module torchgen \
  --add-data "$SITE/mlx/lib/mlx.metallib:mlx/lib" \
  --add-data "$SITE/mlx_whisper/assets:mlx_whisper/assets" \
  mr/cli.py
