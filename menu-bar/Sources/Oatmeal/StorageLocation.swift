import AppKit

/// Real "Change Storage Location…" handler + current-root helper (MB-SW4).
///
/// The app never writes config/state itself — reading the current `out_root`
/// goes through `mr config get out_root` (via `MRCLI`), and changing it goes
/// through `mr config set out_root` (see `StatusItemController.changeRoot`).
struct StorageLocation {
    /// The current resolved `out_root`, by running `mr config get out_root`.
    /// Returns nil when the CLI is unavailable or errors. Trimmed bare path.
    static func currentRoot(cli: MRCLI = MRCLI()) -> String? {
        guard let (out, exit) = try? cli.configGetOutRoot() else { return nil }
        guard exit == 0 else { return nil }
        let trimmed = out.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? nil : trimmed
    }
}
