import AppKit

/// Owns the `NSStatusItem` and drives all UI state (MB-SW3).
///
/// - Icon: a two-state swap — idle shows the `icon-white` template glyph,
///   recording shows the distinct full-color `icon-recording` image (non-template).
///   The OS's separate recording privacy indicator also appears while recording
///   (kept as-is; never hidden).
/// - Refresh is **lazy**: the button-click handler (`togglePressed`) rebuilds
///   the menu and icon from the locally-tracked live state — no subprocess on
///   the open path, no timers/polling.
/// - Start is a quick synchronous CLI call; Stop is dispatched to a background
///   queue (it blocks 1–3 min transcribing) and the icon flips to idle
///   **immediately**, per the brief.
///
/// The controller only shells out to `mr` via `MRCLI` — it never spawns
/// `mr-capture` and never touches the pidfile/heartbeat files (read-only).
final class StatusItemController: NSObject {
    let statusItem: NSStatusItem
    let menuBuilder: MenuBuilder

    /// Base for the transcription heartbeat: the current resolved `out_root`
    /// from `mr config get out_root` (MB-SW4), falling back to `~/Meetings`
    /// (the `mr` default) when the CLI is unavailable or errors. Computed
    /// (not stored) so a storage-location change is picked up on the next use
    /// (the "Check Active Transcriptions…" item in MB-DISPLAY/D2).
    private var transcriptionBase: URL {
        if let root = StorageLocation.currentRoot() {
            return URL(fileURLWithPath: root)
        }
        return URL(fileURLWithPath: ("~/Meetings" as NSString).expandingTildeInPath)
    }

    private var isLiveRecording = false

    /// Events fetched by `startRecordingFromCalendar`, indexed by the row tag
    /// of the dynamic submenu items so selection maps back to the meeting.
    /// Set on the main thread just before the submenu pops; read only there.
    private var pendingMeetingEvents: [MeetingEvent] = []

    /// Whether `mr` can be resolved (fixed at launch; resolving once avoids a
    /// `which mr` subprocess on every menu open).
    private let cliAvailable: Bool

    override init() {
        self.statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        self.menuBuilder = MenuBuilder()
        // Resolving `mr` here (before super.init — required for stored lets)
        // is the app's single `which mr` spawn: the app's environment is fixed
        // at launch, so the result never needs re-resolving.
        self.cliAvailable = AppInfo.resolveMrInvocation() != nil
        super.init()
        self.menuBuilder.target = self

        statusItem.button?.target = self
        statusItem.button?.action = #selector(togglePressed(_:))
        setLive(false)
    }

    // MARK: - Icon

    /// Sets the status-item icon to the state-appropriate glyph.
    /// - Idle: the `icon-white` template image (AppKit tints it to match the
    ///   menu-bar appearance, giving the built-in active/click highlight).
    /// - Recording: the distinct full-color `icon-recording` image, rendered
    ///   non-template so its colors show as drawn. (The OS's separate
    ///   recording privacy indicator also appears; it is kept, never hidden.)
    private func setLive(_ live: Bool) {
        isLiveRecording = live
        guard let button = statusItem.button else { return }
        // Two-state swap: `icon-white` (template) when idle, `icon-recording`
        // (full-color, non-template) while recording. No tint is applied in
        // either state — template rendering tints the idle glyph itself.
        let resourceName = live ? "icon-recording" : "icon-white"
        if let url = Bundle.module.url(forResource: resourceName, withExtension: "png"),
           let image = NSImage(contentsOf: url) {
            image.isTemplate = !live
            image.size = NSSize(width: 18, height: 18)
            button.image = image
        } else {
            button.image = NSImage(
                systemSymbolName: "mic.fill",
                accessibilityDescription: live ? "Recording" : "Idle"
            )
        }
        button.contentTintColor = nil
        button.image?.accessibilityDescription = live ? "Recording" : "Idle"
        button.needsDisplay = true
    }

    // MARK: - Lazy refresh (main thread)

    /// Rebuilds icon + menu from locally-tracked live state. Called on menu
    /// open (and after start/stop) — never on a timer, and never with a
    /// subprocess (see the comment inside).
    func refresh() {
        // No subprocess on the open path: running `mr status` / `which mr` here on
        // the main thread blocked the status-bar tracking event and made the
        // dropdown fail to open while recording. Live state is tracked locally by
        // start/stop; the explicit "Check Active Transcriptions…" item queries the
        // CLI on demand.
        setLive(isLiveRecording)
        let status = MRStatus(recording: isLiveRecording, pid: nil, stamp: nil, startedAt: nil)
        menuBuilder.rebuild(status: status, isCLIAvailable: cliAvailable)
        statusItem.button?.needsDisplay = true
    }

    /// Button click handler — the ONLY way the dropdown opens. Refreshes state,
    /// then pops the menu up explicitly. Because popUp is invoked from a
    /// completed, separate click event, nothing inside the menu can be
    /// auto-activated by the SAME click that opened it (unlike assigning
    /// `.menu` directly, which lets AppKit treat open+click as one gesture).
    @objc func togglePressed(_ sender: Any?) {
        refresh()
        guard let button = statusItem.button else { return }
        menuBuilder.menu.popUp(
            positioning: nil,
            at: NSPoint(x: 0, y: button.bounds.maxY + 4),
            in: button
        )
    }

    // MARK: - Actions (target of the menu items)

    /// "Start Recording" → `mr start` on a background queue. Exit 0 (incl.
    /// "already recording") means live; the item turns red only **after** the
    /// CLI returns, so the menu/open tracking is never blocked by the
    /// subprocess.
    @objc func startRecording(_ sender: Any?) {
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            // Fresh MRCLI inside the closure: no shared-state races with the
            // main thread (invocation is re-resolved; that is fine).
            var failure: (title: String, detail: String)? = nil
            var success = false
            do {
                let (out, exit) = try MRCLI().start()
                if exit == 0 {
                    success = true
                } else {
                    failure = ("Could not start recording",
                               out.isEmpty ? "mr start failed." : "mr start reported: \(out)")
                }
            } catch {
                if let e = error as? MRCLIError {
                    switch e {
                    case .mrUnavailable:
                        failure = ("mr CLI not found",
                                   "Neither a 'mr' command on PATH nor the MR_PYTHON environment " +
                                   "variable is available to this app. Start the app with MR_PYTHON " +
                                   "set, or install mr on PATH.")
                    case .processTimeout:
                        failure = ("mr did not respond",
                                   "The mr CLI did not finish within the timeout.")
                    }
                } else {
                    failure = ("mr CLI not found", "The mr CLI could not be launched.")
                }
            }
            guard let self else { return }
            DispatchQueue.main.async {
                if success {
                    self.setLive(true)
                }
                if let failure {
                    let alert = NSAlert()
                    alert.alertStyle = .warning
                    alert.messageText = failure.title
                    alert.informativeText = failure.detail
                    alert.runModal()
                }
                self.statusItem.button?.needsDisplay = true
            }
        }
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
            var failure: (title: String, detail: String)? = nil
            do {
                let (out, exit) = try MRCLI().stop()
                if exit != 0 {
                    failure = ("Could not stop recording",
                               out.isEmpty ? "mr stop failed." : "mr stop reported: \(out)")
                }
            } catch {
                if let e = error as? MRCLIError {
                    switch e {
                    case .mrUnavailable:
                        failure = ("mr CLI not found",
                                   "Neither a 'mr' command on PATH nor the MR_PYTHON environment " +
                                   "variable is available to this app. Start the app with MR_PYTHON " +
                                   "set, or install mr on PATH.")
                    case .processTimeout:
                        failure = ("mr did not respond",
                                   "The mr CLI did not finish within the timeout.")
                    }
                } else {
                    failure = ("mr CLI not found", "The mr CLI could not be launched.")
                }
            }
            guard let self else { return }
            DispatchQueue.main.async {
                if let failure {
                    let alert = NSAlert()
                    alert.alertStyle = .warning
                    alert.messageText = failure.title
                    alert.informativeText = failure.detail
                    alert.runModal()
                }
                self.statusItem.button?.needsDisplay = true
            }
        }
    }

    /// "Check Active Transcriptions…" → on-demand, OFF the main thread. Flips the
    /// item label to "Searching…", queries `mr status` + the heartbeat, then
    /// updates the row to the active stamp (or "None") and syncs live state.
    @objc func checkActiveTranscriptions(_ sender: Any?) {
        let tag = MenuBuilder.checkTranscriptionsTag
        menuBuilder.menu.item(withTag: tag)?.title = "Searching…"
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            guard let self else { return }
            var recording = false
            let cli = MRCLI()
            if let (out, exit) = try? cli.status(), exit == 0 {
                recording = MRStatus.parse(out).recording
            }
            // Report the in-flight transcription (fresh heartbeat) if any; else "None".
            let base = self.transcriptionBase
            let stamp = TranscriptionState(baseURL: base).activeHeartbeat()?.stamp
            DispatchQueue.main.async { [weak self] in
                guard let self else { return }
                self.isLiveRecording = recording
                self.setLive(recording)
                let final = MenuBuilder.transcriptionResultText(stamp: stamp)
                self.menuBuilder.menu.item(withTag: tag)?.title = final
                self.statusItem.button?.needsDisplay = true
            }
        }
    }

    // MARK: - Calendar quick-start (CAL-L3)

    /// "Start Recording from Calendar…" (top-level item, tag 708). Checks/requests
    /// Calendar access and fetches events in `[now−1h, now+2h]` OFF the main
    /// thread, then pops a dynamic submenu of those events. Permission denied or
    /// no events are surfaced gracefully — the calendar path never blocks a plain
    /// recording.
    @objc func startRecordingFromCalendar(_ sender: Any?) {
        guard let statusItem = statusItem.button else { return }
        let tag = MenuBuilder.calendarMenuTag
        let item = menuBuilder.menu.item(withTag: tag)
        let defaultTitle = item?.title ?? "Start Recording from Calendar…"
        item?.title = "Searching for events…"

        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            guard let self else { return }
            let source = EventListProvider().source
            // The permission request is async; run it in a child Task so the
            // code stays off the main thread while still outside the
            // synchronous global closure. Task inherits this background
            // executor, so `await checkOrRequestAccess` never blocks main.
            Task {
                let access = await checkOrRequestAccess(source)
                let title = defaultTitle
                guard access == .granted else {
                    await MainActor.run { [weak self] in
                        guard let self else { return }
                        self.menuBuilder.menu.item(withTag: tag)?.title = title
                        let alert = NSAlert()
                        alert.alertStyle = .warning
                        alert.messageText = "Calendar access not granted"
                        alert.informativeText =
                            "A calendar meeting is needed to start a recording with context. " +
                            "Grant Calendar access in System Settings ▸ Privacy & Security ▸ Calendars."
                        alert.runModal()
                        self.statusItem.button?.needsDisplay = true
                    }
                    return
                }

                let events = EventListProvider().fetchCalendarEvents()
                await MainActor.run { [weak self] in
                    guard let self else { return }
                    self.menuBuilder.menu.item(withTag: tag)?.title = title
                    self.pendingMeetingEvents = events
                    let sub = MenuBuilder.buildCalendarSubmenu(
                        events,
                        isEnabled: self.cliAvailable,
                        target: self,
                        action: #selector(StatusItemController.startRecordingWithCalendarEvent(_:))
                    )
                    sub.popUp(
                        positioning: nil,
                        at: NSPoint(x: statusItem.bounds.maxX, y: statusItem.bounds.maxY + 4),
                        in: statusItem
                    )
                    self.statusItem.button?.needsDisplay = true
                }
            }
        }
    }

    /// One event row of the dynamic calendar submenu chosen → start a recording
    /// with that meeting attached via `mr start --context-json <tmp>`.
    @objc func startRecordingWithCalendarEvent(_ sender: Any?) {
        let index = (sender as? NSMenuItem)?.tag ?? -1
        guard pendingMeetingEvents.indices.contains(index) else { return }
        let meeting = pendingMeetingEvents[index]

        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            var failure: (title: String, detail: String)? = nil
            var success = false
            let tmpPath = self?.writeContextTempFile(for: meeting)
            do {
                let (out, exit) = try MRCLI().start(withContextJSON: tmpPath)
                if exit == 0 {
                    success = true
                } else {
                    failure = ("Could not start recording",
                               out.isEmpty ? "mr start failed." : "mr start reported: \(out)")
                }
            } catch {
                if let e = error as? MRCLIError {
                    switch e {
                    case .mrUnavailable:
                        failure = ("mr CLI not found",
                                   "Neither a 'mr' command on PATH nor the MR_PYTHON environment " +
                                   "variable is available to this app. Start the app with MR_PYTHON " +
                                   "set, or install mr on PATH.")
                    case .processTimeout:
                        failure = ("mr did not respond",
                                   "The mr CLI did not finish within the timeout.")
                    }
                } else {
                    failure = ("mr CLI not found", "The mr CLI could not be launched.")
                }
            }
            if let tmpPath { try? FileManager.default.removeItem(atPath: tmpPath) }
            guard let self else { return }
            DispatchQueue.main.async {
                if success {
                    self.setLive(true)
                }
                if let failure {
                    let alert = NSAlert()
                    alert.alertStyle = .warning
                    alert.messageText = failure.title
                    alert.informativeText = failure.detail
                    alert.runModal()
                }
                self.statusItem.button?.needsDisplay = true
            }
        }
    }

    /// ISO8601 string for a meeting date ('' when nil), matching the repo's
    /// existing ISO8601DateFormatter convention (see `TranscriptionState`).
    /// `formatOptions` = internet date-time (no fractional seconds).
    private static func iso8601String(for date: Date?) -> String {
        guard let date else { return "" }
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime]
        return formatter.string(from: date)
    }

    /// Writes the `--context-json` payload for a meeting to a uniquely-named
    /// file under the system temp dir and returns its path; nil on any failure.
    /// The caller deletes the file after `mr start` returns.
    private func writeContextTempFile(for meeting: MeetingEvent) -> String? {
        guard
            let json = MRCLI.buildContextJSON(
                title: meeting.title,
                eventID: meeting.id ?? "",
                start: StatusItemController.iso8601String(for: meeting.start),
                end: StatusItemController.iso8601String(for: meeting.end),
                attendees: meeting.attendees,
                notes: meeting.notes ?? ""
            )
        else { return nil }
        let stamp = String(format: "%.0f", Date().timeIntervalSince1970)
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("mr-context-\(stamp)-\(UInt32.random(in: 1..<UInt32.max)).json")
        do {
            try Data(json.utf8).write(to: url, options: .atomic)
            return url.path
        } catch {
            return nil
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
            panel.orderOut(nil)
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
