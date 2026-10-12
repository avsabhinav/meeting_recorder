#!/usr/bin/env bash
# Build mr-capture into a signed-release binary with an embedded Info.plist
# (the micro usage descriptions) so macOS shows proper permission prompts.
#
# Usage: ./build.sh
# Produces: spike/capture/.build/release/mr-capture
set -euo pipefail
cd "$(dirname "$0")"

PLIST="$(pwd)/Info.plist"
BIN=".build/release/mr-capture"

echo "==> swift build -c release (embedding Info.plist)"
# --disable-sandbox: needed when run inside the DSH tool sandbox (sandbox-exec is
# blocked there); harmless and a no-op when invoked from a normal terminal.
swift build --disable-sandbox -c release \
  -Xlinker -sectcreate -Xlinker __TEXT -Xlinker __info_plist -Xlinker "$PLIST"

echo "==> verifying embedded plist section"
otool -s __TEXT __info_plist "$BIN" | head -20

echo "==> codesign (adhoc)"
codesign --force --sign - "$BIN"

echo "==> done: $BIN"
echo "==> run with: $BIN --out <dir> [--no-aec]"