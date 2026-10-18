import Foundation

/// Reader for the Python-written transcription heartbeat
/// (`<out_root>/.state/transcribing.json`, see `mr/heartbeat.py`).
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
        // Schema version must match `mr.heartbeat.HEARTBEAT_VERSION` (1).
        guard obj["version"] as? Int == 1 else { return nil }
        guard let stamp = obj["stamp"] as? String else { return nil }
        guard let startedAt = obj["started_at"] as? String else { return nil }

        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        var started = formatter.date(from: startedAt)
        if started == nil {
            formatter.formatOptions = [.withInternetDateTime]
            started = formatter.date(from: startedAt)
        }
        // Fallback for a NAIVE local timestamp (no zone) — e.g. a heartbeat
        // written before the Python side standardized on UTC-"Z". Interpret it
        // as wall-clock local time. This keeps the reader robust across either
        // form.
        if started == nil {
            started = TranscriptionState.parseNaiveLocalISO8601(startedAt)
        }
        guard let s = started else { return nil }

        let age = Date().timeIntervalSince(s)
        guard age <= maxAgeSeconds else { return nil }
        return Heartbeat(stamp: stamp, startedAt: s)
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
