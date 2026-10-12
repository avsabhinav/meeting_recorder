import AppKit

/// Owns the `NSStatusItem` and drives all UI state (MB-SW3).
///
/// - Icon: `mic.fill` template image — grayscale when idle, tinted
///   `systemRed` while live (no custom assets; SF symbols only).
/// - Refresh is **lazy**: `NSMenuDelegate.menuWillOpen` rebuilds the menu and
///   icon from `mr status` + the transcription heartbeat. No timers/polling.
/// - Start is a quick synchronous CLI call; Stop is dispatched to a background
///   queue (it blocks 1–3 min transcribing) and the icon flips to idle
///   **immediately**, per the brief.
///
/// The controller only shells out to `mr` via `MRCLI` — it never spawns
/// `mr-capture` and never touches the pidfile/heartbeat files (read-only).
final class StatusItemController: NSObject, NSMenuDelegate {
    let statusItem: NSStatusItem
    let menuBuilder: MenuBuilder

    /// v1.1 base for the transcription heartbeat: the CLI does not yet expose
    /// the current `out_root` when idle, so default to `~/Meetings`
    /// (the `mr` default). The Transcribing section reflects that default root.
    private var transcriptionBase: URL {
        URL(fileURLWithPath: ("~/Meetings" as NSString).expandingTildeInPath)
    }

    private var isLiveRecording = false

    override init() {
        self.statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        self.menuBuilder = MenuBuilder()
        super.init()
        self.menuBuilder.target = self

        menuBuilder.menu.delegate = self
        statusItem.menu = menuBuilder.menu
        setLive(false)
    }

    // MARK: - Icon

    /// Sets the status-item icon to idle (grayscale) or live (red mic).
    private func setLive(_ live: Bool) {
        isLiveRecording = live
        guard let button = statusItem.button else { return }
        button.image = NSImage(
            systemSymbolName: "mic.fill",
            accessibilityDescription: live ? "Recording" : "Idle"
        )
        button.contentTintColor = live ? .systemRed : nil
        button.needsDisplay = true
    }

    // MARK: - Lazy refresh (main thread)

    /// Rebuilds icon + menu from current state. Called on menu open (and after
    /// start/stop) — never on a timer. `mr status` is one cheap process spawn,
    /// acceptable here per the brief's lazy model.
    func refresh() {
        let cliAvailable = AppInfo.resolveMrInvocation() != nil

        var recording = false
        if cliAvailable {
            let cli = MRCLI()
            do {
                let (out, _) = try cli.status()
                recording = MRStatus.parse(out).recording
            } catch {
                // e.g. processTimeout: show idle rather than a bogus live icon.
                recording = false
            }
        }

        // Heartbeat reader returns a single active entry (or nil if stale).
        let transcribing = TranscriptionState(baseURL: transcriptionBase)
            .activeHeartbeat()
            .map { [$0] } ?? []

        setLive(recording)
        let status = MRStatus(recording: recording, pid: nil, stamp: nil, startedAt: nil)
        menuBuilder.rebuild(status: status, isCLIAvailable: cliAvailable, transcribing: transcribing)
        statusItem.button?.needsDisplay = true
    }

    // MARK: - NSMenuDelegate

    /// Lazy refresh trigger: fires on the main thread each time the dropdown
    /// opens. Rebuilding inside `menuWillOpen` is the sanctioned pattern.
    func menuWillOpen(_ menu: NSMenu) {
        refresh()
    }

    // MARK: - Actions (target of the menu items)

    /// "Start Recording" → `mr start`. Exit 0 (incl. "already recording") means
    /// live. Runs synchronously — it is a quick daemon-spawn, not the blocking
    /// transcription path.
    @objc func startRecording(_ sender: Any?) {
        do {
            let (_, exit) = try MRCLI().start()
            if exit == 0 {
                setLive(true)
            }
        } catch {
            // mr unavailable or timed out: state self-corrects on next open.
        }
        statusItem.button?.needsDisplay = true
    }

    /// "Stop Recording & Transcribe" → `mr stop` on a background queue.
    /// The icon flips to idle **immediately**; transcription (1–3 min) runs
    /// without blocking the menu bar. A later status read returns
    /// "recording: no", so idle stays correct.
    @objc func stopRecording(_ sender: Any?) {
        setLive(false)
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            // Fresh MRCLI inside the closure: no shared-state races with the
            // main thread (invocation is re-resolved; that is fine).
            _ = try? MRCLI().stop()
            guard let self else { return }
            DispatchQueue.main.async {
                self.statusItem.button?.needsDisplay = true
            }
        }
    }

    /// "Quit" → terminate the app.
    @objc func quit(_ sender: Any?) {
        NSApp.terminate(nil)
    }
}
