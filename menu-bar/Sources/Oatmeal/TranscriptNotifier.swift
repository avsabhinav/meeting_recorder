import AppKit
import UserNotifications

/// Watches the transcripts directory and posts a completion notification when
/// a new transcript lands, opening it on click.
///
/// WHY THE APP AND NOT THE WORKER: a notification must be posted by a process
/// with a bundle identity. The detached `mr _transcribe` worker has none, so
/// the `osascript -e 'display notification'` it used to run was owned by the
/// *osascript* process — macOS showed Script Editor's identity instead of
/// Oatmeal's (no branding) and activated that app on click (Xcode, on some
/// machines). `display notification` also has no click-action API to attach a
/// file to. Posting from here fixes all of it: the notification carries
/// Oatmeal's icon and name, and the click opens the transcript.
///
/// Trade-off of this split: nothing is posted while Oatmeal is not running.
/// The transcript still lands on disk — only the notification is missed.
///
/// Read-only: never writes, moves, or deletes anything under `out_root`.
final class TranscriptNotifier {
    /// `userInfo` key holding the transcript path a notification refers to.
    static let transcriptPathKey = "transcriptPath"

    /// Notification-category identifier (lets the delegate recognize ours).
    static let categoryIdentifier = "transcript-ready"

    private var directory: URL
    private var stream: FSEventStreamRef?

    /// Transcript filenames already present when watching started. Only files
    /// appearing *after* that are notified, so launching the app never
    /// re-announces the user's back catalogue.
    private var seen: Set<String> = []

    /// - `directory`: the transcripts dir to watch (`<out_root>/transcripts`).
    init(directory: URL) {
        self.directory = directory
    }

    deinit { stop() }

    /// Requests notification authorization, then begins watching. Fail-soft: a
    /// denied prompt or an unwatchable directory simply means no notifications
    /// — never an error path for the recording pipeline.
    func start() {
        UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound]) { _, _ in
            // Result intentionally ignored: if the user declines, posting is a
            // no-op and everything else keeps working.
        }
        let category = UNNotificationCategory(
            identifier: Self.categoryIdentifier,
            actions: [],
            intentIdentifiers: [],
            options: []
        )
        UNUserNotificationCenter.current().setNotificationCategories([category])

        seen = Self.transcriptFilenames(in: directory)
        startStream()
    }

    /// Stops the event stream. Idempotent.
    func stop() {
        guard let stream else { return }
        FSEventStreamStop(stream)
        FSEventStreamInvalidate(stream)
        FSEventStreamRelease(stream)
        self.stream = nil
    }

    /// Points the watcher at a new transcripts directory (the user changed the
    /// storage location mid-session). Without this the stream stays on the old
    /// path for the rest of the session and notifications silently stop.
    ///
    /// The new directory's existing files are taken as the baseline, so moving
    /// to a root that already holds transcripts does not announce them. Main
    /// thread.
    func retarget(to directory: URL) {
        guard directory != self.directory else { return }
        stop()
        self.directory = directory
        seen = Self.transcriptFilenames(in: directory)
        startStream()
    }

    // MARK: - Watching

    private func startStream() {
        // The directory may not exist until the first transcription finishes;
        // FSEvents watches the path itself, so a later mkdir still reports.
        var context = FSEventStreamContext(
            version: 0,
            info: Unmanaged.passUnretained(self).toOpaque(),
            retain: nil,
            release: nil,
            copyDescription: nil
        )
        let callback: FSEventStreamCallback = { _, info, _, _, _, _ in
            guard let info else { return }
            let notifier = Unmanaged<TranscriptNotifier>.fromOpaque(info).takeUnretainedValue()
            // Coalesced events only say "something here changed"; diff the
            // directory rather than trusting per-event paths.
            notifier.scanForNewTranscripts()
        }
        guard let stream = FSEventStreamCreate(
            kCFAllocatorDefault,
            callback,
            &context,
            [directory.path] as CFArray,
            FSEventStreamEventId(kFSEventStreamEventIdSinceNow),
            1.0,  // coalesce bursts; a transcript write is not time-critical
            FSEventStreamCreateFlags(
                kFSEventStreamCreateFlagFileEvents | kFSEventStreamCreateFlagNoDefer
            )
        ) else { return }
        self.stream = stream
        FSEventStreamSetDispatchQueue(stream, DispatchQueue.main)
        FSEventStreamStart(stream)
    }

    /// Diffs the directory against `seen` and notifies for each new transcript.
    /// Main thread (the stream is dispatched there).
    private func scanForNewTranscripts() {
        let current = Self.transcriptFilenames(in: directory)
        let added = current.subtracting(seen)
        seen = current
        for name in added.sorted() {
            notify(for: directory.appendingPathComponent(name))
        }
    }

    /// Transcript filenames (`*.md`) currently in `directory`; empty when the
    /// directory does not exist yet.
    static func transcriptFilenames(in directory: URL) -> Set<String> {
        let names = (try? FileManager.default.contentsOfDirectory(atPath: directory.path)) ?? []
        return Set(names.filter { $0.hasSuffix(".md") })
    }

    // MARK: - Posting

    /// Title/body for one transcript filename, distinguishing the
    /// `.FAILED.md` marker the worker writes when transcription dies from a
    /// real transcript. Pure (testable): no posting, no file I/O.
    static func notificationText(for filename: String) -> (title: String, body: String) {
        if filename.hasSuffix(".FAILED.md") {
            let stamp = String(filename.dropLast(".FAILED.md".count))
            return (
                "Transcription failed",
                "\(stamp) could not be transcribed — click for details."
            )
        }
        let stamp = String(filename.dropLast(".md".count))
        return ("Transcript ready", "\(stamp) — click to open.")
    }

    private func notify(for url: URL) {
        let (title, body) = Self.notificationText(for: url.lastPathComponent)
        let content = UNMutableNotificationContent()
        content.title = title
        content.body = body
        content.sound = .default
        content.categoryIdentifier = Self.categoryIdentifier
        content.userInfo = [Self.transcriptPathKey: url.path]

        let request = UNNotificationRequest(
            identifier: url.path,  // one notification per transcript
            content: content,
            trigger: nil  // deliver immediately
        )
        UNUserNotificationCenter.current().add(request)
    }
}
