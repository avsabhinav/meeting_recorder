# Installing from the DMG

A distributable disk image (`Oatmeal-<version>.dmg`, built by
`packaging/make_dmg.sh`) contains **only** `mrBar.app` (the menu-bar app) and
an **Applications** shortcut. `mrBar.app` is **self-contained** — it bundles
the frozen `mr` CLI and the `mr-capture` helper inside the app, so installing
is a single drag. There is no installer step, no venv, and no `launchctl`
wiring.

## Installing from the DMG

1. Double-click the DMG (a volume named **Oatmeal** mounts and a Finder window
   opens).
2. Drag **mrBar.app** onto the **Applications** shortcut in the window (it
   ends up in `/Applications/mrBar.app`). **Done.**
3. Eject the volume. No separate installer step — the app is self-contained.

## First launch / Gatekeeper

This build is **adhoc-signed, not notarized** (no Developer ID), so on a fresh
Mac Gatekeeper will block the first launch of `mrBar.app`. You will see a
dialog worded something like:

> "mrBar" can't be opened because Apple cannot check it for malicious software.

Fix it once: **right-click (control-click) `mrBar.app` → Open → Open** in the
confirmation dialog. After that, normal double-click launches work.

## Terminal `mr` command (optional, dev only)

The bundled app does **not** need the terminal `mr` command. If you want the
standalone `mr` CLI in your own terminal, install it from a source checkout
(the package is **not published on PyPI yet**):

```sh
git clone <repo> && cd <repo>
python3 -m venv .venv && . .venv/bin/activate && pip install -e '.[dev]'
```

`mr doctor` (CLI tool) reports the macOS version, the `mr-capture` helper
location, and whether the Whisper model is cached (`mr doctor --fetch-model`
fetches it once).

## How the install works

- The DMG is self-contained: `mrBar.app/Contents/Resources/mr-cli/` holds the
  frozen `mr` CLI, and `mrBar.app/Contents/Resources/mr-capture` holds the
  capture helper. The app resolves its own CLI and sets `MR_CAPTURE_BIN`
  internally (PKG-BUNDLE), so a bundled install needs **no `PATH` setup, no
  venv, and no `launchctl setenv`**.
- **Dev / source checkouts only:** when you run `mrBar` from a source build
  (not the DMG), it falls back to `mr` on `PATH` (e.g. `pip install -e .`),
  then `MR_PYTHON`; the capture helper is found via `MR_CAPTURE_BIN` or the
  repo build. See the README's "Menu-bar app" notes.

## Verifying

1. Launch `mrBar.app` (right-click → Open on first run) and grant the
   microphone / audio permissions when prompted.
2. Start a recording with the menu bar's **Start Recording**, then **Stop
   Recording & Transcribe**.
3. You should get a notification when the transcript lands in
   `~/Meetings/transcripts/`.
