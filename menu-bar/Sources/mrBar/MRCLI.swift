import Foundation

/// Injectable seam for process spawning: all `MRCLI` subprocesses go through
/// this, so tests can inject a fake runner that returns canned (stdout, exit)
/// pairs without touching the real `mr` or the filesystem.
struct ProcessRunner {
    /// Runs `executable` with `args`, returning trimmed stdout + exit code.
    /// A non-zero exit is NOT an error — it is returned, not thrown.
    var run: (URL, [String]) throws -> (stdout: String, exit: Int32)

    /// Real implementation via Foundation `Process`.
    static let `default` = ProcessRunner(run: ProcessRunner.realRun)

    /// Hard timeout: `mr stop` transcribes (can take 1–3 min), so this is
    /// generous. On timeout the child is killed and an error is thrown.
    static let timeoutSeconds: TimeInterval = 120

    static func realRun(_ exe: URL, _ args: [String]) throws -> (String, Int32) {
        let process = Process()
        process.executableURL = exe
        process.arguments = args
        let stdoutPipe = Pipe()
        process.standardOutput = stdoutPipe
        process.standardError = FileHandle.nullDevice
        try process.run()
        let data = stdoutPipe.fileHandleForReading.readDataToEndOfFile()
        // readDataToEndOfFile returns once the child closes stdout (i.e. exits);
        // guard against a hung child with a hard deadline.
        let deadline = Date().addingTimeInterval(timeoutSeconds)
        while process.isRunning && Date() < deadline {
            Thread.sleep(forTimeInterval: 0.05)
        }
        if process.isRunning {
            process.terminate()
            throw MRCLIError.processTimeout
        }
        let out = String(data: data, encoding: .utf8)?
            .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return (out, process.terminationStatus)
    }
}

/// Errors surfaced by the CLI layer (distinct from a non-zero `mr` exit, which
/// is a normal returned value, not a throw).
enum MRCLIError: Error, Equatable {
    case mrUnavailable
    case processTimeout
}

/// Typed wrapper over the `mr` CLI. Every method returns the raw stdout plus
/// the exit code — the caller decides what the exit code means. Never raises
/// on non-zero exit (e.g. `mr config set` exit 2 on a bad path is data).
struct MRCLI {
    var runner: ProcessRunner = .default
    var invocation: MRInvocation? = AppInfo.resolveMrInvocation()

    func status() throws -> (out: String, exit: Int32) { try invoke(["status"]) }
    func start() throws -> (out: String, exit: Int32) {
        try start(withContextJSON: nil)
    }
    /// `mr start` with an optional `--context-json <path>` (CAL-L3). When
    /// `withContextJSON` is non-nil, the file at that path is persisted as
    /// `meeting_context.json` inside the new recording dir by the Python side.
    /// Passing `nil` behaves exactly like the no-arg `start()`.
    func start(withContextJSON: String? = nil) throws -> (out: String, exit: Int32) {
        var args = ["start"]
        if let ctx = withContextJSON {
            args.append(contentsOf: ["--context-json", ctx])
        }
        return try invoke(args)
    }
    func stop() throws -> (out: String, exit: Int32) { try invoke(["stop"]) }
    func setOutRoot(_ dir: String) throws -> (out: String, exit: Int32) {
        try invoke(["config", "set", "out_root", dir])
    }
    /// `mr config get out_root` — prints the resolved absolute root (bare path)
    /// on exit 0. Non-zero exit is returned, not thrown (mirrors `setOutRoot`).
    func configGetOutRoot() throws -> (out: String, exit: Int32) {
        try invoke(["config", "get", "out_root"])
    }

    private func invoke(_ args: [String]) throws -> (String, Int32) {
        guard let inv = invocation else { throw MRCLIError.mrUnavailable }
        let (exe, prefix): (URL, [String]) = switch inv {
        case .executable(let p): (URL(fileURLWithPath: p), [])
        case .python(let p): (URL(fileURLWithPath: p), ["-m", "mr.cli"])
        }
        return try runner.run(exe, prefix + args)
    }

    /// Builds the `--context-json` payload for `mr start` (CAL-L3). Pure and
    /// Foundation-only so it is testable without AppKit/EventKit. The six keys
    /// pass through verbatim to the persisted `meeting_context.json` (the
    /// Python side stores the raw JSON text). `start`/`end`/`notes` are already
    /// formatted strings; attendeeless/note-less events still carry the key.
    /// Returns `nil` only if the dictionary cannot serialize (should not
    /// happen for these value types).
    static func buildContextJSON(
        title: String,
        eventID: String,
        start: String,
        end: String,
        attendees: [String],
        notes: String
    ) -> String? {
        let obj: [String: Any] = [
            "title": title,
            "event_id": eventID,
            "start": start,
            "end": end,
            "attendees": attendees,
            "notes": notes,
        ]
        guard
            let data = try? JSONSerialization.data(
                withJSONObject: obj,
                options: [.sortedKeys, .fragmentsAllowed]
            )
        else { return nil }
        return String(data: data, encoding: .utf8)
    }
}

/// Parsed view of `mr status` stdout.
struct MRStatus {
    let recording: Bool
    let pid: Int?
    let stamp: String?
    let startedAt: String?

    /// Parse `mr status` output line-by-line. Tolerant: missing fields are nil,
    /// unknown lines (e.g. `last transcript: …`) are ignored.
    static func parse(_ stdout: String) -> MRStatus {
        var recording = false
        var pid: Int?
        var stamp: String?
        var startedAt: String?
        for rawLine in stdout.split(separator: "\n") {
            let line = rawLine.trimmingCharacters(in: .whitespaces)
            if line == "recording: yes" {
                recording = true
            } else if let value = field(line, key: "pid") {
                pid = Int(value)
            } else if let value = field(line, key: "stamp") {
                stamp = value
            } else if let value = field(line, key: "started_at") {
                startedAt = value
            }
        }
        return MRStatus(recording: recording, pid: pid, stamp: stamp, startedAt: startedAt)
    }

    /// Value of a `key: value` line, or nil if the line doesn't match.
    private static func field(_ line: String, key: String) -> String? {
        guard line.hasPrefix(key + ":") else { return nil }
        let value = line.dropFirst(key.count + 1).trimmingCharacters(in: .whitespaces)
        return value.isEmpty ? nil : value
    }
}
