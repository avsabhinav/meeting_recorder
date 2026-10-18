#!/usr/bin/env bash
# PKG-B1: Build all deliverables fresh and assemble a distributable DMG.
#
# Usage: ./packaging/make_dmg.sh   (from anywhere; idempotent, user-local only)
#
# What it does:
#   1. Freezes the mr CLI from source (packaging/freeze_cli.sh) so the bundled
#      binary is always current — a stale dist-freeze must never ship.
#   2. Builds mrBar.app (with the embedded frozen CLI + mr-capture inside)
#      via menu-bar/install.sh
#   3. Stages a DMG volume containing ONLY:
#        mrBar.app
#        Applications -> /Applications   (drag-to-install affordance)
#      (single-drag; PKG-BUNDLE/5)
#   4. Creates dist/Oatmeal-<VERSION>.dmg with hdiutil (UDZO, -ov), with a
#      size computed from the staged content, and opens a laid-out Finder
#      drag window.
#
# Everything is adhoc-signed, by design (no Developer ID).
# PKG_DMG_STAGE_ONLY=1: assemble staging + layout, exit before hdiutil
# (for sandboxed CI where hdiutil device/mount ops are denied).
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
OUTPUT_DMG="$OUTPUT_DIR/Oatmeal-${VERSION}.dmg"
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
# Freeze the CLI from the current source FIRST. `install.sh` embeds whatever is
# in dist-freeze/mr-cli, so re-freezing here guarantees the DMG cannot carry a
# stale binary (the working tree's cli.py is the source of truth).
echo "==> Freezing the mr CLI from source (packaging/freeze_cli.sh)"
bash packaging/freeze_cli.sh

echo "==> Building mrBar.app (menu-bar/install.sh; embeds the frozen CLI + mr-capture)"
bash menu-bar/install.sh

APP_SRC="$REPO_ROOT/menu-bar/.build/Release/mrBar.app"

if [[ ! -d "$APP_SRC" ]]; then
  echo "make_dmg.sh: missing $APP_SRC (did menu-bar/install.sh succeed?)" >&2
  exit 1
fi

# --- 2. Assemble the volume staging directory. ------------------------------
# The volume now contains ONLY mrBar.app (with the embedded frozen CLI +
# mr-capture inside it) and the Applications symlink — single-drag; PKG-BUNDLE/5.
cp -R "$APP_SRC" "$VOL/mrBar.app"

# Drag-to-install affordance.
ln -s /Applications "$VOL/Applications"

# Compute a raw-image size that surely fits the staged content. The app is
# ~950 MB (embedded frozen CLI across ~3k small files), so a fixed 200m can
# never hold it. du -sk gives KiB; convert to MiB, then add a generous margin:
# HFS+ allocates in large blocks and adds per-file metadata, so the raw volume
# needs *notably* more than the apparent size (100m cushion proved too small on
# a real build). Use 50% headroom with a 1536m floor (plain 1.5 GiB works fine;
# the UDZO-compressed output is far smaller than the raw image).
APP_MB=$(($(du -sk "$VOL" | awk '{print $1}') / 1024))
SIZE_MB=$((APP_MB + APP_MB / 2))
if [[ $SIZE_MB -lt 1536 ]]; then SIZE_MB=1536; fi

# PKG_DMG_STAGE_ONLY=1: assemble staging + layout, then exit before hdiutil
# (for sandboxed CI where hdiutil device/mount ops are denied). No DMG written.
if [[ "${PKG_DMG_STAGE_ONLY:-0}" == "1" ]]; then
  echo "==> STAGE_ONLY: staging complete at $VOL (cleanup removes it on exit)"
  echo "==> STAGE_ONLY SIZE_MB=${SIZE_MB}m"
  echo "==> STAGE_ONLY content:"; find "$VOL" -maxdepth 1 -print | sort
  exit 0
fi

# --- 3. Create the DMG (compressed, overwrite any existing one). ------------
# `hdiutil create -srcfolder` fails with "Directory not empty" on recent macOS,
# so build a blank image, mount it, copy the staging tree in, then detach and
# convert to compressed UDZO.
echo "==> Creating $OUTPUT_DMG"
rm -f "$OUTPUT_DMG"
raw_image="$(mktemp -u "${TMPDIR:-/tmp}/mr-raw.XXXXXX").dmg"
MOUNT_PT="$(mktemp -d "${TMPDIR:-/tmp}/mr-mount.XXXXXX")"

hdiutil create -size "${SIZE_MB}m" -fs HFS+ -volname "Oatmeal" "$raw_image" >/dev/null
hdiutil attach "$raw_image" -mountpoint "$MOUNT_PT" -nobrowse >/dev/null
# Copy the staging tree (including the Applications symlink) into the volume.
ditto "$VOL" "$MOUNT_PT"

# Open + lay out the mounted window so double-clicking the DMG shows the
# classic "drag mrBar.app to Applications" window immediately.
open "$MOUNT_PT"
osascript -e 'tell application "Finder" to activate' \
  -e 'tell application "Finder" to set the bounds of the front window to {50, 50, 520, 480}' \
    >/dev/null 2>&1 || true

hdiutil detach "$MOUNT_PT" >/dev/null
hdiutil convert "$raw_image" -format UDZO -o "$OUTPUT_DMG"

# --- 4. Done. ---------------------------------------------------------------
echo
echo "==> DMG ready: $OUTPUT_DMG"
echo "==> Verify with: hdiutil verify \"$OUTPUT_DMG\""
