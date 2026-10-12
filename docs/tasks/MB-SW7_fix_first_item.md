# MB-SW7 — Fix: icon click must not start recording (inert first menu row)

> **Epic MB (menu-bar app) — bug fix.** User report: "as soon as I click on the
> icon a meeting recording starts … it should just open the dropdown."
> Diagnosis (confirmed with the user): the single click **opens the dropdown AND
> the click lands on the first, auto-highlighted menu item, activating it**.
> That first item is `Start Recording`, so a single icon click starts recording.
> The Swift code has no icon-click → record path; the accidental activation is the
> macOS menu-bar "first highlighted item fires on open" behavior.

## Contract / background (do not change)
- `MenuBuilder.swift` builds the `NSMenu` that is assigned to `statusItem.menu`.
  Items with a `target` + `action` are actionable; disabled items (`isEnabled =
  false`, `action: nil`) are inert.
- `StatusItemController.swift` owns state and actions; **this task must not touch
  it**. Only the menu layout changes.
- Verify with: `DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer swift
  test` (or the package's `./build.sh`), plus the existing XCTest target.

## GOAL
When the user clicks the icon, the menu opens but **no recording starts**. The
first (topmost) menu row must be an inert, non-actionable item so an accidental
"click-through on menu open" lands on a row that cannot do anything.

## FILES
- `menu-bar/Sources/mrBar/MenuBuilder.swift` (only file to modify)
- `menu-bar/Tests/mrBarTests/` (only if you add a test; not required — no existing
  MenuBuilderTests target; keep changes to the one source file unless a test target
  already covers menu construction)

## READ FIRST
- `menu-bar/Sources/mrBar/MenuBuilder.swift` — the whole file (~125 lines), the
  `rebuild(...)` method (lines 31–118). Focus on the first item added at the top.

## STEPS
1. In `rebuild(...)`, **before** adding the `Start Recording` item, add a disabled
   status header as the very first row. Concretely, insert:
   ```swift
   // Inert status header — the topmost row. macOS highlights and can click-through
   // on the first item when the menu opens, so this MUST be disabled/non-actionable
   // (a live "Start Recording" as row 1 would start a recording on a mere icon click).
   menu.addItem(disabledItem(statusIcon(status)))
   ```
   Implement `statusIcon(status)` as a small private helper returning a string like
   `"● Idle"` when `!status.recording` and `"● Recording…"` when `status.recording`
   (ASCII-safe; avoid unicode that may not render in every menu font — use plain
   text such as `"(idle)"` / `"(recording)"` if unicode glyphs look wrong; ASCII is
   acceptable and preferred for these tests).
2. Keep `menu.autoenablesItems = false` (already set in `init`) so the header stays
   disabled and no autosuggestion flips it.
3. **Do not change** the behaviour/order of any other item. The `Start Recording`
   item must remain functional (clicking it in the OPEN menu still starts a
   recording) — moving it down by one row is the entire fix.
4. Compile and run the Swift tests.

## ACCEPTANCE
```sh
cd menu-bar
DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer swift build -c release
DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer swift test
```
Both must succeed (clean build + all existing tests green). Additionally, confirm
via code inspection that the first added `menu.addItem(...)` call in `rebuild` is
the new inert header, not `Start Recording`.

## OUT OF SCOPE
- Do **not** edit `StatusItemController.swift`, `main.swift`, MRCLI, or any Python.
- Do **not** change `startRecording`/`stopRecording` logic or the build/install
  scripts.
- Do **not** add new dependencies or change the Package.swift manifest.

## REPORT
Reply with STATUS, FILES CHANGED, VERIFICATION (paste the build+test command output
tail), and NOTES (what the first row is now).