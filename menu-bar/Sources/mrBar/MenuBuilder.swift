import AppKit

/// Builds the status-item dropdown menu from current state (MB-SW3).
///
/// Pure construction — no process spawning, no file reads; `StatusItemController`
/// gathers the state and calls `rebuild`. All items target the controller via
/// target/action; disabled rows have no action at all.
final class MenuBuilder {
    /// Tag for the "Check Active Transcriptions…" item (MB-DISPLAY/D2) so the
    /// controller can retitle it in place without rebuilding the menu.
    static let checkTranscriptionsTag = 707

    /// Tag for the "Start Recording from Calendar…" top-level item (CAL-L2) so
    /// the controller can find/retitle/repopulate its submenu in place.
    static let calendarMenuTag: Int = 708

    /// Display text for the "Check Active Transcriptions…" result (MB-DISPLAY/D3).
    /// `nil` (no in-flight transcription) -> "None"; a stamp -> "<stamp> — transcribing…".
    static func transcriptionResultText(stamp: String?) -> String {
        stamp.map { "\($0) — transcribing…" } ?? "None (no active transcription)"
    }

    /// Short single-line label for one calendar event (CAL-L2):
    /// `"<HH:MM> <title>"` (24-hour local time) when the event has a start
    /// date, just `"<title>"` otherwise. The title is truncated to ~28
    /// characters so a row stays tidy (~40 chars total).
    static func calendarRowTitle(of event: MeetingEvent, now: Date = Date()) -> String {
        let title: String
        if event.title.count > 28 {
            title = String(event.title.prefix(27)) + "…"
        } else {
            title = event.title
        }
        guard let start = event.start else { return title }
        let formatter = DateFormatter()
        formatter.dateFormat = "HH:mm"
        return formatter.string(from: start) + " " + title
    }

    /// Pure list→menu builder for the "Start Recording from Calendar" submenu
    /// (CAL-L2). No calendar/permission/process code — just rows.
    ///
    /// - `events`: the upcoming meeting events (already sorted by the caller).
    /// - `now`: current time (reserved for relative display; rows use absolute
    ///   `HH:mm` today).
    /// - `isEnabled`: applied to every event row (e.g. `isCLIAvailable`).
    /// - `target`: action target for the event rows (`nil` until CAL-L3 wires
    ///   `StatusItemController.startRecordingFromCalendar(_:)`).
    static func buildCalendarSubmenu(
        _ events: [MeetingEvent],
        _ now: Date = Date(),
        isEnabled: Bool,
        target: AnyObject? = nil
    ) -> NSMenu {
        let submenu = NSMenu(title: "Start Recording from Calendar")
        submenu.autoenablesItems = false

        if events.isEmpty {
            let empty = NSMenuItem(title: "No upcoming events", action: nil, keyEquivalent: "")
            empty.isEnabled = false
            submenu.addItem(empty)
            return submenu
        }

        // Thin disabled header so the submenu doesn't look bare.
        let header = NSMenuItem(title: "Start Recording from Calendar", action: nil, keyEquivalent: "")
        header.isEnabled = false
        submenu.addItem(header)

        for (index, event) in events.enumerated() {
            let item = NSMenuItem(
                title: calendarRowTitle(of: event, now: now),
                action: nil, // CAL-L3 wires this action: #selector(StatusItemController.startRecordingFromCalendar(_:))
                keyEquivalent: ""
            )
            item.tag = index
            item.target = target
            item.isEnabled = isEnabled
            submenu.addItem(item)
        }
        return submenu
    }

    /// The retained menu. Popped up on button click via `NSMenu.popUp` (kept
    /// alive by the controller's strong reference).
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
    /// - `status`: the locally-tracked live state (the all-nil idle default
    ///   when not recording).
    /// - `isCLIAvailable`: `AppInfo.resolveMrInvocation() != nil` (resolved
    ///   once at app launch).
    /// - `calendarEvents`: upcoming meeting events for the
    ///   "Start Recording from Calendar…" submenu (CAL-L2); defaults to `[]`
    ///   so existing `rebuild(status:, isCLIAvailable:)` callers compile
    ///   unchanged.
    func rebuild(status: MRStatus, isCLIAvailable: Bool, calendarEvents: [MeetingEvent] = []) {
        menu.removeAllItems()

        // Row 1: inert status label (no action, disabled).
        menu.addItem(disabledItem(statusHeader(status)))

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

        // On-demand transcription status (MB-DISPLAY/D2): the user explicitly
        // asks for it; the controller does the CLI/heartbeat work off the main
        // thread.
        menu.addItem(.separator())
        let checkTranscriptions = NSMenuItem(
            title: "Check Active Transcriptions…",
            action: #selector(StatusItemController.checkActiveTranscriptions(_:)),
            keyEquivalent: ""
        )
        checkTranscriptions.tag = Self.checkTranscriptionsTag
        checkTranscriptions.target = target
        checkTranscriptions.isEnabled = isCLIAvailable
        menu.addItem(checkTranscriptions)

        // Calendar quick-start (CAL-L2): pure construction; the caller supplies
        // `calendarEvents` (fetched off-main in CAL-L3). Tag lets the
        // controller find/repopulate this item in place.
        let calendarItem = NSMenuItem(title: "Start Recording from Calendar…", action: nil, keyEquivalent: "")
        calendarItem.tag = Self.calendarMenuTag
        calendarItem.isEnabled = isCLIAvailable
        calendarItem.submenu = Self.buildCalendarSubmenu(
            calendarEvents,
            isEnabled: isCLIAvailable,
            target: target
        )
        menu.addItem(calendarItem)

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
