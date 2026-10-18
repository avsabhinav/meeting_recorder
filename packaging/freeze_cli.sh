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
  --add-data "$SITE/mlx/lib/mlx.metallib:mlx/lib" \
  --add-data "$SITE/mlx_whisper/assets:mlx_whisper/assets" \
  mr/cli.py
