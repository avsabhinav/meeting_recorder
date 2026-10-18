import Foundation
import EventKit

/// Value type describing one calendar meeting inside the active window.
/// `attendees` are the attendees' display names (nil names dropped).
struct MeetingEvent {
    let id: String?
    let title: String
    let start: Date?
    let end: Date?
    let attendees: [String]
    let notes: String?
}

/// Coarse outcome of checking (and, when possible, requesting) Calendar access.
enum CalendarAccess {
    case notDetermined
    case granted
    case denied
}

/// Pure, EventKit-free input record for the mapping/sorting core. The core
/// operates on this (not on `EKEvent`) so it compiles and is testable without
/// EventKit objects at all.
struct RawEvent {
    var id: String?
    var title: String
    var start: Date?
    var end: Date?
    var attendees: [String]
    var notes: String?

    init(
        id: String? = nil,
        title: String = "",
        start: Date? = nil,
        end: Date? = nil,
        attendees: [String] = [],
        notes: String? = nil
    ) {
        self.id = id
        self.title = title
        self.start = start
        self.end = end
        self.attendees = attendees
        self.notes = notes
    }
}

/// Maps plain `RawEvent` records to `MeetingEvent` values. Pure.
func mapEvents(_ raw: [RawEvent]) -> [MeetingEvent] {
    raw.map {
        MeetingEvent(
            id: $0.id,
            title: $0.title,
            start: $0.start,
            end: $0.end,
            attendees: $0.attendees,
            notes: $0.notes
        )
    }
}

/// Sorts events ascending by start; events with a nil start sort last. Pure.
func sortEvents(_ events: [MeetingEvent]) -> [MeetingEvent] {
    events.sorted { a, b in
        if let aStart = a.start, let bStart = b.start {
            return aStart < bStart
        }
        if a.start == nil && b.start == nil {
            return false
        }
        // Nil start sorts last.
        return a.start != nil
    }
}

/// Keeps only events whose start falls inside `[window.start, window.end]`;
/// events with a nil start are dropped. Pure (redundant with the EventKit
/// predicate, but makes the window contract explicit and testable).
func filterEvents(
    _ events: [MeetingEvent],
    in window: (start: Date, end: Date)
) -> [MeetingEvent] {
    events.filter { event in
        guard let start = event.start else { return false }
        return start >= window.start && start <= window.end
    }
}

/// Injectable seam over EventKit: everything the service needs from
/// `EKEventStore` in one place, so tests can supply a canned source.
/// Mirrors the repo's `ProcessRunner` injection style.
protocol CalendarSource {
    /// Current authorization state, from `EKEventStore.authorizationStatus(for: .event)`.
    func authorizationStatus() -> EKAuthorizationStatus
    /// Async permission request; throws on denial.
    func requestFullAccessToEvents() async throws -> Bool
    /// Events in `[start, end]` across all event calendars.
    func events(start: Date, end: Date) -> [EKEvent]
}

/// Real implementation over `EKEventStore`.
struct EKCalendarSource: CalendarSource {
    private let store: EKEventStore

    init(store: EKEventStore = EKEventStore()) {
        self.store = store
    }

    func authorizationStatus() -> EKAuthorizationStatus {
        EKEventStore.authorizationStatus(for: .event)
    }

    func requestFullAccessToEvents() async throws -> Bool {
        try await store.requestFullAccessToEvents()
    }

    func events(start: Date, end: Date) -> [EKEvent] {
        let predicate = store.predicateForEvents(
            withStart: start,
            end: end,
            calendars: store.calendars(for: .event)
        )
        return store.events(matching: predicate)
    }
}

/// Checks current Calendar access; if not-yet-determined, requests full
/// access once. Returns `.granted`, `.denied`, or `.notDetermined` (the
/// pre-request state, only reachable if the request itself cannot run).
func checkOrRequestAccess(_ source: CalendarSource) async -> CalendarAccess {
    switch source.authorizationStatus() {
    case .fullAccess:
        return .granted
    case .notDetermined:
        if (try? await source.requestFullAccessToEvents()) == true {
            return .granted
        }
        return .denied
    default:
        return .denied
    }
}

/// Builds a `RawEvent` from an `EKEvent`. The stable id prefers
/// `calendar.calendarIdentifier|eventIdentifier`; falls back to the
/// identifier alone, then `nil`.
func rawEvent(from event: EKEvent) -> RawEvent {
    let calendarID = event.calendar.calendarIdentifier
    let id: String?
    if let eventID = event.eventIdentifier {
        id = calendarID.isEmpty ? eventID : "\(calendarID)|\(eventID)"
    } else {
        id = calendarID.isEmpty ? nil : calendarID
    }
    return RawEvent(
        id: id,
        title: event.title ?? "",
        start: event.startDate,
        end: event.endDate,
        attendees: event.attendees?.compactMap { $0.name } ?? [],
        notes: event.notes
    )
}

/// Fetches events in `[now − 1h, now + 2h]`, maps and sorts them.
/// `now` is injectable for determinism.
struct EventListProvider {
    var source: CalendarSource = EKCalendarSource()

    /// Window bounds relative to "now", in seconds.
    static let windowBeforeSeconds: TimeInterval = 3600
    static let windowAfterSeconds: TimeInterval = 7200

    func fetchCalendarEvents(now: Date = Date()) -> [MeetingEvent] {
        let windowStart = now.addingTimeInterval(-Self.windowBeforeSeconds)
        let windowEnd = now.addingTimeInterval(Self.windowAfterSeconds)
        let mapped = mapEvents(source.events(start: windowStart, end: windowEnd).map(rawEvent(from:)))
        return sortEvents(filterEvents(mapped, in: (start: windowStart, end: windowEnd)))
    }
}
