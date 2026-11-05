import Foundation
import XCTest
@testable import Oatmeal

/// Reader for the transcription heartbeat (`<out_root>/.state/transcribing.json`).
///
/// The fixtures below use the CURRENT schema version (2, see
/// `mr.heartbeat.HEARTBEAT_VERSION`), which carries the owning worker's `pid`.
/// Tests whose subject is not the version field still have to use version 2,
/// or they would exercise the wrong-version rejection instead of the behaviour
/// they name.
final class TranscriptionStateTests: XCTestCase {
    private var tmpDir: URL!

    override func setUpWithError() throws {
        tmpDir = FileManager.default.temporaryDirectory
            .appendingPathComponent("OatmealTests-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: tmpDir, withIntermediateDirectories: true)
    }

    override func tearDownWithError() throws {
        try? FileManager.default.removeItem(at: tmpDir)
    }

    /// Write `<base>/.state/transcribing.json` with the given JSON body.
    private func writeHeartbeat(base: URL, body: String) throws {
        let stateDir = base.appendingPathComponent(".state")
        try FileManager.default.createDirectory(at: stateDir, withIntermediateDirectories: true)
        try body.write(to: stateDir.appendingPathComponent("transcribing.json"), atomically: true, encoding: .utf8)
    }

    func testFreshHeartbeatIsReturned() throws {
        let iso = ISO8601DateFormatter().string(from: Date())
        try writeHeartbeat(base: tmpDir, body: """
        {
          "version": 2,
          "stamp": "2024-05-01-1030",
          "out_root": "\(tmpDir.path)",
          "started_at": "\(iso)",
          "pid": 4711
        }
        """)
        let hb = try XCTUnwrap(TranscriptionState(baseURL: tmpDir).activeHeartbeat())
        XCTAssertEqual(hb.stamp, "2024-05-01-1030")
        XCTAssertNotNil(hb.startedAt)
        XCTAssertEqual(hb.pid, 4711)
    }

    func testFreshHeartbeatWithTrailingZ() throws {
        // Current UTC time as `...Z` — ISO8601DateFormatter must parse it.
        // (This is exactly the form the Python `_do_stop` now writes, e.g.
        // `2026-10-12T20:47:16.936490Z`.)
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = TimeZone(identifier: "UTC")
        f.dateFormat = "yyyy-MM-dd'T'HH:mm:ss.SSS'Z'"
        let z = f.string(from: Date())
        XCTAssertTrue(z.hasSuffix("Z"))
        try writeHeartbeat(base: tmpDir, body: """
        {"version":2,"stamp":"s","out_root":"x","started_at":"\(z)","pid":123}
        """)
        XCTAssertNotNil(TranscriptionState(baseURL: tmpDir).activeHeartbeat())
    }

    func testMissingHeartbeatIsNil() {
        XCTAssertNil(TranscriptionState(baseURL: tmpDir).activeHeartbeat())
    }

    func testStaleHeartbeatIsNil() throws {
        // started_at ~10 minutes ago; maxAge 60s => stale.
        let old = ISO8601DateFormatter().string(from: Date().addingTimeInterval(-600))
        try writeHeartbeat(base: tmpDir, body: """
        {"version":2,"stamp":"s","out_root":"x","started_at":"\(old)"}
        """)
        XCTAssertNil(TranscriptionState(baseURL: tmpDir).activeHeartbeat(maxAgeSeconds: 60))
    }

    func testFreshWithinCustomMaxAge() throws {
        let old = ISO8601DateFormatter().string(from: Date().addingTimeInterval(-60))
        try writeHeartbeat(base: tmpDir, body: """
        {"version":2,"stamp":"s","out_root":"x","started_at":"\(old)"}
        """)
        XCTAssertNotNil(TranscriptionState(baseURL: tmpDir).activeHeartbeat(maxAgeSeconds: 120))
    }

    func testMalformedJSONIsNil() throws {
        try writeHeartbeat(base: tmpDir, body: "not json {")
        XCTAssertNil(TranscriptionState(baseURL: tmpDir).activeHeartbeat())
    }

    func testVersion1IsNil() throws {
        // Version 1 predates the `pid` field: treated as stale, so a reader
        // can never act on a heartbeat it cannot signal.
        let iso = ISO8601DateFormatter().string(from: Date())
        try writeHeartbeat(base: tmpDir, body: """
        {"version":1,"stamp":"s","out_root":"x","started_at":"\(iso)"}
        """)
        XCTAssertNil(TranscriptionState(baseURL: tmpDir).activeHeartbeat())
    }

    func testUnknownVersionIsNil() throws {
        let iso = ISO8601DateFormatter().string(from: Date())
        try writeHeartbeat(base: tmpDir, body: """
        {"version":3,"stamp":"s","out_root":"x","started_at":"\(iso)"}
        """)
        XCTAssertNil(TranscriptionState(baseURL: tmpDir).activeHeartbeat())
    }

    func testMissingPidIsStillReturnedWithNilPid() throws {
        // A heartbeat without a PID is still information worth showing; only
        // STOPPING it needs a PID.
        let iso = ISO8601DateFormatter().string(from: Date())
        try writeHeartbeat(base: tmpDir, body: """
        {"version":2,"stamp":"s","out_root":"x","started_at":"\(iso)"}
        """)
        let hb = try XCTUnwrap(TranscriptionState(baseURL: tmpDir).activeHeartbeat())
        XCTAssertNil(hb.pid)
    }

    func testNonIntegerPidYieldsNilPidNotRejection() throws {
        let iso = ISO8601DateFormatter().string(from: Date())
        try writeHeartbeat(base: tmpDir, body: """
        {"version":2,"stamp":"s","out_root":"x","started_at":"\(iso)","pid":"4711"}
        """)
        let hb = try XCTUnwrap(TranscriptionState(baseURL: tmpDir).activeHeartbeat())
        XCTAssertNil(hb.pid)
    }

    func testMissingStampIsNil() throws {
        let iso = ISO8601DateFormatter().string(from: Date())
        try writeHeartbeat(base: tmpDir, body: """
        {"version":2,"out_root":"x","started_at":"\(iso)"}
        """)
        XCTAssertNil(TranscriptionState(baseURL: tmpDir).activeHeartbeat())
    }

    // MARK: - updated_at (liveness refreshed by the worker)

    func testLongRunWithFreshUpdatedAtIsReturned() throws {
        // Started 20 min ago, refreshed just now: still transcribing.
        let started = ISO8601DateFormatter().string(from: Date().addingTimeInterval(-1200))
        let updated = ISO8601DateFormatter().string(from: Date())
        try writeHeartbeat(base: tmpDir, body: """
        {"version":2,"stamp":"s","out_root":"x","started_at":"\(started)","updated_at":"\(updated)","pid":7}
        """)
        let hb = try XCTUnwrap(TranscriptionState(baseURL: tmpDir).activeHeartbeat())
        XCTAssertEqual(hb.pid, 7)
    }

    func testStaleUpdatedAtIsNil() throws {
        let started = ISO8601DateFormatter().string(from: Date().addingTimeInterval(-1200))
        let updated = ISO8601DateFormatter().string(from: Date().addingTimeInterval(-600))
        try writeHeartbeat(base: tmpDir, body: """
        {"version":2,"stamp":"s","out_root":"x","started_at":"\(started)","updated_at":"\(updated)","pid":7}
        """)
        XCTAssertNil(TranscriptionState(baseURL: tmpDir).activeHeartbeat())
    }

    func testUnparseableUpdatedAtIsNil() throws {
        let started = ISO8601DateFormatter().string(from: Date())
        try writeHeartbeat(base: tmpDir, body: """
        {"version":2,"stamp":"s","out_root":"x","started_at":"\(started)","updated_at":"garbage","pid":7}
        """)
        XCTAssertNil(TranscriptionState(baseURL: tmpDir).activeHeartbeat())
    }
}
