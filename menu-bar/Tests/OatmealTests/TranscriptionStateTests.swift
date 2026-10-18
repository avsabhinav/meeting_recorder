import Foundation
import XCTest
@testable import Oatmeal

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
          "version": 1,
          "stamp": "2024-05-01-1030",
          "out_root": "\(tmpDir.path)",
          "started_at": "\(iso)"
        }
        """)
        let hb = try XCTUnwrap(TranscriptionState(baseURL: tmpDir).activeHeartbeat())
        XCTAssertEqual(hb.stamp, "2024-05-01-1030")
        XCTAssertNotNil(hb.startedAt)
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
        {"version":1,"stamp":"s","out_root":"x","started_at":"\(z)"}
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
        {"version":1,"stamp":"s","out_root":"x","started_at":"\(old)"}
        """)
        XCTAssertNil(TranscriptionState(baseURL: tmpDir).activeHeartbeat(maxAgeSeconds: 60))
    }

    func testFreshWithinCustomMaxAge() throws {
        let old = ISO8601DateFormatter().string(from: Date().addingTimeInterval(-60))
        try writeHeartbeat(base: tmpDir, body: """
        {"version":1,"stamp":"s","out_root":"x","started_at":"\(old)"}
        """)
        XCTAssertNotNil(TranscriptionState(baseURL: tmpDir).activeHeartbeat(maxAgeSeconds: 120))
    }

    func testMalformedJSONIsNil() throws {
        try writeHeartbeat(base: tmpDir, body: "not json {")
        XCTAssertNil(TranscriptionState(baseURL: tmpDir).activeHeartbeat())
    }

    func testWrongVersionIsNil() throws {
        let iso = ISO8601DateFormatter().string(from: Date())
        try writeHeartbeat(base: tmpDir, body: """
        {"version":2,"stamp":"s","out_root":"x","started_at":"\(iso)"}
        """)
        XCTAssertNil(TranscriptionState(baseURL: tmpDir).activeHeartbeat())
    }

    func testMissingStampIsNil() throws {
        let iso = ISO8601DateFormatter().string(from: Date())
        try writeHeartbeat(base: tmpDir, body: """
        {"version":1,"out_root":"x","started_at":"\(iso)"}
        """)
        XCTAssertNil(TranscriptionState(baseURL: tmpDir).activeHeartbeat())
    }
}
