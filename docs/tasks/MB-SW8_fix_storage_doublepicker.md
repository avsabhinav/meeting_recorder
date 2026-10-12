# MB-SW8 — Fix: storage-location change re-opens the folder picker (and the follow-on `mr start failed`)

> **Epic MB (menu-bar app) — bug fix.** User report: (1) after changing the
> storage location and confirming, the folder picker popped up again; (2) then
> `Start Recording` reported `mr start failed`. This task fixes the code bug
> behind (1); (2) is a knock-on of (1) re-entrancy leaving `out_root` briefly
> wrong — `mr start` itself is verified working on the real Mac.

## Contract / background (do not change)
- `StatusItemController.swift` owns UI state and actions. It shells out to `mr`
  (never touches config itself). The menu is **lazily rebuilt on every menu open**
  (`menuWillOpen` → `refresh()` → `MenuBuilder.rebuild()`), so an immediate refresh
  inside an action handler is unnecessary for correctness.
- The bug: `changeRoot(...)` calls `refresh()` at the end (line 238). `refresh()`
  → `menuBuilder.rebuild(...)` → `menu.removeAllItems()` + re-add items. When this
  runs inside a menu-action handler, macOS can click-through onto the re-added
  same-position item, re-firing `Change Storage Location…` → the picker reopens.
  Also, AppKit's `NSSavePanel` docs require calling `orderOut(nil)` on the panel
  before showing an alert from the completion handler (the panel sheet may still be
  on screen and would otherwise interact with the modal alert). We do NOT currently
  call `orderOut`, and we DO show a modal `NSAlert` inside the handler.

## GOAL
Changing the storage location shows the confirmation **once**, then the picker
must NOT re-open. Nothing else's behaviour changes.

## FILES
- `menu-bar/Sources/mrBar/StatusItemController.swift` (only file to modify)

## READ FIRST
- `menu-bar/Sources/mrBar/StatusItemController.swift`:
  - `changeStorageLocation(...)` — lines ~192-204 (creates the `NSOpenPanel`,
    calls `panel.begin { ... }` whose handler guards `response == .OK`,
    `let url = panel.url`, then calls `self?.changeRoot(url.path)`).
  - `changeRoot(...)` — lines ~209-239 (runs `MRCLI().setOutRoot(newRoot)`, shows a
    modal `NSAlert` success/warning, then calls `refresh()` at the very end).

## STEPS
1. In `changeStorageLocation(...)`, inside the `begin` completion handler, **right
   before** `self?.changeRoot(url.path)` (i.e. after the guard), add a call to close
   the still-on-screen panel: `panel.orderOut(nil)`. (Verified: `NSOpenPanel.orderOut`
   type-checks in this toolchain.)
2. In `changeRoot(...)`, **remove the final `refresh()` call** (and its comment) so the
   menu is NOT rebuilt inside the action handler. The menu refreshes automatically on
   the next `menuWillOpen` (lazy model), so no behaviour is lost — the new root is
   reflected in the Transcribing section / Open-Folder paths on the next open.
3. Do not change anything else: the `NSAlert` copy, the CLI call, the guard, or any
   other method.

## ACCEPTANCE
```sh
cd menu-bar
export DEVELOPER_DIR="/Applications/Xcode.app/Contents/Developer"
export TMPDIR="$PWD/.tmp" CLANG_MODULE_CACHE_PATH="$PWD/.modcache" SWIFTPM_CACHE_DIR="$PWD/.swiftpm-cache"
swift build -c release --disable-sandbox
swift test --disable-sandbox
```
Both must exit 0 (clean build; existing 18 Swift tests green). Confirm by reading the
file that (a) `orderOut(nil)` is called before `changeRoot`, and (b) `changeRoot` no
longer calls `refresh()` at the end.

## OUT OF SCOPE
- Do NOT change `MenuBuilder.swift`, `main.swift`, MRCLI, StorageLocation, any Python,
  tests, or build/install scripts.
- Do NOT change `startRecording`/`stopRecording`/`openSubfolder` logic.
- The `mr start failed` symptom is NOT fixed in this task (it is a knock-on of the
  double-picker); it will be re-verified by the user after this fix.

## REPORT
Reply with STATUS, FILES CHANGED, VERIFICATION (paste the tail of both command outputs),
and NOTES.