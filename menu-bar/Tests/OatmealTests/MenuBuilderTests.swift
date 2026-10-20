import Foundation
import XCTest
@testable import Oatmeal

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

    // MARK: - Menu structure

    private func idleMenu(isCLIAvailable: Bool = true) -> NSMenu {
        let builder = MenuBuilder()
        builder.rebuild(
            status: MRStatus(recording: false, pid: nil, stamp: nil, startedAt: nil),
            isCLIAvailable: isCLIAvailable
        )
        return builder.menu
    }

    func testCalendarStartSitsDirectlyBelowStartRecording() {
        // The two are alternatives for the same intent: if the calendar row
        // drifts down the menu again, people default to the plain start.
        let titles = idleMenu().items.map(\.title)
        guard let startIndex = titles.firstIndex(of: "Start Recording") else {
            return XCTFail("no Start Recording item: \(titles)")
        }
        XCTAssertEqual(titles[startIndex + 1], "Start Recording from Calendar…")
    }

    func testNoIdleOrRecordingHeaderRow() {
        // The inert "(idle)"/"(recording)" row was a stop-gap and is gone.
        let titles = idleMenu().items.map(\.title)
        XCTAssertFalse(titles.contains("(idle)"), "stale header row: \(titles)")
        XCTAssertFalse(titles.contains("(recording)"), "stale header row: \(titles)")

        let builder = MenuBuilder()
        builder.rebuild(
            status: MRStatus(recording: true, pid: 42, stamp: "s1", startedAt: nil),
            isCLIAvailable: true
        )
        let recordingTitles = builder.menu.items.map(\.title)
        XCTAssertFalse(recordingTitles.contains("(recording)"), "stale header row: \(recordingTitles)")
    }

    func testMenuOpensWithStartRecording() {
        // Nothing inert above the first real action any more.
        XCTAssertEqual(idleMenu().items.first?.title, "Start Recording")
    }

    func testCheckActiveTranscriptionsItemIsPresentAndTagged() {
        let item = idleMenu().item(withTag: MenuBuilder.checkTranscriptionsTag)
        XCTAssertEqual(item?.title, "Check Active Transcriptions…")
        XCTAssertTrue(item?.isEnabled ?? false)
    }

    func testCalendarItemIsTaggedAndEnabledWithCLI() {
        let item = idleMenu().item(withTag: MenuBuilder.calendarMenuTag)
        XCTAssertEqual(item?.title, "Start Recording from Calendar…")
        XCTAssertTrue(item?.isEnabled ?? false)
        // Clickable with no pre-supplied events (the controller pops a dynamic
        // submenu); a static submenu is only attached when events are passed.
        XCTAssertNil(item?.submenu)
    }

    func testCalendarItemDisabledWithoutCLI() {
        let menu = idleMenu(isCLIAvailable: false)
        XCTAssertFalse(menu.item(withTag: MenuBuilder.calendarMenuTag)?.isEnabled ?? true)
        XCTAssertTrue(menu.items.map(\.title).contains("mr CLI not found (set MR_PYTHON)"))
    }

    // MARK: - Recording-section enablement

    private func recordingMenu(calendarEvents: [MeetingEvent] = []) -> NSMenu {
        let builder = MenuBuilder()
        builder.rebuild(
            status: MRStatus(recording: true, pid: 42, stamp: "s1", startedAt: nil),
            isCLIAvailable: true,
            calendarEvents: calendarEvents
        )
        return builder.menu
    }

    func testWhileRecordingOnlyStopIsEnabledInRecordSection() {
        // Both start paths must be disabled, not just the one that was used:
        // the calendar row previously checked isCLIAvailable alone, so
        // whichever row the user did not start from stayed clickable.
        let menu = recordingMenu()
        let byTitle = { (t: String) in menu.items.first { $0.title == t } }
        XCTAssertEqual(byTitle("Start Recording")?.isEnabled, false)
        XCTAssertEqual(byTitle("Start Recording from Calendar…")?.isEnabled, false)
        XCTAssertEqual(byTitle("Stop Recording & Transcribe")?.isEnabled, true)
    }

    func testWhileIdleBothStartPathsEnabledAndStopDisabled() {
        let menu = idleMenu()
        let byTitle = { (t: String) in menu.items.first { $0.title == t } }
        XCTAssertEqual(byTitle("Start Recording")?.isEnabled, true)
        XCTAssertEqual(byTitle("Start Recording from Calendar…")?.isEnabled, true)
        XCTAssertEqual(byTitle("Stop Recording & Transcribe")?.isEnabled, false)
    }

    func testCalendarSubmenuRowsDisabledWhileRecording() {
        // A disabled parent is not enough: pre-supplied event rows carried
        // isEnabled: isCLIAvailable independently of the recording state.
        let events = [
            MeetingEvent(
                id: "e1", title: "Standup", start: Date(), end: nil,
                attendees: [], notes: nil
            ),
            MeetingEvent(
                id: "e2", title: "1:1", start: Date(), end: nil,
                attendees: [], notes: nil
            ),
        ]
        let menu = recordingMenu(calendarEvents: events)
        guard let submenu = menu.item(withTag: MenuBuilder.calendarMenuTag)?.submenu else {
            return XCTFail("no calendar submenu")
        }
        // Every actionable row (the header has no action) must be disabled.
        let actionable = submenu.items.filter { $0.action != nil }
        XCTAssertFalse(actionable.isEmpty, "expected event rows")
        XCTAssertTrue(actionable.allSatisfy { !$0.isEnabled }, "enabled row while recording")
    }
}
