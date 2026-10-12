# Task 2 — mic capture + AEC → mic.wav (STATUS: done — lead finished worker's work)

- Deliverables: `capture/Sources/mr-capture/MicCapture.swift` (new),
  edits to `capture/Sources/mr-capture/main.swift` (`--no-aec` flag + wiring).
- The local worker wrote the code but left it **non-compiling** (3 errors:
  `setVoiceProcessingEnabled` imported as `throws` not `error:&`; and
  `AVAudioEngine.isNodeConnected` doesn't exist). Lead repaired those, plus:
- **Runtime fix #1:** `engine.connect(mainMixer → output, format: outputFormat)`
  threw `IsFormatSampleRateAndChannelCountValid` (output format invalid pre-start).
  Reconnect then failed `engine.start` with `kAudioUnitErr_FailedInitialization (-10875)`.
  **Working recipe:** connect `mainMixer → output` using the **input node's format**
  (`input.inputFormat(forBus: 0)`), VP enabled before start. Stable across AEC on/off.
- Live self-test (lead, ~13 s, pings + `say` speech on laptop speakers):
  - AEC on: `mic: MacBook Pro Microphone @ 48000 x9ch`, mic.wav 13.3 s peak 0.286
    (channel 0 = user voice; VP produces an odd 9-channel format — always take ch 0).
  - AEC off (`--no-aec`): mic @ 48000 x1ch, mic.wav 9.8 s peak 0.052.
  - system tap in both: valid 16 kHz mono; Ctrl-C → clean exit 0, both WAVs finalized.
- No mic TCC prompt observed running from the DSH host process.
- NOTE for echo analysis: with AEC on, `say`/`afplay` audio is still present in the
  mic (peak 0.286) — the VPIO reference is the device's own output, so whether it
  cancels *another app's* played audio must be judged on a real call (Task 9 human
  step); echo_check.py is the safety net.