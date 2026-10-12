# Task 2 — Mic capture (AVAudioEngine + voice processing) → `mic.wav`

> Throwaway spike. Do only what's described. You are one small agent with a
> fresh context; do not explore the whole repo. When done, ALSO write
> `spike/tasks/02_mic_capture.SUMMARY.md` (short status report) and reply
> REPORT with STATUS / FILES CHANGED / VERIFICATION / NOTES.

## Context (already decided — do not re-research)
- macOS 27.0.1 arm64, Swift 6.4, SwiftPM package at `spike/capture/`
  (target `mr-capture`). **Do not edit `Package.swift`.**
- Existing files you may READ (not modify): under
  `spike/capture/Sources/mr-capture/`:
  - `Wav.swift`: `WavWriter` — thread-safe incremental WAV writer.
    `init(path:String, sampleRate:UInt32=16000) throws`,
    `func append(_ samples:[Int16])`, `func close()`, `var durationSeconds:Double`.
  - `Resample.swift`: `BoxResampler(sourceRate:Double, targetRate:Double=16000)`
    with `func process(_ mono:[Float]) -> [Int16]`. Downmix to mono yourself.
  - `main.swift`: current CLI entry; you will ADD mic wiring to it (read it
    first — it already starts a `SystemTapCapture` writing `system.wav`).
- AEC / voice processing: use `AVAudioEngine` input node
  (`engine.inputNode.setVoiceProcessingEnabled(true, error:)` — throws) or
  by default. VPIO is enabled on `AVAudioIONode`; enable **before** engine
  start; macOS 14+ `voiceProcessingOtherAudioDuckingConfiguration =
  AVAudioVoiceProcessingOtherAudioDuckingConfiguration(enableAdvancedDucking:false,
  duckingLevel: .min)`. Engine must render to the real output device for VPIO
  to work: connect `engine.mainMixerNode → engine.outputNode`, and install a
  tap on `engine.inputNode`.

## Scope — exactly this
Add a `MicCapture` class in a new file `spike/capture/Sources/mr-capture/MicCapture.swift`,
and wire it into `main.swift`:

1. `MicCapture(outPath: String)`; `func start(aec: Bool) throws`:
   - `let engine = AVAudioEngine()`, `let input = engine.inputNode`,
     `let format = input.inputFormat(forBus: 0)`. If `aec`, call
     `try input.setVoiceProcessingEnabled(true)` and
     `input.voiceProcessingOtherAudioDuckingConfiguration = ...(.min)`.
   - Connect `mainMixerNode → outputNode`, then
     `input.installTap(onBus:0, bufferSize:4096, format:format)` block:
     convert each buffer to **mono [Float]** (use channel 0 of
     `buf.floatChannelData`; note: with VOIP `format.channelCount` may be
     2 or 1 — always take channel 0), resample with a `BoxResampler`
     (sourceRate = format.sampleRate), and `writer.append(_samples)`.
   - `engine.prepare()`, `try engine.start()`.
2. `stop()`: `input.removeTap(onBus:0)`, `engine.stop()`, `writer.close()`.
3. Also expose `var nativeSampleRate`/`nativeChannels`/`deviceName` (from
   `input.inputFormat` and any device name you can get — best effort is fine),
   and `latestFirstBufferHostTime: Double?` (approx `CFAbsoluteTimeGetCurrent()`
   of the first audio callback — this approximates host time of first sample
   for `meta.json`; use `mach_absolute_time()` if convenient, else CFAbsoluteTime).
4. `main.swift`: add a `--no-aec` flag. Notes:
   - Read existing args parsing (`--out <dir>`). Add: if `--no-aec` present,
     pass `aec:false`, else `aec:true`. Reject unknown flags with a usage msg.
   - Start mic writer/`MicCapture` **before** `SystemTapCapture` so both
     streams begin near-identical host time.
   - On shutdown (SIGINT/SIGTERM), stop mic **and** system, close **both**
     writers, print durations. Keep it clean and minimal.
   - Write `mic.wav` in the same `--out` dir.

## Non-goals (do NOT do)
- No `meta.json` file (next task).
- No mic pitch/playback, no shortestFlags beyond `--no-aec`, no `--help`.
- Don't touch `Package.swift`, `Wav.swift`, `Resample.swift`, `SystemTap.swift`.
- Don't edit `main.swift` beyond the two justified changes (flag parsing + wire
  the mic and shutdown).

## Build & test
- Always build with `CLANG_MODULE_CACHE_PATH="$TMPDIR/mcache" swift build --disable-sandbox`
  (blocked sandbox-exec/module cache otherwise), e.g.
  `cd spike/capture && CLANG_MODULE_CACHE_PATH="$TMPDIR/mcache" swift build --disable-sandbox`.
- To test quickly: play a tone via `say "test"` or `afplay` while capture runs
  (macOS lets the mic hear speakers). Run the new binary a few seconds with
  `--no-aec`, Ctrl-C, then verify `mic.wav` exists and is non-silent with
  soundfile: `spike/.venv/bin/python -c "import soundfile as sf,numpy as np; x,=sf.read('<mic.wav>'); print(sf._info('<mic.wav>'), np.abs(x).max())"`.
  Expect 16000 Hz mono, peak > ~0.02 when speakers were making sound.
- Note any macOS permission prompt (microphone) and what happened if you saw one.

## Deliverable
- `spike/capture/Sources/mr-capture/MicCapture.swift` (new)
- Edited `spike/capture/Sources/mr-capture/main.swift`
- `spike/tasks/02_mic_capture.SUMMARY.md`
- Nothing else.

## When done
Reply `REPORT:` with STATUS, FILES CHANGED, VERIFICATION (WAV format + peak amp + any permission prompt observed), NOTES.