import Foundation

/// How to invoke the `mr` CLI for one subcommand (args come separately at call time).
enum MRInvocation {
    /// The resolved `mr` executable path (e.g. from PATH) — run directly.
    case executable(String)
    /// Python interpreter to run `-m mr.cli ...` (e.g. a venv python).
    case python(String)
}

enum AppInfo {
    /// Path to the bundled frozen CLI inside this app's Resources, if the app is
    /// running as a real bundle (never when running as bare `swift run`/xctest).
    /// PKG-BUNDLE/2: the highest-precedence candidate; returns nil when not in a
    /// real bundle or the entry binary is missing/not executable.
    static func bundledMrCliPath() -> String? {
        guard let url = Bundle.main.url(forResource: "mr-cli", withExtension: nil,
                                        subdirectory: nil) else { return nil }
        let exe = url.appendingPathComponent("mr-cli").path
        return pathExists(executableAt: exe) ? exe : nil
    }

    /// Path to the bundled mr-capture helper inside this app's Resources
    /// (PKG-BUNDLE/3), or nil when not running as a real bundle.
    static func bundledCaptureBinPath() -> String? {
        guard let url = Bundle.main.url(forResource: "mr-capture", withExtension: nil) else { return nil }
        let p = url.path
        return pathExists(executableAt: p) ? p : nil
    }

    /// Candidates for the `mr` CLI, most-preferred first. Each invocation's
    /// launch path + fixed leading args (e.g. python `["-m","mr.cli"]`).
    static func mrCandidates(bundledMrCliPath: String? = AppInfo.bundledMrCliPath()) -> [MRInvocation] {
        var candidates: [MRInvocation] = []
        // 0. Highest precedence: the CLI bundled inside this app (PKG-BUNDLE/2).
        //    Only offered if the entry binary actually exists and is executable.
        if let p = bundledMrCliPath, pathExists(executableAt: p) {
            candidates.append(.executable(p))
        }
        // 1. `mr` on PATH (e.g. an installed console script).
        if let path = which("mr"), !path.isEmpty {
            candidates.append(.executable(path))
        }
        // 2. Env override MR_PYTHON: a python interpreter (venv) that can `-m mr.cli`.
        if let py = ProcessInfo.processInfo.environment["MR_PYTHON"], !py.isEmpty {
            candidates.append(.python(py))
        }
        // No fabricated fallbacks: if nothing above is discoverable, the UI
        // should show an explicit "mr CLI not found" error menu item.
        return candidates
    }

    /// Best-effort resolution against the current environment:
    /// returns the first candidate whose executable/launch-path exists and is
    /// executable, or nil if none are usable.
    static func resolveMrInvocation() -> MRInvocation? {
        for candidate in mrCandidates() {
            let path: String
            switch candidate {
            case .executable(let p): path = p
            case .python(let p): path = p
            }
            if pathExists(executableAt: path) {
                return candidate
            }
        }
        return nil
    }

    /// The app bundle identifier (used for plist + notifications).
    static var bundleID: String { "com.oatmeal.app" }

    /// Synchronously run `/usr/bin/env which <name>`; return the trimmed stdout
    /// path on exit 0, else nil. (PATH lookup for a CLI not installed here.)
    static func which(_ name: String) -> String? {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/env")
        process.arguments = ["which", name]
        let pipe = Pipe()
        process.standardOutput = pipe
        process.standardError = FileHandle.nullDevice
        do {
            try process.run()
        } catch {
            return nil
        }
        let data = pipe.fileHandleForReading.readDataToEndOfFile()
        // readDataToEndOfFile blocks until the process closes stdout (i.e. exits);
        // waitForExecution is then immediate. Guard against a hang with a deadline.
        let deadline = Date().addingTimeInterval(5)
        while process.isRunning && Date() < deadline {
            Thread.sleep(forTimeInterval: 0.05)
        }
        process.waitUntilExit()
        guard process.terminationStatus == 0 else { return nil }
        let out = String(data: data, encoding: .utf8)?
            .trimmingCharacters(in: .whitespacesAndNewlines)
        return (out?.isEmpty == false) ? out : nil
    }

    /// True if the file at `s` exists and is executable.
    static func pathExists(executableAt s: String) -> Bool {
        let expanded = (s as NSString).expandingTildeInPath
        return FileManager.default.isExecutableFile(atPath: expanded)
    }
}
