#!/usr/bin/env bash
# Build mrBar into a signed-release binary (MB-SW1 scaffold; no Info.plist yet —
# added with the AppKit menu-bar app in later tasks).
#
# Usage: ./build.sh
# Produces: menu-bar/.build/release/mrBar
set -euo pipefail
cd "$(dirname "$0")"

# Prefer the full Xcode toolchain if it's installed, even when xcode-select
# still points at CommandLineTools (needed so `swift test`/XCTest resolve and
# the build matches the Xcode SDK). No-op when not overridden.
if [ -z "${DEVELOPER_DIR:-}" ] && [ -x "/Applications/Xcode.app/Contents/Developer/usr/bin/swift" ]; then
  export DEVELOPER_DIR="/Applications/Xcode.app/Contents/Developer"
fi

# Fallback for restrictive shells (e.g. the DSH tool sandbox, where writes to
# ~/Library/org.swift.swiftpm and the system temp dir are denied): redirect the
# Swift toolchain caches to workspace-local dirs. No-op in a normal terminal.
if ! touch "$HOME/Library/org.swift.swiftpm/.probe" 2>/dev/null \
   || ! touch "${TMPDIR:-/tmp}/.probe" 2>/dev/null; then
  mkdir -p .tmp .modcache .swiftpm-cache
  export TMPDIR="$(pwd)/.tmp"
  export CLANG_MODULE_CACHE_PATH="$(pwd)/.modcache"
  export SWIFTPM_CACHE_DIR="$(pwd)/.swiftpm-cache"
fi
rm -f "$HOME/Library/org.swift.swiftpm/.probe" "${TMPDIR:-/tmp}/.probe" 2>/dev/null || true

BIN=".build/release/mrBar"

echo "==> swift build -c release"
# --disable-sandbox: needed when run inside the DSH tool sandbox (sandbox-exec is
# blocked there); harmless and a no-op when invoked from a normal terminal.
swift build --disable-sandbox -c release

echo "==> codesign (adhoc)"
codesign --force --sign - "$BIN"

echo "==> done: $(pwd)/$BIN"
