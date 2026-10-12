import Foundation

// mrBar — stub entrypoint (MB-SW1 scaffold). Real menu/GUI comes in later tasks.
// Prints the resolved `mr` CLI invocation and exits 2 (placeholder behavior).

func describe(_ inv: MRInvocation) -> String {
    switch inv {
    case .executable(let p): return "executable: \(p)"
    case .python(let p): return "python: \(p) -m mr.cli"
    }
}

if let inv = AppInfo.resolveMrInvocation() {
    print("mrBar: mr CLI resolved as \(describe(inv))")
} else {
    print("mrBar: mr CLI not found (no candidate resolved)")
}
exit(2)
