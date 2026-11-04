import Foundation
import XCTest
@testable import Oatmeal

/// Unit tests for the pure "transcription stopped" notification text —
/// no posting (which would require authorization and a bundle identity).
final class TranscriptNotifierTests: XCTestCase {
    func testStoppedNotificationTextWithStamp() {
        let (title, body) = TranscriptNotifier.stoppedNotificationText(stamp: "2026-10-22_1440")
        XCTAssertEqual(title, "Transcription stopped")
        XCTAssertTrue(body.contains("2026-10-22_1440"))
        XCTAssertTrue(body.contains("Re-transcribe"))
    }

    func testStoppedNotificationTextEmptyStamp() {
        let (title, body) = TranscriptNotifier.stoppedNotificationText(stamp: "")
        XCTAssertEqual(title, "Transcription stopped")
        XCTAssertFalse(body.contains("  "))
        XCTAssertTrue(body.contains("Re-transcribe"))
    }

    func testStoppedNotificationTextWhitespaceOnlyStamp() {
        let (title, body) = TranscriptNotifier.stoppedNotificationText(stamp: "   ")
        XCTAssertEqual(title, "Transcription stopped")
        XCTAssertFalse(body.contains("  "))
        XCTAssertTrue(body.contains("Re-transcribe"))
    }

    func testStoppedNotificationTextPaddedStamp() {
        let (title, body) = TranscriptNotifier.stoppedNotificationText(stamp: " 2026-10-22_1440 ")
        XCTAssertEqual(title, "Transcription stopped")
        XCTAssertTrue(body.contains("2026-10-22_1440"))
        XCTAssertFalse(body.contains(" 2026"))
    }
}
