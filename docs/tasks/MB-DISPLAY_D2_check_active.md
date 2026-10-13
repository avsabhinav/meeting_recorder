TASK: MB-DISPLAY/D2 Add a lazy "Check Active Transcriptions…" menu item with an async, non-blocking status lookup
GOAL: The dropdown gets an explicit **"Check Active Transcriptions…"** item. When the user clicks it, the item's title changes to **"Searching…"**, then updates to the active transcription's stamp (e.g. `2026-01-15_1030 — transcribing…`) or **"None (no active transcription)"** — all CLI/heartbeat work done **off the main thread** so the menu and app never block. The lookup also syncs the controller's live-recording state.
CONTEXT: `mrBar` is a macOS menu-bar app (Swift/AppKit) that shells out to the `mr` CLI. Task D1 removed the eager `mr status` + heartbeat from the menu-open path (no subprocess on open) and removed the always-rendered "Transcribing:" section. This task adds back the transcription-status feature as an explicit on-demand item, exactly as the user requested ("move the status to a sub option ... call it check active transcriptions ... show searching... and then return the name or none"). The pieces you need already exist: `MRCLI.status()` → stdout + exit; `MRStatus.parse(_:)` → `MRStatus(recording:)`; `TranscriptionState(baseURL:).activeHeartbeat()` → `Heartbeat?` (`.stamp` when non-nil, nil when not transcribing); and `transcriptionBase` (a computed var on the controller) returns the current `out_root`. Your working directory is the repo root.
FILES (create/modify ONLY these): menu-bar/Sources/mrBar/MenuBuilder.swift, menu-bar/Sources/mrBar/StatusItemController.swift
READ FIRST:
- menu-bar/Sources/mrBar/MenuBuilder.swift (134 lines; after D1) — `rebuild(status:isCLIAvailable:)`. Add the new item near the Start/Stop rows / storage group.
- menu-bar/Sources/mrBar/StatusItemController.swift (after D1) — read `refresh()`, `setLive`, `startRecording`, `transcriptionBase`, `isLiveRecording`, and the existing `@objc` action pattern.
STEPS:
1. `MenuBuilder.swift`:
   - Add near the top of the class: `static let checkTranscriptionsTag = 707`.
   - In `rebuild(status:isCLIAvailable:)`, after the Start/Stop items and the `if !isCLIAvailable` error row, add a separator, then a `NSMenuItem` titled "Check Active Transcriptions…" with `tag = Self.checkTranscriptionsTag`, `action = #selector(StatusItemController.checkActiveTranscriptions(_:))`, `target = target`, and `isEnabled = isCLIAvailable`. (When the CLI is unavailable, the item should still appear but disabled — mirroring how Start/Stop render. Put it BEFORE the existing storage separator so the groups read: Start/Stop · Check Active Transcriptions… · Change Storage Location… · Open Folder … )
2. `StatusItemController.swift` — add an action method:
```swift
    /// "Check Active Transcriptions…" → on-demand, OFF the main thread. Flips the
    /// item label to "Searching…", queries `mr status` + the heartbeat, then
    /// updates the row to the active stamp (or "None") and syncs live state.
    @objc func checkActiveTranscriptions(_ sender: Any?) {
        let tag = MenuBuilder.checkTranscriptionsTag
        menuBuilder.menu.item(withTag: tag)?.title = "Searching…"
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            guard let self else { return }
            var recording = false
            let cli = MRCLI()
            if let (out, exit) = try? cli.status(), exit == 0 {
                recording = MRStatus.parse(out).recording
            }
            // Report the in-flight transcription (fresh heartbeat) if any; else "None".
            let base = self.transcriptionBase
            let stamp = TranscriptionState(baseURL: base).activeHeartbeat()?.stamp
            DispatchQueue.main.async { [weak self] in
                guard let self else { return }
                self.isLiveRecording = recording
                self.setLive(recording)
                let final = stamp.map { "\($0) — transcribing…" }
                    ?? "None (no active transcription)"
                self.menuBuilder.menu.item(withTag: tag)?.title = final
                self.statusItem.button?.needsDisplay = true
            }
        }
    }
```
   Place it in the "Actions" section near `startRecording`/`stopRecording`.
ACCEPTANCE:
1. `MenuBuilder.rebuild` adds exactly one item whose title is "Check Active Transcriptions…" and whose `action` is `checkActiveTranscriptions(_:)`; the `menu.menuBarHeight` etc. untouched.
2. No main-thread subprocess: in `checkActiveTranscriptions`, the `MRCLI()`/`status()`/`TranscriptionState`/`transcriptionBase` work is all inside the `DispatchQueue.global` closure — NOT on the main thread.
3. It compiles: `cd menu-bar && bash build.sh` exits 0 and prints "==> done:" (print the tail). If build.sh's extras fail, `cd menu-bar && swift build -c release --disable-sandbox` reporting exit 0 is acceptable.
4. `git diff` for these two files shows only the intended additions (no reformatting of untouched lines).
OUT OF SCOPE: changing `refresh()`/D1's non-blocking open path, Start/Stop/storage/folder/quit actions, `MRCLI.swift`, `TranscriptionState.swift`, `AppInfo.swift`, `StorageLocation.swift`, `main.swift`, tests (D3), Python, capture. Do not reformat unrelated lines.
REPORT: reply with STATUS, FILES CHANGED, VERIFICATION (grep for the action + build.sh tail), and NOTES.