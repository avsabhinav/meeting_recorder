# Installing from the DMG

A distributable disk image (`MeetingRecorder-<version>.dmg`, built by
`packaging/make_dmg.sh`) contains `mrBar.app` (the menu-bar app), the
`mr-capture` helper, and a double-click installer (`Install.command`).

## Installing from the DMG

1. Double-click the DMG to mount it (a volume named **Meeting Recorder** appears).
2. Drag **mrBar.app** onto the **Applications** icon in the DMG window (it ends
   up in `/Applications/mrBar.app`).
3. Double-click **Install.command** in the DMG window. It opens a Terminal
   window and installs everything for **your user only — no sudo needed**.

## First launch / Gatekeeper

This build is **adhoc-signed, not notarized** (no Developer ID), so on a fresh
Mac Gatekeeper will block the first launch of `mrBar.app` — and may also block
double-clicking `Install.command`. You will see a dialog worded something like:

> "mrBar" can't be opened because Apple cannot check it for malicious software.

Fix it once: **right-click (control-click) `mrBar.app` → Open → Open** in the
confirmation dialog. The same right-click → Open trick works for
`Install.command` if Gatekeeper refuses to run it. After that, normal
double-click launches work.

## Terminal `mr` command

`Install.command` tries `pip install meeting-recorder` from PyPI, but the
package **is not published on PyPI yet**, so that step fails and the installer
finishes with an "INCOMPLETE" message — expected. To get the `mr` CLI working,
use a checkout of the repo:

```sh
git clone <repo> && cd <repo>
~/.local/share/mr-install/venv/bin/pip install -e .
```

Installing into the venv the installer already created makes the
`~/.local/bin/mr` shim work immediately. Until the package lands on PyPI, a
source checkout is required for the terminal `mr` command and for the
menu-bar app's CLI calls.

## How the installer wires things

- Creates a venv at `~/.local/share/mr-install/venv`; writes a
  `~/.local/bin/mr` shim that runs `mr` from that venv.
- Copies `mr-capture` to `/usr/local/bin` if writable, else `~/.local/bin`.
- Finder-launched GUI apps don't inherit your shell's `PATH`, so the installer
  sets `MR_PYTHON` and `MR_CAPTURE_BIN` via `launchctl setenv` — how a
  Finder-launched `mrBar` finds the CLI (only affects apps launched **after**
  the installer runs).
- Add the bin dir to your `PATH` once, in `~/.zshrc`:
  `export PATH="$HOME/.local/bin:$PATH"` — then open a **new** terminal.

## Verifying

1. `mr doctor` — reports the macOS version, the `mr-capture` helper location,
   and whether the Whisper model is cached (`mr doctor --fetch-model` fetches
   it once).
2. Quit and relaunch the `mrBar` menu-bar app so it picks up the new
   `MR_PYTHON` / `MR_CAPTURE_BIN` environment.
3. `mr toggle` to start a test recording, `mr toggle` again to stop — you
   should get a notification when the transcript lands in
   `~/Meetings/transcripts/`.
