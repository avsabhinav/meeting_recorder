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

        // MB-SW10: first row is ENABLED but harmless. A single icon click opens the
        // menu and macOS auto-activates the first ENABLED actionable item (it skips
        // disabled rows), so this row — not "Start Recording" — absorbs the accidental
        // activation. Its action is a no-op.
        let header = NSMenuItem(
            title: statusHeader(status),
            action: #selector(StatusItemController.statusHeaderClicked(_:)),
            keyEquivalent: ""
        )
        header.target = target
        header.isEnabled = true
        menu.addItem(header)

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

        // Storage location + folder access (MB-SW4): real actions. Both need
        // the CLI (the app never reads/writes config itself), so they are
        // enabled only when `mr` resolves.
        menu.addItem(.separator())

        let changeRoot = NSMenuItem(
            title: "Change Storage Location…",
            action: #selector(StatusItemController.changeStorageLocation(_:)),
            keyEquivalent: ""
        )
        changeRoot.target = target
        changeRoot.isEnabled = isCLIAvailable
        menu.addItem(changeRoot)

        // "Open Folder" submenu with Recordings / Transcripts (chosen over two
        // flat top-level items to keep the menu tidy; the brief only requires
        // the capability).
        let openFolder = NSMenuItem(title: "Open Folder", action: nil, keyEquivalent: "")
        openFolder.isEnabled = isCLIAvailable
        let openMenu = NSMenu(title: "Open Folder")
        openMenu.autoenablesItems = false

        let openRecordings = NSMenuItem(
            title: "Recordings",
            action: #selector(StatusItemController.openRecordingsFolder(_:)),
            keyEquivalent: ""
        )
        openRecordings.target = target
        openRecordings.isEnabled = isCLIAvailable
        openMenu.addItem(openRecordings)

        let openTranscripts = NSMenuItem(
            title: "Transcripts",
            action: #selector(StatusItemController.openTranscriptsFolder(_:)),
            keyEquivalent: ""
        )
        openTranscripts.target = target
        openTranscripts.isEnabled = isCLIAvailable
        openMenu.addItem(openTranscripts)

        openFolder.submenu = openMenu
        menu.addItem(openFolder)

        menu.addItem(.separator())

        let quit = NSMenuItem(
            title: "Quit",
            action: #selector(StatusItemController.quit(_:)),
            keyEquivalent: "q"
        )
        quit.target = target
        menu.addItem(quit)
    }

    /// Plain-text status shown in the inert top row (MB-SW7).
    private func statusHeader(_ status: MRStatus) -> String {
        status.recording ? "(recording)" : "(idle)"
    }

    private func disabledItem(_ title: String) -> NSMenuItem {
        let item = NSMenuItem(title: title, action: nil, keyEquivalent: "")
        item.isEnabled = false
        return item
    }
}
