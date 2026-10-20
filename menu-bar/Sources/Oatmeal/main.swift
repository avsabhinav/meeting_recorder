import AppKit
import UserNotifications

// Oatmeal — macOS menu-bar app entrypoint (MB-SW3).
//
// A pure shell around the `mr` CLI: an NSStatusItem + dropdown. No dock icon
// (`.accessory` activation policy — the canonical menu-bar-app mode; a future
// Info.plist may add LSUIElement as well), no windows.

/// Retains the status-item controller (a strong reference is required — the
/// delegate is retained by `NSApplication`, so this keeps it alive for the app
/// lifetime).
final class AppDelegate: NSObject, NSApplicationDelegate {
    private var controller: StatusItemController?

    /// Watches the transcripts dir and posts the "transcript ready"
    /// notification (see `TranscriptNotifier` for why the app posts it rather
    /// than the detached Python worker).
    private var notifier: TranscriptNotifier?

    func applicationDidFinishLaunching(_ notification: Notification) {
        controller = StatusItemController()

        // Install the delegate BEFORE anything can be delivered: a click on a
        // notification posted by a previous launch is handed over during
        // startup and is dropped if no delegate is set yet.
        UNUserNotificationCenter.current().delegate = self

        // Follow a mid-session storage-location change (MB-SW4): the watcher
        // is bound to one directory, so it must be repointed when out_root
        // moves or it watches the old path for the rest of the session.
        NotificationCenter.default.addObserver(
            forName: .oatmealStorageRootChanged,
            object: nil,
            queue: .main
        ) { [weak self] note in
            guard let self, let root = note.object as? String else { return }
            self.notifier?.retarget(
                to: URL(fileURLWithPath: root).appendingPathComponent("transcripts")
            )
        }

        // Resolving out_root shells out to `mr config get out_root`, so keep it
        // off the main thread; the watcher is started back on main.
        DispatchQueue.global(qos: .utility).async { [weak self] in
            let root = StorageLocation.currentRoot()
                ?? ("~/Meetings" as NSString).expandingTildeInPath
            let transcripts = URL(fileURLWithPath: root).appendingPathComponent("transcripts")
            DispatchQueue.main.async {
                guard let self else { return }
                let notifier = TranscriptNotifier(directory: transcripts)
                self.notifier = notifier
                notifier.start()
            }
        }
    }

    // A menu-bar-only app has no windows. Returning `true` here causes the
    // app to QUIT whenever a status-item menu is dismissed by clicking outside.
    // It must stay alive: only "Quit" (NSApp.terminate) should end it.
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        false
    }
}

// MARK: - Notification handling

extension AppDelegate: UNUserNotificationCenterDelegate {
    /// Clicking the notification opens the transcript it refers to — the whole
    /// point of posting from the app. The path travels in `userInfo`; it is
    /// opened only when it still exists (the user may have moved or deleted
    /// it), falling back to the enclosing folder.
    func userNotificationCenter(
        _ center: UNUserNotificationCenter,
        didReceive response: UNNotificationResponse,
        withCompletionHandler completionHandler: @escaping () -> Void
    ) {
        defer { completionHandler() }
        guard response.actionIdentifier == UNNotificationDefaultActionIdentifier else { return }
        let info = response.notification.request.content.userInfo
        guard let path = info[TranscriptNotifier.transcriptPathKey] as? String else { return }

        let url = URL(fileURLWithPath: path)
        if FileManager.default.fileExists(atPath: path) {
            NSWorkspace.shared.open(url)
        } else {
            NSWorkspace.shared.open(url.deletingLastPathComponent())
        }
    }

    /// Show the banner even when Oatmeal is frontmost; macOS otherwise
    /// suppresses notifications from the active app and the user sees nothing.
    func userNotificationCenter(
        _ center: UNUserNotificationCenter,
        willPresent notification: UNNotification,
        withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void
    ) {
        completionHandler([.banner, .sound])
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.accessory)
app.run()
