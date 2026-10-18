import Foundation
import XCTest
@testable import mrBar

final class AppInfoTests: XCTestCase {

    /// Create a real, executable temp file standing in for the bundled
    /// frozen CLI entry binary (e.g. Contents/Resources/mr-cli/mr-cli).
    private func makeExecutableStub() throws -> String {
        let dir = FileManager.default.temporaryDirectory
        let file = dir.appendingPathComponent("mrBarAppInfoTest-\(UUID().uuidString)/mr-cli")
        try FileManager.default.createDirectory(at: file.deletingLastPathComponent(),
                                                withIntermediateDirectories: true)
        try "stub".write(to: file, atomically: true, encoding: .utf8)
        try FileManager.default.setAttributes([.posixPermissions: 0o755],
                                              ofItemAtPath: file.path)
        return file.path
    }

    private func paths(in candidates: [MRInvocation]) -> [String] {
        candidates.map { c in
            switch c {
            case .executable(let p), .python(let p): return p
            }
        }
    }

    func testBundledPathIsFirstCandidate() throws {
        let bundled = try makeExecutableStub()
        defer { try? FileManager.default.removeItem(at: URL(fileURLWithPath: bundled).deletingLastPathComponent()) }
        let candidates = AppInfo.mrCandidates(bundledMrCliPath: bundled)
        guard let first = candidates.first else {
            return XCTFail("expected at least one candidate")
        }
        if case .executable(let p) = first {
            XCTAssertEqual(p, bundled)
        } else {
            XCTFail("expected first candidate to be .executable, got \(first)")
        }
        // It must come BEFORE any PATH candidate (index 0).
        XCTAssertEqual(paths(in: candidates).first, bundled)
    }

    func testNilBundledPathProducesNoBundledCandidate() {
        let injected = "/fake/App.app/Contents/Resources/mr-cli/mr-cli"
        let candidates = AppInfo.mrCandidates(bundledMrCliPath: nil)
        XCTAssertFalse(paths(in: candidates).contains(injected),
                       "no candidate may carry the injected path when bundled is nil")
    }

    func testNonExecutablePathNotReturned() {
        let notExecutable = "/definitely/not/executable/mr-cli"
        let candidates = AppInfo.mrCandidates(bundledMrCliPath: notExecutable)
        XCTAssertFalse(paths(in: candidates).contains(notExecutable),
                       "a non-executable bundled path must not become a candidate")
    }
}
