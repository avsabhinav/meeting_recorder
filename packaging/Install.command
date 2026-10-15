#!/usr/bin/env bash
# Meeting Recorder — installer (double-clickable from the DMG).
#
# Sets up, for the current user only (NO sudo):
#   1. The `mr` Python CLI  ->  ~/.local/bin/mr   (shim into a venv python)
#   2. The mr-capture helper -> /usr/local/bin/mr-capture (if writable)
#                                   else ~/.local/bin/mr-capture
#   3. launchctl setenv MR_PYTHON / MR_CAPTURE_BIN so the Finder-launched
#      mrBar menu-bar app can find the CLI (GUI apps don't inherit your
#      shell's PATH).
#
# Honest note on the `mr` package:
#   This installer tries `pip install meeting-recorder` from PyPI. That
#   package is NOT published there as of this writing, so this step will
#   normally FAIL and the script exits with a message telling you to install
#   from source instead (see the final failure message). The venv,
#   mr-capture, and launchctl setup below still complete so a source install
#   into the same venv just works afterwards.
#
# Re-runnable: safe to run again; it upgrades the venv, refreshes
# mr-capture, and re-sets the launchd env vars (unset first to avoid dupes).

set -euo pipefail

# When copied into the DMG, Install.command sits NEXT TO mr-capture.
cd "$(dirname "$0")"
INSTALL_DIR="$(pwd)"
CAP_SRC="$INSTALL_DIR/mr-capture"

# --- Layout (all user-local, no sudo) ---------------------------------------
MR_ROOT="$HOME/.local/share/mr-install"
VENV="$MR_ROOT/venv"
BIN="${HOME}/.local/bin"
mkdir -p "$MR_ROOT" "$BIN"

note()  { printf '\n==> %s\n' "$*"; }
warn()  { printf 'WARNING: %s\n' "$*" >&2; }
fail()  { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

# --- 1. Find a usable Python 3.12+ ------------------------------------------
py_ok() {  # $1 = interpreter path; true if it runs and is >= 3.12
  [[ -x "$1" ]] && "$1" -c 'import sys; sys.exit(0 if sys.version_info >= (3,12) else 1)' 2>/dev/null
}

PY=""

# Candidate 0: an existing `mr` already on PATH → re-install is just an
# upgrade; still fine to run through the normal venv path below.
if command -v mr >/dev/null 2>&1; then
  echo "==> Found existing 'mr' at $(command -v mr); refreshing it."
fi

# Candidates 1-3: python3.12 / 3.13 / 3.14 on PATH.
for c in python3.12 python3.13 python3.14; do
  if command -v "$c" >/dev/null 2>&1 && py_ok "$(command -v "$c")"; then
    PY="$(command -v "$c")"
    break
  fi
done

# Candidate 4: uv-managed base interpreters (e.g. cpython-3.12.13-macos-aarch64-none).
if [[ -z "$PY" ]]; then
  for c in "$HOME"/.local/share/uv/python/cpython-3.12*/bin/python3.1*; do
    if py_ok "$c"; then PY="$c"; break; fi
  done
fi

# Candidate 5: system python3, if it happens to be >= 3.12.
if [[ -z "$PY" ]] && py_ok /usr/bin/python3; then
  PY="/usr/bin/python3"
fi

if [[ -z "$PY" ]]; then
  fail "Python 3.12+ required. Install from https://www.python.org/downloads/macos/ and re-run this installer."
fi
echo "==> Using Python: $PY ($("$PY" --version 2>&1))"

# --- 2. Create the venv (if not already a valid one) -------------------------
if [[ ! -x "$VENV/bin/python" ]]; then
  note "Creating venv at $VENV"
  "$PY" -m venv "$VENV"
fi

note "Upgrading pip"
"$VENV/bin/pip" install --quiet --upgrade pip

# --- 3. Install the `mr` CLI package -----------------------------------------
# Honest caveat: `meeting-recorder` is not (yet) on PyPI. Try anyway so the
# script works automatically once it is published; otherwise fall back to
# source instructions.
if "$VENV/bin/pip" install --quiet meeting-recorder 2>/dev/null; then
  note "Installed 'meeting-recorder' from PyPI."
  MR_INSTALLED=1
else
  MR_INSTALLED=0
  warn "'meeting-recorder' is not on PyPI yet."
  warn "Finish the CLI install from a repo checkout with:"
  warn "    \"$VENV/bin/pip\" install -e ./"
  warn "That places 'mr' in \"$VENV/bin/mr\"; the shim below still works."
  warn "Continuing with the rest of the install (mr-capture + launchctl)..."
fi

# Create the ~/.local/bin/mr shim. It works whether the package came from
# PyPI (console script) or from `pip install -e .` (console script too);
# `-m mr.cli` is the guaranteed fallback if the console script is missing.
note "Writing $BIN/mr shim"
cat > "$BIN/mr" <<'SHIM'
#!/usr/bin/env bash
exec "$MR_PYTHON" -m mr.cli "$@"
SHIM
sed -i '' "s|\"\$MR_PYTHON\"|\"$VENV/bin/python\"|" "$BIN/mr"
chmod +x "$BIN/mr"

# --- 4. Install mr-capture ---------------------------------------------------
if [[ ! -f "$CAP_SRC" ]]; then
  fail "mr-capture not found next to Install.command ($CAP_SRC). Is the DMG mounted correctly?"
fi

if [[ -w /usr/local/bin || ( ! -d /usr/local/bin && -w /usr/local ) ]]; then
  CAP_DEST="/usr/local/bin/mr-capture"
else
  CAP_DEST="$BIN/mr-capture"
fi
mkdir -p "$(dirname "$CAP_DEST")"
cp -f "$CAP_SRC" "$CAP_DEST"
chmod +x "$CAP_DEST"
note "Installed mr-capture -> $CAP_DEST"

# --- 5. Wire the Finder-launched mrBar app ------------------------------------
# GUI apps launched from Finder don't inherit your shell PATH; per-user
# launchd env (launchctl setenv) is the native way to reach them.
note "Setting launchd env for GUI apps (affects apps launched AFTER this)"
launchctl unsetenv MR_PYTHON      2>/dev/null || true
launchctl unsetenv MR_CAPTURE_BIN 2>/dev/null || true
launchctl setenv MR_PYTHON "$VENV/bin/python"
launchctl setenv MR_CAPTURE_BIN "$CAP_DEST"

# --- 6. Done -----------------------------------------------------------------
cat <<EOF

==> Install complete.

Next steps:
  1. Add the CLI bin dir to your PATH (once) — append to ~/.zshrc:
         export PATH="$BIN:$PATH"
     Then open a NEW terminal. (Contains: mr)
  2. Relaunch the mrBar menu-bar app (quit it and start it again) so it
     picks up the new launchd env.
  3. Verify with:  mr doctor

First launch note: this build is adhoc-signed, not notarized — if Gatekeeper
blocks mrBar.app (or this script), right-click it and choose "Open".
EOF

if [[ "$MR_INSTALLED" -ne 1 ]]; then
  printf '\nINCOMPLETE: the `mr` package was not installed (it is not on PyPI yet).\n'
  printf '             From a checkout of the repo, run:\n'
  printf '                 "$VENV/bin/pip" install -e .\n'
  printf '             Then everything above is ready to use. (Exit code 1.)\n'
  exit 1
fi
