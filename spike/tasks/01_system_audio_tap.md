# Task 1 — Swift skeleton + system-audio tap → `system.wav`

> You are one engineer on a team doing a throwaway spike. Do **only** what
> this task describes. Do not read `PLAN.md` or `PHASE0_SPIKE.md` beyond what's
> summarized below — this file is self-contained on purpose, to keep your
> context small. If you think you need more context than is given here, stop
> and write that question into your summary instead of guessing.

## Background (already decided — do not re-research)
This is a spike for a macOS meeting recorder. We need to capture **system
audio** (what's playing out of the speakers — the other person's voice in a
call) into a WAV file, using Apple's Core Audio **process tap** API
(macOS 14.2+). A previous research pass already read the real SDK headers and
decided the approach:

- Use `CATapDescription` with
  `initStereoGlobalTapButExcludeProcesses:[ourOwnPID]` — this taps *everything
  except our own process*. Set `privateTap = true`. Leave `muteBehavior` at
  its default (`CATapUnmuted`) so the user's audio keeps playing normally.
- Call `AudioHardwareCreateProcessTap(description, &tapID)` to get an
  `AudioObjectID`. This object ID **is itself a readable input device** — you
  do **not** need to wrap it in a private aggregate device. Read from it
  directly.
- To read it: query the tap's native `AudioStreamBasicDescription` first (so
  your requested format matches — mismatches fail silently), then create an
  `AudioQueueNewInput` and point it at the tap's device (e.g. via
  `AudioQueueSetProperty(kAudioQueueProperty_CurrentDevice, <tap UID>)`, or
  the equivalent mechanism you find works when you implement this — if the
  exact property/mechanism differs from this description once you're in the
  headers, use what actually works and note the discrepancy in your summary).
- Environment: macOS 27.0.1, arm64 (Apple Silicon), Swift 6.4 via
  `/usr/bin/swift`. `xcodebuild` is present. SDK is at
  `/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk` (get the exact path
  with `xcrun --show-sdk-path`).

## Scope — exactly this, nothing more
Build a SwiftPM executable package at `spike/capture/` that:
1. Has a `Package.swift` defining an executable target named `mr-capture`.
2. Parses one command-line flag: `--out <dir>` (a directory path, created if
   it doesn't exist).
3. Creates a system-audio tap as described above, excluding our own process.
4. Writes everything captured from the tap to `<dir>/system.wav` —
   **16 kHz, mono, 16-bit PCM** — written incrementally as data arrives (not
   buffered in memory for the whole run). Resample/downmix from whatever the
   tap's native format is.
5. Runs until **Ctrl‑C (SIGINT)**, then finalizes the WAV file (correct
   header/size) and exits with code 0. A partially-written WAV must still be
   a valid, playable file if the process is killed less cleanly — best effort
   is fine for this task; full crash-safety is not required yet.
6. No `meta.json`, no mic capture, no `--no-aec` flag, no `--help` text
   beyond the one flag. Keep it minimal.

## Explicit non-goals for this task (do NOT do)
- No mic capture / `AVAudioEngine` / voice processing / AEC — that's Task 2.
- No `meta.json` or other metadata file.
- No packaging, tests, CI, or production polish.
- No aggregate device — read the tap directly as described above.
- Don't touch `PLAN.md`, `PHASE0_SPIKE.md`, or `spike/INVESTIGATION.md`.

## How to self-check before you report done
1. `swift build` succeeds with no errors (warnings OK, note any).
2. Run it for ~10 seconds while some audio is actually playing on the Mac
   (e.g. in a separate terminal: `afplay /System/Library/Sounds/Ping.aiff`
   on a loop, or play any system sound/video — pick whatever's easiest).
   Send Ctrl‑C (SIGINT) after ~10s.
3. Confirm `system.wav` was created and is a **valid, non-silent** WAV:
   - Check format with e.g. `afinfo <path>/system.wav` or `soxi` if
     available — should report 16000 Hz, mono/1 channel, duration ~10s
     (±1-2s is fine).
   - Confirm it's not silence: e.g.
     `python3 -c "import wave,audioop; w=wave.open('system.wav'); d=w.readframes(w.getnframes()); print('max amplitude:', audioop.max(d, w.getsampwidth()))"`
     — amplitude should be clearly above 0 (not just a handful of near-zero
     samples) if audio was playing.
4. If you had to grant a macOS permission prompt (microphone or system audio
   recording) to get this working, note exactly what prompt appeared and
   what you clicked.

## Deliverables
- `spike/capture/Package.swift`
- `spike/capture/Sources/mr-capture/main.swift` (or split into a couple files
  if that's cleaner — your call)
- Nothing else under `spike/` — don't create transcribe.py, README.md, etc.
  yet; those are later tasks.

## When you're done
Write a short summary (10–20 lines max) to
`spike/tasks/01_system_audio_tap.SUMMARY.md` covering:
- Did it build? Any deviations from the described approach (e.g. a different
  property/API call than the one named above), and why.
- Result of the self-check: WAV format reported, amplitude value, any
  permission prompts seen.
- Anything that surprised you or that the next task (mic capture + AEC)
  should know about.
- Any blockers, with what you tried, if you got stuck for more than ~30-45
  min on one thing.

Keep the summary short — this is a status report to your lead, not
documentation.
