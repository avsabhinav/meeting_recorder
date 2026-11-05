import Foundation
import XCTest
@testable import Oatmeal

final class MRCLITests: XCTestCase {

    private func makeCLI(invocation: MRInvocation?,
                         canned: (stdout: String, exit: Int32)) -> MRCLI {
        var cli = MRCLI()
        cli.invocation = invocation
        cli.runner = ProcessRunner { exe, args, env in
            MRCLITests.lastCall = (exe, args, env)
            return canned
        }
        return cli
    }

    private static var lastCall: (exe: URL, args: [String], env: [String: String])?

    func testExecutableInvocationNoPrefix() throws {
        let cli = makeCLI(invocation: .executable("/usr/local/bin/mr"),
                          canned: ("recording: no", 0))
        let (out, exit) = try cli.status()
        XCTAssertEqual(out, "recording: no")
        XCTAssertEqual(exit, 0)
        let call = try XCTUnwrap(Self.lastCall)
        XCTAssertEqual(call.exe.path, "/usr/local/bin/mr")
        XCTAssertEqual(call.args, ["status"])
    }

    func testPythonInvocationUsesModulePrefix() throws {
        let cli = makeCLI(invocation: .python("/venv/bin/python3"),
                          canned: ("", 0))
        _ = try cli.start()
        let call = try XCTUnwrap(Self.lastCall)
        XCTAssertEqual(call.exe.path, "/venv/bin/python3")
        XCTAssertEqual(call.args, ["-m", "mr.cli", "start"])
    }

    func testSetOutRootBuildsConfigArgs() throws {
        let cli = makeCLI(invocation: .executable("/usr/local/bin/mr"),
                          canned: ("out_root: /tmp/x", 0))
        _ = try cli.setOutRoot("/tmp/x")
        let call = try XCTUnwrap(Self.lastCall)
        XCTAssertEqual(call.args, ["config", "set", "out_root", "/tmp/x"])
    }

    func testConfigGetOutRootBuildsConfigArgs() throws {
        let cli = makeCLI(invocation: .executable("/usr/local/bin/mr"),
                          canned: ("/Users/u/Meetings", 0))
        let (out, exit) = try cli.configGetOutRoot()
        XCTAssertEqual(out, "/Users/u/Meetings")
        XCTAssertEqual(exit, 0)
        let call = try XCTUnwrap(Self.lastCall)
        XCTAssertEqual(call.args, ["config", "get", "out_root"])
    }

    func testStopReturnsCanned() throws {
        let cli = makeCLI(invocation: .executable("/usr/local/bin/mr"),
                          canned: ("transcribed", 0))
        let (out, exit) = try cli.stop()
        XCTAssertEqual(out, "transcribed")
        XCTAssertEqual(exit, 0)
    }

    func testNonZeroExitIsReturnedNotThrown() throws {
        let cli = makeCLI(invocation: .executable("/usr/local/bin/mr"),
                          canned: ("bad path", 2))
        let (out, exit) = try cli.setOutRoot("/no/such/dir")
        XCTAssertEqual(out, "bad path")
        XCTAssertEqual(exit, 2)
    }

    func testBundledCaptureBinPassesEnvToRunner() throws {
        var cli = makeCLI(invocation: .executable("/x/mr"),
                          canned: ("recording: no", 0))
        cli.bundledCaptureBin = "/fake/bundle/mr-capture"
        _ = try cli.status()
        let call = try XCTUnwrap(Self.lastCall)
        XCTAssertEqual(call.env, ["MR_CAPTURE_BIN": "/fake/bundle/mr-capture"])
    }

    func testNoBundledCaptureBinPassesEmptyEnv() throws {
        var cli = makeCLI(invocation: .executable("/x/mr"),
                          canned: ("recording: no", 0))
        cli.bundledCaptureBin = nil
        _ = try cli.status()
        let call = try XCTUnwrap(Self.lastCall)
        XCTAssertTrue(call.env.isEmpty)
    }

    func testMrUnavailableWhenNoInvocation() throws {
        let cli = makeCLI(invocation: nil, canned: ("", 0))
        try XCTAssertThrowsError(try cli.status()) { error in
            XCTAssertEqual(error as? MRCLIError, .mrUnavailable)
        }
        try XCTAssertThrowsError(try cli.stop()) { error in
            XCTAssertEqual(error as? MRCLIError, .mrUnavailable)
        }
    }

    func testStopTranscribeWithoutStampBuildsBareArg() throws {
        let cli = makeCLI(invocation: .executable("/usr/local/bin/mr"),
                          canned: ("stopped transcription of 2026-10-22_1440", 0))
        let (out, exit) = try cli.stopTranscribe()
        XCTAssertEqual(out, "stopped transcription of 2026-10-22_1440")
        XCTAssertEqual(exit, 0)
        let call = try XCTUnwrap(Self.lastCall)
        XCTAssertEqual(call.args, ["stop-transcribe"])
    }

    func testStopTranscribeWithStampAppendsStamp() throws {
        let cli = makeCLI(invocation: .executable("/usr/local/bin/mr"),
                          canned: ("no transcription running for 2026-10-22_1440", 0))
        let (out, exit) = try cli.stopTranscribe(stamp: "2026-10-22_1440")
        XCTAssertEqual(out, "no transcription running for 2026-10-22_1440")
        XCTAssertEqual(exit, 0)
        let call = try XCTUnwrap(Self.lastCall)
        XCTAssertEqual(call.args, ["stop-transcribe", "2026-10-22_1440"])
    }

    func testStopTranscribeEmptyStampIgnored() throws {
        let cli = makeCLI(invocation: .executable("/usr/local/bin/mr"),
                          canned: ("no transcription running", 0))
        _ = try cli.stopTranscribe(stamp: "")
        let call = try XCTUnwrap(Self.lastCall)
        XCTAssertEqual(call.args, ["stop-transcribe"])
    }

    func testRetranscribeBuildsArgs() throws {
        let cli = makeCLI(invocation: .executable("/usr/local/bin/mr"),
                          canned: ("retranscribing 2026-10-22_1044", 0))
        let (out, exit) = try cli.retranscribe("2026-10-22_1044")
        XCTAssertEqual(out, "retranscribing 2026-10-22_1044")
        XCTAssertEqual(exit, 0)
        let call = try XCTUnwrap(Self.lastCall)
        XCTAssertEqual(call.args, ["retranscribe", "2026-10-22_1044"])
    }

    func testRetranscribeNonZeroExitIsReturnedNotThrown() throws {
        let cli = makeCLI(invocation: .executable("/usr/local/bin/mr"),
                          canned: ("no recording for 2026-10-22_1044", 1))
        let (out, exit) = try cli.retranscribe("2026-10-22_1044")
        XCTAssertEqual(out, "no recording for 2026-10-22_1044")
        XCTAssertEqual(exit, 1)
    }

    func testPythonInvocationPrefixForStopTranscribe() throws {
        let cli = makeCLI(invocation: .python("/venv/bin/python"),
                          canned: ("no transcription running", 0))
        _ = try cli.stopTranscribe(stamp: "2026-10-22_1440")
        let call = try XCTUnwrap(Self.lastCall)
        XCTAssertEqual(call.exe.path, "/venv/bin/python")
        XCTAssertEqual(call.args, ["-m", "mr.cli", "stop-transcribe", "2026-10-22_1440"])
    }

    func testMRStatusParseRecording() {
        let stdout = """
        recording: yes
        pid: 12345
        out_dir: /Users/u/Meetings/recordings/2024-05-01-1030
        stamp: 2024-05-01-1030
        started_at: 2024-05-01T10:30:00.123456
        last transcript: /Users/u/Meetings/transcripts/2024-04-30.md
        """
        let s = MRStatus.parse(stdout)
        XCTAssertTrue(s.recording)
        XCTAssertEqual(s.pid, 12345)
        XCTAssertEqual(s.stamp, "2024-05-01-1030")
        XCTAssertEqual(s.startedAt, "2024-05-01T10:30:00.123456")
    }

    func testMRStatusParseIdle() {
        let s = MRStatus.parse("recording: no\nlast transcript: /x/y.md")
        XCTAssertFalse(s.recording)
        XCTAssertNil(s.pid)
        XCTAssertNil(s.stamp)
        XCTAssertNil(s.startedAt)
    }

    func testMRStatusParseGarbage() {
        let s = MRStatus.parse("")
        XCTAssertFalse(s.recording)
        XCTAssertNil(s.pid)
    }
}
