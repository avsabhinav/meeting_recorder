TASK: MB-DISPLAY/D3 Add unit tests for the on-demand "Check Active Transcriptions…" display logic
GOAL: The (formerly inline) logic that renders the "Check Active Transcriptions…" result is extracted into a small, pure, testable function, and the controller calls it. New XCTest cases cover every branch so `swift test` stays green and the display string is regression-protected.
CONTEXT: `mrBar` is a macOS menu-bar app (Swift/AppKit). D2 added `StatusItemController.checkActiveTranscriptions(_:)`, which currently builds the final label inline with `stamp.map { "\($0) — transcribing…" } ?? "None (no active transcription)"`. The existing test target (`mrBarTests`) is Foundation-only and unit-tests pure logic (`MRCLI`, `MRStatus.parse`, `TranscriptionState`) — it does NOT instantiate the AppKit `StatusItemController`. To test the new display logic without the UI, we extract it into a pure static on `MenuBuilder` (same place as the item's tag) and call it from the controller. Your working directory is the repo root: `/Users/abhinavademmagari/Documents/Projects/meeting recorder`.
FILES (create/modify ONLY these): menu-bar/Sources/mrBar/MenuBuilder.swift, menu-bar/Sources/mrBar/StatusItemController.swift, menu-bar/Tests/mrBarTests/MenuBuilderTests.swift (new)
READ FIRST:
- menu-bar/Sources/mrBar/MenuBuilder.swift (after D2) — add the static helper near `checkTranscriptionsTag`.
- menu-bar/Sources/mrBar/StatusItemController.swift (after D2) — `checkActiveTranscriptions` body uses the helper.
- menu-bar/Tests/mrBarTests/MRCLITests.swift and TranscriptionStateTests.swift — follow the existing `import XCTest` / `@testable import mrBar` style.
STEPS:
1. `MenuBuilder.swift`: add a pure static function:
```swift
    /// Display text for the "Check Active Transcriptions…" result (MB-DISPLAY/D3).
    /// `nil` (no in-flight transcription) -> "None"; a stamp -> "<stamp> — transcribing…".
    static func transcriptionResultText(stamp: String?) -> String {
        stamp.map { "\($0) — transcribing…" } ?? "None (no active transcription)"
    }
```
2. `StatusItemController.swift`: in `checkActiveTranscriptions(_:)`, replace the inline `let final = stamp.map { ... } ?? "None (no active transcription)"` with `let final = MenuBuilder.transcriptionResultText(stamp: stamp)`. Nothing else changes.
3. NEW `menu-bar/Tests/mrBarTests/MenuBuilderTests.swift`: mirror the existing test-file style (`import Foundation`/`import XCTest` + `@testable import mrBar`). Add a `final class MenuBuilderTests: XCTestCase` with cases:
   - `testTranscriptionResultTextWithStamp`: `XCTAssertEqual(MenuBuilder.transcriptionResultText(stamp: "2026-01-15_1030"), "2026-01-15_1030 — transcribing…")`.
   - `testTranscriptionResultTextNilStamp`: `XCTAssertEqual(MenuBuilder.transcriptionResultText(stamp: nil), "None (no active transcription)")`.
   - `testTranscriptionResultTextEmptyStamp`: `XCTAssertEqual(MenuBuilder.transcriptionResultText(stamp: ""), " — transcribing…")` (documents the empty-string edge; acceptable as-is).
ACCEPTANCE:
1. `cd menu-bar && DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer env TMPDIR="$(pwd)/.tmp" CLANG_MODULE_CACHE_PATH="$(pwd)/.modcache" SWIFTPM_CACHE_DIR="$(pwd)/.swiftpm-cache" swift test --disable-sandbox` → all tests pass, INCLUDING the 3 new ones (report total executed, was 18 before → expect 21). Ensure `.tmp`/`.modcache`/`.swiftpm-cache` dirs exist first (`mkdir -p .tmp .modcache .swiftpm-cache`).
2. `cd menu-bar && bash build.sh` → exit 0 and prints "==> done:" (the helper is small and the app still builds).
3. `git diff --stat` for the three files is small (< ~60 lines total); no reformatting of unrelated lines.
OUT OF SCOPE: changing the `checkActiveTranscriptions` async/threading behavior or its status/heartbeat lookups, the `refresh()` D1 path, other tests, Python, capture. Do not add UI/Action-sending tests that instantiate `StatusItemController`.
REPORT: reply with STATUS, FILES CHANGED, VERIFICATION (swift test tail showing 21 passed, build.sh tail, diff stat), and NOTES.