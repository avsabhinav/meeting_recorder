import Foundation
import XCTest
@testable import mrBar

/// Unit tests for the pure "Check Active Transcriptions…" display logic
/// (MB-DISPLAY/D3) — no AppKit, no `StatusItemController` instantiation.
final class MenuBuilderTests: XCTestCase {
    func testTranscriptionResultTextWithStamp() {
        XCTAssertEqual(
            MenuBuilder.transcriptionResultText(stamp: "2026-01-15_1030"),
            "2026-01-15_1030 — transcribing…"
        )
    }

    func testTranscriptionResultTextNilStamp() {
        XCTAssertEqual(
            MenuBuilder.transcriptionResultText(stamp: nil),
            "None (no active transcription)"
        )
    }

    func testTranscriptionResultTextEmptyStamp() {
        // Documents the empty-string edge; acceptable as-is.
        XCTAssertEqual(
            MenuBuilder.transcriptionResultText(stamp: ""),
            " — transcribing…"
        )
    }
}
