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

    /// Base for the transcription heartbeat: the current resolved `out_root`
    /// from `mr config get out_root` (MB-SW4), falling back to `~/Meetings`
    /// (the `mr` default) when the CLI is unavailable or errors. Computed
    /// (not stored) so every `refresh()` — i.e. every menu open — re-queries
    /// the CLI, and a storage-location change is picked up on the next open.
    private var transcriptionBase: URL {
        if let root = StorageLocation.currentRoot() {
            return URL(fileURLWithPath: root)
        }
        return URL(fileURLWithPath: ("~/Meetings" as NSString).expandingTildeInPath)
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

    // MARK: - Storage location (MB-SW4)

    /// "Change Storage Location…" → `NSOpenPanel` (directories only) →
    /// `mr config set out_root <dir>`.
    ///
    /// A menu-bar app has no window to sheet the panel onto, so `begin`
    /// (non-blocking) is used instead of `runModal` — the completion handler
    /// runs on the main thread, which is where the `NSAlert` confirmation must
    /// show.
    @objc func changeStorageLocation(_ sender: Any?) {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.allowsMultipleSelection = false
        panel.title = "Choose Storage Location"
        panel.message = "New recordings & transcripts will go here. Existing files are NOT moved."
        panel.prompt = "Choose"
        panel.begin { [weak self] response in
            guard response == .OK, let url = panel.url else { return }
            self?.changeRoot(url.path)
        }
    }

    /// Applies the chosen root via `mr config set out_root` (the app never
    /// writes config itself), then confirms or reports the CLI's error.
    /// Always called on the main thread.
    private func changeRoot(_ newRoot: String) {
        let result: (out: String, exit: Int32)
        do {
            result = try MRCLI().setOutRoot(newRoot)
        } catch {
            // `mr` unavailable or the process timed out (not a bad path).
            let alert = NSAlert()
            alert.alertStyle = .warning
            alert.messageText = "Could not change storage location"
            alert.informativeText = "The mr CLI is unavailable or did not respond."
            alert.runModal()
            return
        }

        let alert = NSAlert()
        if result.exit == 0 {
            alert.alertStyle = .informational
            alert.messageText = "Storage location updated."
            alert.informativeText =
                "Recordings and transcripts for NEW sessions go to:\n\(result.out)\n" +
                "Existing files were not moved."
        } else {
            alert.alertStyle = .warning
            alert.messageText = "Could not set storage location"
            alert.informativeText = result.out.isEmpty ? "mr config set out_root failed." : result.out
        }
        alert.runModal()

        // Reflect the new root in the Transcribing section + folder-open paths.
        refresh()
    }

    // MARK: - Folder open (MB-SW4)

    /// "Open Folder ▸ Recordings" → open `<root>/recordings` in Finder.
    @objc func openRecordingsFolder(_ sender: Any?) {
        openSubfolder("recordings")
    }

    /// "Open Folder ▸ Transcripts" → open `<root>/transcripts` in Finder.
    @objc func openTranscriptsFolder(_ sender: Any?) {
        openSubfolder("transcripts")
    }

    /// Opens a subfolder of the current `out_root` (resolved via
    /// `mr config get out_root`). If the subfolder does not exist yet but the
    /// root does, open the root; if neither exists, tell the user the folder
    /// is created on first use.
    private func openSubfolder(_ sub: String) {
        guard let root = StorageLocation.currentRoot() else {
            let alert = NSAlert()
            alert.alertStyle = .warning
            alert.messageText = "Cannot open folder"
            alert.informativeText =
                "The mr CLI is unavailable, so the current storage location is unknown."
            alert.runModal()
            return
        }

        let dir = root + "/" + sub
        if FileManager.default.fileExists(atPath: dir) {
            _ = NSWorkspace.shared.openFile(dir)
        } else if FileManager.default.fileExists(atPath: root) {
            // Subfolder not created yet (no sessions recorded at this root).
            _ = NSWorkspace.shared.openFile(root)
        } else {
            let alert = NSAlert()
            alert.alertStyle = .informational
            alert.messageText = "Folder does not exist yet"
            alert.informativeText = "It is created on first use."
            alert.runModal()
        }
    }

    /// "Quit" → terminate the app.
    @objc func quit(_ sender: Any?) {
        NSApp.terminate(nil)
    }
}
