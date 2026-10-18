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
FROZEN_CLI="$(pwd)/../dist-freeze/mr-cli"     # repo-root frozen onedir tree
CAP_BIN="$(pwd)/../capture/.build/release/mr-capture"
RES_DIR="$APP/Contents/Resources"

if [[ ! -x "$BIN" ]]; then
  echo "install.sh: expected executable not found at $BIN" >&2
  exit 1
fi

# Assemble a minimal .app bundle (idempotent: overwrite on re-run).
mkdir -p "$APP/Contents/MacOS"
cp -f "$BIN" "$APP/Contents/MacOS/mrBar"
chmod +x "$APP/Contents/MacOS/mrBar"
cp -f "$(pwd)/Info.plist" "$APP/Contents/Info.plist"

# Copy the SwiftPM resource bundle into Contents/Resources/. SwiftPM emits the
# bundled PNGs (menu-bar icon, logo) as a separate `mrBar_mrBar.bundle` that is
# NOT inside the .app by default; Bundle.module resolves it via
# Bundle.main.resourceURL, so without this copy the app Fatal-errors at launch
# ("unable to find bundle named mrBar_mrBar") and shows no icon. Guarded because
# a resource-less build may not emit it.
RES_BUNDLE="$(pwd)/.build/release/mrBar_mrBar.bundle"
if [[ -d "$RES_BUNDLE" ]]; then
  mkdir -p "$RES_DIR"
  rm -rf "$RES_DIR/mrBar_mrBar.bundle"   # keep re-runs idempotent: cp -R into an existing dir double-nests it
  cp -R "$RES_BUNDLE" "$RES_DIR/mrBar_mrBar.bundle"
  echo "embedded SwiftPM resource bundle in $RES_DIR"
else
  echo "WARN: no SwiftPM resource bundle at $RES_BUNDLE — app will crash at launch (missing icon resources)."
fi

# Bundle the frozen mr-cli onedir tree + the mr-capture helper into Resources/
# so the app is self-contained (PKG-BUNDLE/1). Frozen CLI may be absent in a
# dev-only source build — embed only when both artifacts exist.
if [[ -x "$FROZEN_CLI/mr-cli" && -x "$CAP_BIN" ]]; then
  mkdir -p "$RES_DIR"
  rm -rf "$RES_DIR/mr-cli"
  cp -R "$FROZEN_CLI" "$RES_DIR/mr-cli"
  cp -f "$CAP_BIN" "$RES_DIR/mr-capture"
  chmod +x "$RES_DIR/mr-capture"
  echo "embedded frozen mr-cli + mr-capture in $RES_DIR"
else
  echo "WARN: frozen CLI ($FROZEN_CLI) or mr-capture ($CAP_BIN) missing — skipping embed; app is NOT self-contained (dev build)."
fi

# Adhoc codesign the bundle (deep: no embedded frameworks, but harmless).
codesign --force --deep --sign - "$APP"

echo "installed mrBar.app at $APP"
echo "note: drag the .app into /Applications to install it."
