import Foundation

/// Reader for the Python-written transcription heartbeat
/// (`<out_root>/.state/transcribing.json`, see `mr/heartbeat.py`).
///
/// Schema version 2 (the current `mr.heartbeat.HEARTBEAT_VERSION`) adds the
/// owning worker's `pid` to the payload; version 1 predates that field and is
/// treated as stale.
///
/// NOTE: the menu app must point `baseURL` at the current `out_root`
/// (`mr config`'s `out_root`, default `~/Meetings`) — the heartbeat is written
/// under whatever `out_root` is in effect, and `mr status` does not print it
/// when idle. MB-SW3 resolves the base (e.g. via `mr config get out_root` or
/// the default) before calling in.
///
/// Pure read-only: a stale or malformed heartbeat is treated as absent but
/// never deleted (mirrors `mr.heartbeat.read_transcribing_heartbeat`).
struct TranscriptionState {
    /// JSON shape of `transcribing.json` (Python-truth).
    struct Heartbeat {
        let stamp: String
        let startedAt: Date?
        /// Owning worker PID (heartbeat v2). `nil` when the writer omitted it;
        /// `mr stop-transcribe` needs it to signal exactly that process.
        let pid: Int?
    }

    /// Base directory under which `.state/transcribing.json` lives (the
    /// current `out_root`).
    let baseURL: URL

    init(baseURL: URL) { self.baseURL = baseURL }

    /// Returns a fresh heartbeat, or nil if absent/stale/invalid.
    /// `maxAgeSeconds` defaults to 300. Stale/malformed => nil (never deletes).
    func activeHeartbeat(maxAgeSeconds: TimeInterval = 300) -> Heartbeat? {
        let path = baseURL.appendingPathComponent(".state").appendingPathComponent("transcribing.json")
        guard let data = try? Data(contentsOf: path) else { return nil }
        guard let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            return nil
        }
        // Schema version must match `mr.heartbeat.HEARTBEAT_VERSION` (now 2).
        // Version 1 predates the `pid` field and is treated as stale.
        guard obj["version"] as? Int == 2 else { return nil }
        guard let stamp = obj["stamp"] as? String else { return nil }
        guard let startedAt = obj["started_at"] as? String else { return nil }
        guard let s = TranscriptionState.parseTimestamp(startedAt) else { return nil }

        // Liveness: the worker refreshes `updated_at` every ~30 s, so a long
        // transcription is not reported idle after `maxAgeSeconds`. Older
        // heartbeats without it fall back to `started_at` (mirrors
        // `mr.heartbeat.read_transcribing_heartbeat`).
        var liveAt = s
        if let updatedAt = obj["updated_at"] as? String {
            guard let u = TranscriptionState.parseTimestamp(updatedAt) else { return nil }
            liveAt = u
        }
        let age = Date().timeIntervalSince(liveAt)
        guard age <= maxAgeSeconds else { return nil }
        // v2: owning worker PID. Present-and-an-integer yields it; missing,
        // explicit null, or a non-integer (string/float/bool) yields nil.
        // Never rejects the heartbeat on its own.
        let pid = obj["pid"] as? Int
        return Heartbeat(stamp: stamp, startedAt: s, pid: pid)
    }

    /// Parse an ISO8601 timestamp: with a zone (fractional seconds optional),
    /// else a NAIVE local timestamp — e.g. a heartbeat written before the
    /// Python side standardized on UTC-"Z" — read as wall-clock local time.
    static func parseTimestamp(_ s: String) -> Date? {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let d = formatter.date(from: s) { return d }
        formatter.formatOptions = [.withInternetDateTime]
        if let d = formatter.date(from: s) { return d }
        return parseNaiveLocalISO8601(s)
    }

    /// Parse a timezone-less local timestamp like `2026-10-12T16:45:57` or
    /// `2026-10-12T16:45:57.769888` as wall-clock local time. Returns nil if it
    /// can't be read.
    private static func parseNaiveLocalISO8601(_ s: String) -> Date? {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = TimeZone.current
        let fractionPatterns = [
            "yyyy-MM-dd'T'HH:mm:ss.SSSSSS", // 6-digit
            "yyyy-MM-dd'T'HH:mm:ss.SSS",    // 3-digit
            "yyyy-MM-dd'T'HH:mm:ss",        // no fraction
        ]
        for pattern in fractionPatterns {
            formatter.dateFormat = pattern
            if let d = formatter.date(from: s) { return d }
        }
        return nil
    }
}
