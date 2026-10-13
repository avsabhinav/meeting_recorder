TASK: MB-DISPLAY/D1 Make the status-dropdown open path non-blocking (no subprocess on menu open) and remove the always-rendered "Transcribing:" section
GOAL: Opening the `mrBar` dropdown must no longer spawn `mr status` or any subprocess on the main thread, and must no longer compute/render the eager "Transcribing:" section — so the menu ALWAYS opens, even while recording. Start/Stop enablement and the live/idle icon derive from the controller's locally-tracked live state.
CONTEXT: `mrBar` is a macOS menu-bar app (Swift/AppKit) that shells out to the `mr` CLI. Currently `StatusItemController.togglePressed` → `refresh()` runs `MRCLI().status()` synchronously on the MAIN thread (which blocks on `readDataToEndOfFile()` in `ProcessRunner.realRun`) and also calls `AppInfo.resolveMrInvocation()` (which itself runs `/usr/bin/env which mr`), then `NSMenu.popUp` runs inside the status-bar button's tracking event. Blocking the main thread mid-track makes the dropdown fail to open — the user hit this while recording. That was the report behind this task. The fix: on menu open, do NOT spawn any process and do NOT read the heartbeat; `refresh()` becomes lightweight. The explicit "Check Active Transcriptions…" item (a later task, D2) will do the CLI/heartbeat query on demand. Below are the two files you may modify.
FILES (create/modify ONLY these): menu-bar/Sources/mrBar/StatusItemController.swift, menu-bar/Sources/mrBar/MenuBuilder.swift
READ FIRST:
- menu-bar/Sources/mrBar/StatusItemController.swift (293 lines) — focus on `init`, `setLive`, the `transcriptionBase` computed var, `refresh()`, `togglePressed`. Do NOT change `startRecording`, `stopRecording`, `changeStorageLocation`, `changeRoot`, `openSubfolder`, `quit`.
- menu-bar/Sources/mrBar/MenuBuilder.swift (134 lines) — focus on `rebuild(...)` and the "Transcribing:" section block and the disabled-item helper.
STEPS:
1. `StatusItemController.swift`:
   a. Add a cached property: `private let cliAvailable: Bool`. In `init`, after `super.init()` and before `setLive(false)`, set `self.cliAvailable = AppInfo.resolveMrInvocation() != nil`. (The app's environment is fixed at launch; resolving once avoids a `/usr/bin/env which mr` subprocess on every menu open.)
   b. Rewrite `refresh()` as follows (NO `MRCLI`/`status()`/`TranscriptionState` here — do NOT create an `MRCLI` and do NOT call `cli.status()` or `activeHeartbeat()` on the open path):
```swift
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
```
   Keep the `transcriptionBase` computed var in place even though it becomes unused right now (the next task D2 reuses it for the on-demand heartbeat check) — do NOT delete it, do NOT reference it in refresh.
2. `MenuBuilder.swift`: change the signature from `func rebuild(status: MRStatus, isCLIAvailable: Bool, transcribing: [TranscriptionState.Heartbeat])` to `func rebuild(status: MRStatus, isCLIAvailable: Bool)`. Delete the "Transcribing:" section block (the `if !transcribing.isEmpty { menu.addItem(disabledItem("Transcribing:")); for heartbeat in transcribing { ... } }`). Update the doc comment near the top if it mentions the transcribing section.
ACCEPTANCE:
1. No subprocess is spawned on the menu-open path: grep `StatusItemController.swift` for `MRCLI(`, `.status()`, `activeHeartbeat`, `resolveMrInvocation` — none may appear inside `refresh()` (resolveMrInvocation may appear only in `init`).
2. It compiles: `cd menu-bar && ./build.sh` exits 0 (print the tail). If `./build.sh` lacks exec permission, use `bash build.sh`.
3. (`cd menu-bar && swift build -c release --disable-sandbox` also acceptable if build.sh's extras fail, but prefer build.sh.)
OUT OF SCOPE: adding the "Check Active Transcriptions…" item (next task), changing start/stop/storage/folder/quit actions, `MRCLI.swift`, `TranscriptionState.swift`, `AppInfo.swift`, `main.swift`, tests, Python, capture. Do not reformat unrelated lines.
REPORT: reply with STATUS, FILES CHANGED, VERIFICATION (the grep result + build.sh tail), and NOTES.