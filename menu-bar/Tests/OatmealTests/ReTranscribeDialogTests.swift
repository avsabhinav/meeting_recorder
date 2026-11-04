import Foundation
import XCTest
@testable import Oatmeal

/// Unit tests for the pure "Re-transcribe…" list/selection logic (RT-8) —
/// no AppKit; `present` (the only AppKit-touching member) is not covered here.
final class ReTranscribeDialogTests: XCTestCase {
    private var tmpDir: URL!

    override func setUpWithError() throws {
        tmpDir = FileManager.default.temporaryDirectory
            .appendingPathComponent("OatmealTests-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: tmpDir, withIntermediateDirectories: true)
    }

    override func tearDownWithError() throws {
        try? FileManager.default.removeItem(at: tmpDir)
    }

    private func makeRecording(_ stamp: String, mic: Bool, system: Bool) throws {
        let dir = tmpDir.appendingPathComponent("recordings").appendingPathComponent(stamp)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        if mic { FileManager.default.createFile(atPath: dir.appendingPathComponent("mic.wav").path, contents: Data()) }
        if system { FileManager.default.createFile(atPath: dir.appendingPathComponent("system.wav").path, contents: Data()) }
    }

    // MARK: - stamp(fromRecordingDirName:)

    func testStampAcceptsValidName() {
        XCTAssertEqual(ReTranscribeDialog.stamp(fromRecordingDirName: "2026-10-22_1440"), "2026-10-22_1440")
    }

    func testStampRejectsNonStamps() {
        XCTAssertEqual(ReTranscribeDialog.stamp(fromRecordingDirName: "2026-10-22"), nil)
        XCTAssertEqual(ReTranscribeDialog.stamp(fromRecordingDirName: "foo"), nil)
        XCTAssertEqual(ReTranscribeDialog.stamp(fromRecordingDirName: ".DS_Store"), nil)
        XCTAssertEqual(ReTranscribeDialog.stamp(fromRecordingDirName: "2026-10-22_1440_extra"), nil)
        XCTAssertEqual(ReTranscribeDialog.stamp(fromRecordingDirName: "2026-10-22_14"), nil)
    }

    // MARK: - isTranscribable

    func testIsTranscribableRequiresBothWavs() throws {
        try makeRecording("2026-10-22_1440", mic: true, system: true)
        try makeRecording("2026-10-21_1606", mic: true, system: false)
        try makeRecording("2026-10-20_1455", mic: false, system: false)

        let rec = ReTranscribeDialog.recordingsDirectory(root: tmpDir.path)
            .appendingPathComponent("2026-10-22_1440")
        XCTAssertTrue(ReTranscribeDialog.isTranscribable(rec))

        let micOnly = ReTranscribeDialog.recordingsDirectory(root: tmpDir.path)
            .appendingPathComponent("2026-10-21_1606")
        XCTAssertFalse(ReTranscribeDialog.isTranscribable(micOnly))

        let empty = ReTranscribeDialog.recordingsDirectory(root: tmpDir.path)
            .appendingPathComponent("2026-10-20_1455")
        XCTAssertFalse(ReTranscribeDialog.isTranscribable(empty))
    }

    // MARK: - transcribableStamps

    func testTranscribableStampsNewestFirst() throws {
        try makeRecording("2026-10-20_1455", mic: true, system: true)
        try makeRecording("2026-10-22_1440", mic: true, system: true)
        try makeRecording("2026-10-21_1606", mic: true, system: true)

        let dir = ReTranscribeDialog.recordingsDirectory(root: tmpDir.path)
        XCTAssertEqual(
            ReTranscribeDialog.transcribableStamps(inRecordingsDir: dir),
            ["2026-10-22_1440", "2026-10-21_1606", "2026-10-20_1455"]
        )
    }

    func testTranscribableStampsMissingDirectory() {
        let dir = tmpDir.appendingPathComponent("recordings") // never created
        XCTAssertEqual(ReTranscribeDialog.transcribableStamps(inRecordingsDir: dir), [])
    }

    // MARK: - candidates / candidateTitles

    func testCandidatesIncludeUntranscribableWithTitles() throws {
        try makeRecording("2026-10-22_1440", mic: true, system: true)
        try makeRecording("2026-10-21_1606", mic: true, system: false) // audio deleted
        try makeRecording("2026-10-20_1455", mic: true, system: true)

        let root = tmpDir.path
        let stamps = ReTranscribeDialog.candidates(root: root)
        let titles = ReTranscribeDialog.candidateTitles(root: root)

        XCTAssertEqual(stamps, ["2026-10-22_1440", "2026-10-21_1606", "2026-10-20_1455"])
        XCTAssertEqual(titles.count, stamps.count)
        XCTAssertEqual(
            titles,
            [
                "2026-10-22_1440 — ready",
                "2026-10-21_1606 — audio deleted",
                "2026-10-20_1455 — ready",
            ]
        )
    }

    // MARK: - URL helpers

    func testRecordingsDirectoryAndRecordingURL() {
        let root = "/tmp/oatmeal"
        XCTAssertEqual(
            ReTranscribeDialog.recordingsDirectory(root: root).path,
            "/tmp/oatmeal/recordings"
        )
        XCTAssertEqual(
            ReTranscribeDialog.recordingURL(root: root, stamp: "2026-10-22_1440").path,
            "/tmp/oatmeal/recordings/2026-10-22_1440"
        )
    }
}
