import AppKit

/// Builds the status-item dropdown menu from current state (MB-SW3).
///
/// Pure construction — no process spawning, no file reads; `StatusItemController`
/// gathers the state and calls `rebuild`. All items target the controller via
/// target/action; disabled rows have no action at all.
final class MenuBuilder {
    /// The retained menu. Assign it to `statusItem.menu` (which keeps it alive).
    let menu = NSMenu()

    /// Action target (the `StatusItemController`). Weak + settable so the
    /// controller can assign itself after its own `super.init` (Swift forbids
    /// using `self` before that).
    weak var target: AnyObject?

    init(target: AnyObject? = nil) {
        self.target = target
        // We manage isEnabled per-item ourselves; don't let AppKit second-guess
        // it (auto-enable also disables items whose target doesn't "look" able).
        menu.autoenablesItems = false
    }

    /// Rebuilds `menu` in place for one menu-open.
    ///
    /// - `status`: parsed `mr status` (or the all-nil idle default when the CLI
    ///   is unavailable / errored).
    /// - `isCLIAvailable`: `AppInfo.resolveMrInvocation() != nil`.
    /// - `transcribing`: active transcription heartbeats (usually 0 or 1 — the
    ///   heartbeat file holds a single entry; the reader returns nil for stale).
    func rebuild(status: MRStatus, isCLIAvailable: Bool, transcribing: [TranscriptionState.Heartbeat]) {
        menu.removeAllItems()

        let start = NSMenuItem(
            title: "Start Recording",
            action: #selector(StatusItemController.startRecording(_:)),
            keyEquivalent: ""
        )
        start.target = target
        start.isEnabled = isCLIAvailable && !status.recording
        menu.addItem(start)

        let stop = NSMenuItem(
            title: "Stop Recording & Transcribe",
            action: #selector(StatusItemController.stopRecording(_:)),
            keyEquivalent: ""
        )
        stop.target = target
        stop.isEnabled = isCLIAvailable && status.recording
        menu.addItem(stop)

        if !isCLIAvailable {
            // Explain why Start/Stop above won't work (brief §6 / AppInfo
            // contract).
            menu.addItem(disabledItem("mr CLI not found (set MR_PYTHON)"))
        }

        // "Transcribing:" section — present only while a heartbeat is active.
        if !transcribing.isEmpty {
            menu.addItem(disabledItem("Transcribing:"))
            for heartbeat in transcribing {
                menu.addItem(disabledItem("\(heartbeat.stamp) — transcribing…"))
            }
        }

        // Placeholders only (MB-SW4 replaces these with a real NSOpenPanel +
        // folder-open action). Disabled so the menu is whole but safe.
        menu.addItem(disabledItem("Change Storage Location…"))
        menu.addItem(disabledItem("Open Folder…"))

        menu.addItem(.separator())

        let quit = NSMenuItem(
            title: "Quit",
            action: #selector(StatusItemController.quit(_:)),
            keyEquivalent: "q"
        )
        quit.target = target
        menu.addItem(quit)
    }

    private func disabledItem(_ title: String) -> NSMenuItem {
        let item = NSMenuItem(title: title, action: nil, keyEquivalent: "")
        item.isEnabled = false
        return item
    }
}
