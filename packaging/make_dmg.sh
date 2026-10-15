#!/usr/bin/env bash
# PKG-B1: Build all deliverables fresh and assemble a distributable DMG.
#
# Usage: ./packaging/make_dmg.sh   (from anywhere; idempotent, user-local only)
#
# What it does:
#   1. Builds mrBar.app          via menu-bar/install.sh
#   2. Builds mr-capture         via capture/install.sh
#   3. Stages a DMG volume containing:
#        mrBar.app
#        mr-capture
#        Install.command  (copied from packaging/Install.command if it
#                          exists; a stub placeholder until PKG-B2 lands)
#        Applications -> /Applications   (drag-to-install affordance)
#        README install.txt
#   4. Creates dist/MeetingRecorder-<VERSION>.dmg with hdiutil (UDZO, -ov).
#
# The DMG does NOT bundle the Python CLI: Install.command (PKG-B2) installs
# the `mr` CLI and the mr-capture helper into the user's environment.
# Everything is adhoc-signed, by design (no Developer ID).
set -euo pipefail

cd "$(dirname "$0")/.."
REPO_ROOT="$(pwd)"

# --- Version: read from pyproject.toml, fall back to a constant. -----------
VERSION="0.1.0"
if [[ -f pyproject.toml ]]; then
  V="$(sed -n 's/^version[[:space:]]*=[[:space:]]*"\(.*\)".*/\1/p' pyproject.toml | head -n1)"
  if [[ -n "${V:-}" ]]; then
    VERSION="$V"
  fi
fi

OUTPUT_DIR="$REPO_ROOT/dist"
OUTPUT_DMG="$OUTPUT_DIR/MeetingRecorder-${VERSION}.dmg"
mkdir -p "$OUTPUT_DIR"

# --- Staging dir + cleanup (removes staging, mount point, raw image on exit). -
STAGING="$(mktemp -d "${TMPDIR:-/tmp}/mr-dmg.XXXXXX")"
raw_image=""
MOUNT_PT=""
cleanup() {
  [[ -n "$MOUNT_PT" ]] && hdiutil detach "$MOUNT_PT" >/dev/null 2>&1 || true
  rm -rf "$STAGING" "$MOUNT_PT" "$raw_image"
}
trap cleanup EXIT

VOL="$STAGING/volume"
mkdir -p "$VOL"

# --- 1. Build all artifacts fresh from source. ------------------------------
echo "==> Building mrBar.app (menu-bar/install.sh)"
bash menu-bar/install.sh

echo "==> Building mr-capture (capture/install.sh)"
bash capture/install.sh

echo "==> Note: the Python CLI is not bundled; Install.command handles it."

APP_SRC="$REPO_ROOT/menu-bar/.build/Release/mrBar.app"
CAP_SRC="$REPO_ROOT/capture/.build/release/mr-capture"

if [[ ! -d "$APP_SRC" ]]; then
  echo "make_dmg.sh: missing $APP_SRC (did menu-bar/install.sh succeed?)" >&2
  exit 1
fi
if [[ ! -x "$CAP_SRC" ]]; then
  echo "make_dmg.sh: missing $CAP_SRC (did capture/install.sh succeed?)" >&2
  exit 1
fi

# --- 2. Assemble the volume staging directory. ------------------------------
cp -R "$APP_SRC" "$VOL/mrBar.app"
cp -f "$CAP_SRC" "$VOL/mr-capture"
chmod +x "$VOL/mr-capture"

# Install.command: use the real one when PKG-B2 has landed, else a stub.
if [[ -f packaging/Install.command ]]; then
  cp -f packaging/Install.command "$VOL/Install.command"
else
  cat > "$VOL/Install.command" <<'EOF'
#!/usr/bin/env bash
# Placeholder for the CLI installer (added in a later task, PKG-B2).
echo "Run packaging/Install.command from the repo for the CLI installer (added in a later task)."
EOF
  chmod +x "$VOL/Install.command"
fi

# Drag-to-install affordance.
ln -s /Applications "$VOL/Applications"

# Short install note.
cat > "$VOL/README install.txt" <<EOF
Meeting Recorder ${VERSION} — install

  1. Drag mrBar.app into the Applications folder (the icon on the right).
  2. Double-click Install.command to install the mr CLI and helper.
  3. First launch: right-click mrBar.app (or Install.command) and choose
     Open, since this build is adhoc-signed, not notarized.
EOF

# --- 3. Create the DMG (compressed, overwrite any existing one). ------------
# `hdiutil create -srcfolder` fails with "Directory not empty" on recent macOS,
# so build a blank image, mount it, copy the staging tree in, then detach and
# convert to compressed UDZO.
echo "==> Creating $OUTPUT_DMG"
rm -f "$OUTPUT_DMG"
raw_image="$(mktemp -u "${TMPDIR:-/tmp}/mr-raw.XXXXXX").dmg"
MOUNT_PT="$(mktemp -d "${TMPDIR:-/tmp}/mr-mount.XXXXXX")"

hdiutil create -size 200m -fs HFS+ -volname "Meeting Recorder" "$raw_image" >/dev/null
hdiutil attach "$raw_image" -mountpoint "$MOUNT_PT" -nobrowse >/dev/null
# Copy the staging tree (including the Applications symlink) into the volume.
ditto "$VOL" "$MOUNT_PT"
hdiutil detach "$MOUNT_PT" >/dev/null
hdiutil convert "$raw_image" -format UDZO -o "$OUTPUT_DMG"

# --- 4. Done. ---------------------------------------------------------------
echo
echo "==> DMG ready: $OUTPUT_DMG"
echo "==> Verify with: hdiutil verify \"$OUTPUT_DMG\""
