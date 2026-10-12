#!/usr/bin/env bash
# Build mrBar and assemble the menu-bar .app bundle (MB-SW4).
#
# Usage: ./install.sh   (from anywhere; idempotent, no sudo)
#
# Produces:
#   menu-bar/.build/Release/mrBar.app
#     Contents/MacOS/mrBar     (the release binary from ./build.sh)
#     Contents/Info.plist      (LSUIElement + mic/audio usage strings)
#
# The bundle is left in the build dir — drag it into /Applications manually
# (see docs). It is adhoc-signed like the rest of the repo.
set -euo pipefail
cd "$(dirname "$0")"

./build.sh

BIN="$(pwd)/.build/release/mrBar"
APP="$(pwd)/.build/Release/mrBar.app"

if [[ ! -x "$BIN" ]]; then
  echo "install.sh: expected executable not found at $BIN" >&2
  exit 1
fi

# Assemble a minimal .app bundle (idempotent: overwrite on re-run).
mkdir -p "$APP/Contents/MacOS"
cp -f "$BIN" "$APP/Contents/MacOS/mrBar"
chmod +x "$APP/Contents/MacOS/mrBar"
cp -f "$(pwd)/Info.plist" "$APP/Contents/Info.plist"

# Adhoc codesign the bundle (deep: no embedded frameworks, but harmless).
codesign --force --deep --sign - "$APP"

echo "installed mrBar.app at $APP"
echo "note: drag the .app into /Applications to install it."
