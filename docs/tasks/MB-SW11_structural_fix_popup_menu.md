# MB-SW11 — Structural fix v3: icon click must only open the dropdown

> MB-SW7 (disabled first row) and MB-SW10 (enabled no-op first row) both tried to
> make sure that *whichever* item the opening click auto-activates is harmless.
> The user confirms recording STILL auto-starts on a single icon click. Both were
> symptom patches, not a fix of the actual mechanism. This task removes the
> mechanism instead of dodging it.

## GOAL
A single left-click on the menu-bar icon ONLY opens the dropdown. It must never
invoke `startRecording` (or any other action) as part of that same click. The
user must make a second, separate click on "Start Recording" inside the already-
open menu to start a recording, and on "Stop Recording & Transcribe" to stop one.

## ROOT CAUSE
`StatusItemController.init` does:
```swift
statusItem.menu = menuBuilder.menu
```
Assigning `.menu` directly on an `NSStatusItem` makes `NSStatusBarButton` treat a
single click specially: AppKit opens the menu as part of the mouse-down and can
resolve the mouse-up as a click-through onto the menu item under the pointer /
the first highlighted row — i.e. open + activate can happen in one user gesture.
This is a known `NSStatusItem` gotcha. Moving which row is "first" (MB-SW7,
MB-SW10) doesn't remove this; it only gambles on where the click lands.

The structural fix: don't let AppKit auto-pop the assigned menu at all. Drive the
status item with a plain button click handler and pop the menu up explicitly and
only in response to that handler. A click handled this way is a complete,
discrete event by the time the menu appears — there is no mouse-up left over to
fall through onto a menu item, so nothing inside the menu can be activated by
the same click that opened it.

## CONTEXT
- Swift 6, AppKit, macOS SDK 27. Package: `menu-bar/` (SwiftPM).
- `menu-bar/Sources/mrBar/StatusItemController.swift` currently (relevant lines):
  ```swift
  final class StatusItemController: NSObject, NSMenuDelegate {
      let statusItem: NSStatusItem
      let menuBuilder: MenuBuilder
      ...
      override init() {
          self.statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
          self.menuBuilder = MenuBuilder()
          super.init()
          self.menuBuilder.target = self

          menuBuilder.menu.delegate = self
          statusItem.menu = menuBuilder.menu     // <-- this line is the bug
          setLive(false)
      }
      ...
      func menuWillOpen(_ menu: NSMenu) {
          refresh()
      }
  ```
- `menu-bar/Sources/mrBar/MenuBuilder.swift` currently inserts an ENABLED no-op
  header row as a workaround (MB-SW10):
  ```swift
  let header = NSMenuItem(
      title: statusHeader(status),
      action: #selector(StatusItemController.statusHeaderClicked(_:)),
      keyEquivalent: ""
  )
  header.target = target
  header.isEnabled = true
  menu.addItem(header)
  ```
  `statusHeaderClicked` is a no-op `@objc` method in `StatusItemController` (near
  the bottom, next to `quit`). `disabledItem(_:)` is a small helper already used
  elsewhere in the same file for plain inert rows.
- `NSStatusItem.button` is an `NSStatusBarButton?` (an `NSButton` subclass) that
  supports normal `.target`/`.action` wiring exactly like any other `NSButton`.
- To show a menu explicitly and get `NSMenuDelegate.menuWillOpen` to still fire
  for the lazy refresh, you can refresh *before* calling `popUp`, since
  `menuWillOpen` will no longer be the trigger point once `.menu` isn't assigned
  — doing the state rebuild directly in the click handler is simpler and
  equivalent (menuWillOpen won't be the one calling it anymore, but the delegate
  being set is harmless to leave in place or remove).

## FILES
- `menu-bar/Sources/mrBar/StatusItemController.swift`
- `menu-bar/Sources/mrBar/MenuBuilder.swift`

## READ FIRST
- `menu-bar/Sources/mrBar/StatusItemController.swift` lines 33–96 (init, setLive,
  refresh, menuWillOpen) and the `statusHeaderClicked` method near line 282.
- `menu-bar/Sources/mrBar/MenuBuilder.swift` lines 31–56 (the row-1 header block)
  and lines 138–142 (`disabledItem` helper).

## STEPS
1. In `StatusItemController.init`, remove `statusItem.menu = menuBuilder.menu`.
   Instead wire the button directly:
   ```swift
   statusItem.button?.target = self
   statusItem.button?.action = #selector(togglePressed(_:))
   ```
   Keep `menuBuilder.menu.delegate = self` (harmless; or remove it — your call,
   but if you keep it, `menuWillOpen` must not re-run `refresh()` a second time
   redundantly — see step 2).
2. Add a new method (near `menuWillOpen`):
   ```swift
   /// Button click handler: this is now the ONLY way the dropdown opens.
   /// Rebuilds state fresh, then pops the menu up explicitly — a structurally
   /// separate event from any click on an item inside the now-open menu, so
   /// nothing inside the menu can be auto-activated by this same click.
   @objc func togglePressed(_ sender: Any?) {
       refresh()
       guard let button = statusItem.button else { return }
       menuBuilder.menu.popUp(
           positioning: nil,
           at: NSPoint(x: 0, y: button.bounds.maxY + 4),
           in: button
       )
   }
   ```
   If `menuWillOpen` is still wired as the delegate and would double-call
   `refresh()`, that's fine (it's idempotent — just rebuilds the menu again from
   fresh state) but if you removed the delegate assignment in step 1, also
   delete the now-unused `func menuWillOpen(_ menu: NSMenu) { refresh() }`
   method and the `NSMenuDelegate` conformance only if nothing else needs it —
   check first; keep the class as `NSMenuDelegate` if easier, just make sure it
   still compiles.
3. In `MenuBuilder.rebuild(...)`, revert the row-1 header back to a plain
   disabled status label — it's no longer needed as a decoy since the opening
   click can no longer activate anything:
   ```swift
   menu.addItem(disabledItem(statusHeader(status)))
   ```
   Remove the no-op header's `action`/`target` wiring block it replaces.
4. In `StatusItemController`, delete the now-unused `statusHeaderClicked`
   no-op method (it was only there to serve the row-1 decoy).
5. Build:
   ```sh
   cd menu-bar
   export DEVELOPER_DIR="/Applications/Xcode.app/Contents/Developer"
   export TMPDIR="$PWD/.tmp" CLANG_MODULE_CACHE_PATH="$PWD/.modcache" SWIFTPM_CACHE_DIR="$PWD/.swiftpm-cache"
   swift build -c release --disable-sandbox
   swift test --disable-sandbox
   ```
   Both must exit 0.

## ACCEPTANCE
- `swift build -c release --disable-sandbox` exits 0.
- `swift test --disable-sandbox` exits 0 (existing suite, no new tests required —
  this is pure AppKit event wiring that XCTest can't simulate meaningfully).
- Read the final `StatusItemController.swift` and confirm: `statusItem.menu` is
  never assigned; `statusItem.button?.action` is set to `togglePressed`;
  `togglePressed` calls `refresh()` then `menuBuilder.menu.popUp(...)`.
- Read the final `MenuBuilder.swift` and confirm row 1 is `disabledItem(statusHeader(status))`
  with no custom action/target, and `startRecording`/`stopRecording` wiring on
  rows 2/3 is unchanged.

## OUT OF SCOPE
- Do not change `startRecording`, `stopRecording`, storage-location methods,
  `MRCLI`, `main.swift`, the Python side, or any test files.
- Do not change icon color/tint logic (`setLive`) — already correct per spec.
- Do not reorder menu items beyond what step 3 requires.

## REPORT
Reply with STATUS, FILES CHANGED, VERIFICATION (paste the tail of both build/test
command outputs), and NOTES (flag if `menuWillOpen`/`NSMenuDelegate` was removed
or left in place, and why).
