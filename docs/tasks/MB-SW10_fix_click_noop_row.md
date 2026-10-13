# MB-SW10 — Fix v2: icon click must only open the dropdown (enabled no-op first row)

> The MB-SW7 fix (a DISABLED inert first row) did not hold — the user still sees
> a single icon click START a recording. Root cause of the residual bug: on a
> single click, macOS opens the menu and **auto-activates the first ENABLED,
> actionable item under the click — it SKIPS disabled rows**. So the disabled
> row-1 header fell through to the next enabled item ("Start Recording") and the
> mouse-up fired it. Fix: make the first row **ENABLED with a harmless no-op
> action** so the auto-activation hits that row instead of "Start Recording".

## GOAL
A single left-click of the menu-bar icon opens the dropdown and NEVER starts a
recording. Clicking "Start Recording" inside the open menu still works normally.

## CONTEXT
- `MenuBuilder.rebuild(...)` (file `menu-bar/Sources/mrBar/MenuBuilder.swift`)
  currently adds, as the very first row:
  ```swift
  menu.addItem(disabledItem(statusHeader(status)))
  ```
  (`disabledItem` sets `isEnabled = false`, `action: nil`.)
- `statusHeader(_ status:)` returns `"(idle)"` / `"(recording)"`.
- All menu items target the controller via `target`/`action`; `menu.autoenablesItems`
  is `false`.
- The controller is `StatusItemController` (file
  `menu-bar/Sources/mrBar/StatusItemController.swift`), an `NSObject, NSMenuDelegate`.

## FILES
- `menu-bar/Sources/mrBar/MenuBuilder.swift`
- `menu-bar/Sources/mrBar/StatusItemController.swift`

## READ FIRST
- `menu-bar/Sources/mrBar/MenuBuilder.swift` lines ~31-46 (start of `rebuild`) and
  lines ~125-134 (`statusHeader`, `disabledItem`).
- `menu-bar/Sources/mrBar/StatusItemController.swift` — any existing
  `@objc func quit(_:)` near the bottom (~line 283) as a pattern for a small
  `@objc` action method; and confirm where to add one.

## STEPS
1. In `MenuBuilder.rebuild(...)`, replace the first row so it is an ENABLED
   no-op status header instead of a disabled one:
   ```swift
   // MB-SW10: first row is ENABLED but harmless. A single icon click opens the
   // menu and macOS auto-activates the first ENABLED actionable item (it skips
   // disabled rows), so this row — not "Start Recording" — absorbs the accidental
   // activation. Its action is a no-op.
   let header = NSMenuItem(
       title: statusHeader(status),
       action: #selector(StatusItemController.statusHeaderClicked(_:)),
       keyEquivalent: ""
   )
   header.target = target
   header.isEnabled = true
   menu.addItem(header)
   ```
   Keep `statusHeader`; the `disabledItem` helper stays (used elsewhere).
2. In `StatusItemController`, add a no-op action method (near `quit`):
   ```swift
   /// No-op: row-1 status header absorbs an accidental icon-click activation (MB-SW10).
   @objc func statusHeaderClicked(_ sender: Any?) {}
   ```
3. Do not change anything else: "Start Recording" stays the 2nd row, still
   targeted at `StatusItemController.startRecording`, enabled when the CLI is
   available; Stop / storage / open-folder / quit unchanged.
4. Build + test.

## ACCEPTANCE
```sh
cd menu-bar
export DEVELOPER_DIR="/Applications/Xcode.app/Contents/Developer"
export TMPDIR="$PWD/.tmp" CLANG_MODULE_CACHE_PATH="$PWD/.modcache" SWIFTPM_CACHE_DIR="$PWD/.swiftpm-cache"
swift build -c release --disable-sandbox
swift test --disable-sandbox
```
Both must exit 0 (clean build; existing 18 Swift tests green). Confirm by reading
the code that (a) the first `menu.addItem(...)` in `rebuild` adds an **enabled**
header whose selector is `statusHeaderClicked`, and (b) `startRecording` is still
the 2nd row and unchanged.

## OUT OF SCOPE
- Do NOT change `startRecording`, `stopRecording`, storage-location methods, MRCLI,
  main.swift, the Python side, tests, or build scripts.
- Do NOT reorder other items or change the rest of the menu.

## REPORT
Reply with STATUS, FILES CHANGED, VERIFICATION (paste the tail of both command
outputs), and NOTES.