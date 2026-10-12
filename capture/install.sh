#!/usr/bin/env bash
# Build mr-capture and "install" it to the stable repo-local location.
#
# Usage: ./install.sh   (from anywhere; idempotent, no sudo)
#
# The default install destination is the in-tree release build:
#   capture/.build/release/mr-capture
# which is exactly what mr/core/capture.py's DEFAULT_CAPTURE_BIN resolves to,
# so no environment is needed after running this script.
#
# To install to a system location instead (e.g. /usr/local/bin), build with
# ./build.sh and copy the binary yourself, then point the wrapper at it:
#   export MR_CAPTURE_BIN=/usr/local/bin/mr-capture
set -euo pipefail
cd "$(dirname "$0")"

./build.sh

BIN="$(pwd)/.build/release/mr-capture"

if [[ ! -x "$BIN" ]]; then
  echo "install.sh: expected executable not found at $BIN" >&2
  exit 1
fi

echo "installed mr-capture at $BIN"
echo "note: MR_CAPTURE_BIN can override this location (e.g. for a system install)."
