import AppKit

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

    func applicationDidFinishLaunching(_ notification: Notification) {
        controller = StatusItemController()
    }

    // A menu-bar-only app has no windows. Returning `true` here causes the
    // app to QUIT whenever a status-item menu is dismissed by clicking outside.
    // It must stay alive: only "Quit" (NSApp.terminate) should end it.
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        false
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.accessory)
app.run()
