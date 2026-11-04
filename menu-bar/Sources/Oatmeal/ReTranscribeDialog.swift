import AppKit
import Foundation

/// "Re-transcribe…" recording picker (RT epic).
///
/// The list/selection logic is pure and `FileManager`-injectable so it is unit
/// testable without AppKit; `present` is the only part that touches AppKit.
struct ReTranscribeDialog {
    /// `<root>/recordings`.
    static func recordingsDirectory(root: String) -> URL {
        URL(fileURLWithPath: root).appendingPathComponent("recordings")
    }

    /// The stamp a recording directory name denotes, or nil when the name is
    /// not a stamp (so `.DS_Store`, `.state`, `foo`, `2026-10-22` are skipped).
    /// A stamp is `YYYY-MM-DD_HHMM`: 10 chars, digit groups, exactly one `_`.
    static func stamp(fromRecordingDirName name: String) -> String? {
        // YYYY-MM-DD_HHMM (15 chars): digits at every position except `-` (4, 7)
        // and `_` (10). (The doc comment above says "10 chars"; the format, the
        // regex it quotes, and the required test cases all use 15.)
        let c = Array(name)
        guard c.count == 15,
              c[4] == "-", c[7] == "-", c[10] == "_" else { return nil }
        for (i, ch) in c.enumerated() where i != 4 && i != 7 && i != 10 {
            if ch < "0" || ch > "9" { return nil }
        }
        return name
    }

    /// True when `<dir>` holds BOTH `mic.wav` and `system.wav`.
    static func isTranscribable(_ dir: URL, fm: FileManager = .default) -> Bool {
        fm.fileExists(atPath: dir.appendingPathComponent("mic.wav").path)
            && fm.fileExists(atPath: dir.appendingPathComponent("system.wav").path)
    }

    /// Stamps of transcribable recordings, NEWEST FIRST (stamp strings sort
    /// lexicographically because the format is zero-padded).
    static func transcribableStamps(inRecordingsDir dir: URL, fm: FileManager = .default) -> [String] {
        guard let names = try? fm.contentsOfDirectory(atPath: dir.path) else { return [] }
        return names
            .compactMap { stamp(fromRecordingDirName: $0) }
            .filter { isTranscribable(dir.appendingPathComponent($0), fm: fm) }
            .sorted(by: >)
    }

    /// Every candidate stamp (transcribable or not), newest first — the dialog
    /// shows the untranscribable ones disabled instead of hiding them, so the
    /// user learns why a recording cannot be re-run.
    static func candidates(root: String, fm: FileManager = .default) -> [String] {
        let dir = recordingsDirectory(root: root)
        guard let names = try? fm.contentsOfDirectory(atPath: dir.path) else { return [] }
        return names
            .compactMap { stamp(fromRecordingDirName: $0) }
            .sorted(by: >)
    }

    /// `<root>/recordings/<stamp>` — what `mr retranscribe <stamp>` re-reads.
    static func recordingURL(root: String, stamp: String) -> URL {
        recordingsDirectory(root: root).appendingPathComponent(stamp)
    }

    /// Popup row titles, one per candidate: the stamp plus a short suffix —
    /// `" — ready"` when transcribable, `" — audio deleted"` when not.
    static func candidateTitles(root: String, fm: FileManager = .default) -> [String] {
        let dir = recordingsDirectory(root: root)
        return candidates(root: root, fm: fm).map { stamp in
            isTranscribable(dir.appendingPathComponent(stamp), fm: fm)
                ? "\(stamp) — ready"
                : "\(stamp) — audio deleted"
        }
    }

    /// Runs the picker as a modal panel. `onChoose` fires on the main thread
    /// with the chosen stamp ONLY when the user confirms a transcribable row.
    static func present(root: String, onChoose: @escaping (String) -> Void) {
        let stamps = candidates(root: root)
        let titles = candidateTitles(root: root)

        guard !stamps.isEmpty else {
            let alert = NSAlert()
            alert.alertStyle = .informational
            alert.messageText = "No recordings found"
            alert.informativeText =
                "Recordings appear here once a call has been recorded. "
                + "Press Start in the menu bar to record one."
            alert.runModal()
            return
        }

        let alert = NSAlert()
        alert.messageText = "Re-transcribe a recording"
        alert.informativeText = "Pick a recording. Its audio is re-read and the transcript is rewritten."
        alert.addButton(withTitle: "Re-transcribe")
        alert.addButton(withTitle: "Cancel")

        // Accessory: popup (newest first, latest pre-selected) + a hint label
        // that also drives the confirm button's enabled state.
        let accessory = AccessoryView(frame: NSRect(x: 0, y: 0, width: 420, height: 56))
        let popup = NSPopUpButton(frame: NSRect(x: 0, y: 14, width: 420, height: 25), pullsDown: false)
        popup.addItems(withTitles: titles)
        popup.selectItem(at: 0)
        let hint = NSTextField(labelWithString: "Audio is re-read; the existing transcript is overwritten.")
        hint.frame = NSRect(x: 0, y: 0, width: 420, height: 14)
        hint.font = .systemFont(ofSize: 11)
        hint.textColor = .secondaryLabelColor
        accessory.addSubview(popup)
        accessory.addSubview(hint)
        alert.accessoryView = accessory

        let confirmButton = alert.buttons.first(where: { $0.title == "Re-transcribe" })

        func update(for index: Int) {
            let transcribable = isTranscribable(recordingURL(root: root, stamp: stamps[index]))
            confirmButton?.isEnabled = transcribable
            hint.stringValue = transcribable
                ? "Audio is re-read; the existing transcript is overwritten."
                : "This recording has no audio left to re-read."
        }

        // Both the action AND the initial state are set before `runModal`.
        popup.target = accessory
        popup.action = #selector(AccessoryView.popupChanged(_:))
        accessory.hint = hint
        accessory.confirmButton = confirmButton
        accessory.update = { i in update(for: i) }
        update(for: 0)

        // The popup is the window's first responder so a stray double-Return
        // cannot fire an implicit confirm and the field editor's position is
        // predictable.
        alert.window.initialFirstResponder = popup

        // `runModal` must be called on the main thread — this is called from
        // the menu action, which is already on the main thread.
        let response = alert.runModal()
        guard response == .alertFirstButtonReturn else { return }
        let index = popup.indexOfSelectedItem
        guard index >= 0, index < stamps.count else { return }
        onChoose(stamps[index])
    }

}

/// The accessory view, carrying the hint label, confirm button and update
/// closure so the popup's target/action can drive them (the picker's logic
/// lives in statics, which have no per-instance state to hang a target on).
private final class AccessoryView: NSView {
    var hint: NSTextField?
    var confirmButton: NSButton?
    var update: ((Int) -> Void)?

    @objc func popupChanged(_ sender: NSPopUpButton) {
        update?(sender.indexOfSelectedItem)
    }
}
