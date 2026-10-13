TASK: CAP-AUDIO/A1 Remove voice-processing (AEC) from mic capture so recording never degrades a live call
GOAL: `mr-capture` must record the RAW microphone with no AVAudioEngine voice processing (VPIO) and no output-device rendering, so capturing is invisible to an active Teams call. The `--no-aec` flag and all `aec` plumbing are removed; the binary always records a raw 1-channel mic tap.
CONTEXT: This is a local-first macOS meeting recorder. The Swift helper `mr-capture` records a 16 kHz mono mic stream (recorded as `You`) plus a system-audio tap (`Them`, in `SystemTap.swift`, UNTOUCHED by this task). The user found that enabling AVAudioEngine voice processing (the current AEC-on default) grabs the mic+output in "voice chat" mode, which attenuates their near-end voice and ducks the remote participant's audio during an active call. Decision: record raw mic only; echo is handled later by Python-side text dedup. Below are the two files you may modify.

There are exactly two files in scope (everything else is read-only for you):

1) capture/Sources/mr-capture/MicCapture.swift — current relevant code:
```swift
    func start(aec: Bool) throws {
        let input = engine.inputNode
        if aec {
            // Must be set before engine.start(). Imported as `throws`.
            do { try input.setVoiceProcessingEnabled(true) }
            catch { throw CaptureError("setVoiceProcessingEnabled: \(error.localizedDescription)") }
            if #available(macOS 14.0, *) {
                // Keep our own system-audio tap audible at full level.
                input.voiceProcessingOtherAudioDuckingConfiguration =
                    AVAudioVoiceProcessingOtherAudioDuckingConfiguration(enableAdvancedDucking: false,
                                                                          duckingLevel: .min)
            }
            aecEnabled = true
        }

        // Re-read the format after VP setup: channel count may change (1 -> 2).
        let format = input.inputFormat(forBus: 0)
        guard format.sampleRate > 0, format.channelCount > 0 else {
            throw CaptureError("input node has no valid format (no microphone?)")
        }
        nativeSampleRate = format.sampleRate
        nativeChannels = format.channelCount
        if let inID = caGetUInt32(AudioObjectID(kAudioObjectSystemObject),
                                  kAudioHardwarePropertyDefaultInputDevice) {
            deviceName = caGetString(inID, kAudioObjectPropertyName) ?? "unknown"
        }

        // VPIO requires the engine to render to a real output device. Connect at the
        // input's native sample rate so the voice-processing IO unit init succeeds
        // (need both input and output at a matching hardware rate, both set
        // while the engine is stopped).
        engine.connect(engine.mainMixerNode, to: engine.outputNode, format: format)

        resampler = BoxResampler(sourceRate: format.sampleRate)
        input.installTap(onBus: 0, bufferSize: 4096, format: format) { [weak self] buf, _ in
            self?.handle(buf)
        }

        engine.prepare()
        do { try engine.start() } catch {
            input.removeTap(onBus: 0)
            throw CaptureError("engine.start: \(error.localizedDescription)")
        }
        started = true
    }
```
Also in `MicCapture.swift`: `private(set) var aecEnabled = false` is declared near the top; `handle(_:)` reads `buf.floatChannelData`, takes `data.pointee` (channel 0) as `[Float]`, feeds it through `resampler` and `writer`. That tap logic stays identical — with no VPIO the input is already 1 channel and channel 0 is your voice.

2) capture/Sources/mr-capture/main.swift — current relevant code:
```swift
var outArg: String?
var aec = true
var i = 0
while i < args.count {
    let a = args[i]
    if a == "--out" {
        guard i + 1 < args.count else { die("usage: mr-capture --out <dir> [--no-aec]", 2) }
        outArg = (args[i + 1] as NSString).expandingTildeInPath
        i += 2
    } else if a == "--no-aec" {
        aec = false
        i += 1
    } else {
        die("usage: mr-capture --out <dir> [--no-aec]", 2)
    }
}
```
and later:
```swift
let mic: MicCapture
do { mic = try MicCapture(outPath: outDir + "/mic.wav") } catch { die("\(error)") }
do { try mic.start(aec: aec) } catch {
    mic.writer.close()
    die("mic: \(error)")
}
log("mic: \(mic.deviceName) @ \(mic.nativeSampleRate) Hz x\(mic.nativeChannels) (aec=\(mic.aecEnabled))")
```
and in `writeMeta(_:)`: `"aec": mic.aecEnabled,`
FILES (create/modify ONLY these): capture/Sources/mr-capture/MicCapture.swift, capture/Sources/mr-capture/main.swift
READ FIRST:
- capture/Sources/mr-capture/MicCapture.swift (whole file, 110 lines)
- capture/Sources/mr-capture/main.swift (whole file, 117 lines)
STEPS:
1. In `MicCapture.swift`: change `start(aec: Bool)` to `start()` (no parameter). Remove the entire `if aec { ... }` block (the `setVoiceProcessingEnabled`, `voiceProcessingOtherAudioDuckingConfiguration`, and `aecEnabled = true`). Remove the `engine.connect(engine.mainMixerNode, to: engine.outputNode, format: format)` line and its comment (we must NOT start an IO unit on the output device). Keep everything else: reading `input.inputFormat(forBus: 0)`, the guard, setting nativeSampleRate/nativeChannels/deviceName, `resampler = BoxResampler(...)`, `input.installTap(...)`, `engine.prepare()`, `engine.start()` error handling, `started = true`.
2. In `MicCapture.swift`: remove the `private(set) var aecEnabled = false` declaration. Update the class doc comment near the top (the block that mentions "voice processing (AEC)" / "automatic echo cancellation") to a one-paragraph note stating the mic is recorded RAW with no voice processing so capture never degrades a live call, and that echo is handled by downstream text dedup. Update the pipeline comment `// channel 0 = user's voice (mic + reference mix)` to `// channel 0 = user's voice (raw mic)`.
3. In `main.swift`: remove the `--no-aec` case and the `var aec` variable. Update the usage string to `mr-capture --out <dir>`. Change `try mic.start(aec: aec)` to `try mic.start()`. Update the `log("mic: ...")` line to drop `(aec=\(mic.aecEnabled))` (there is nothing to print now). Update the header usage comment at the top (the `// Usage: mr-capture --out <dir> [--no-aec]` line).
4. In `writeMeta` in `main.swift`: replace `"aec": mic.aecEnabled,` with `"aec": false,` (keeps the meta.json schema field stable; the Python reader is unaffected).
DO NOT change resampling, WAV writing, the system tap, signal handling, or shutdown logic.
ACCEPTANCE:
1. No references remain to any of: `aec`, `aecEnabled`, `--no-aec`, `setVoiceProcessingEnabled`, `voiceProcessingOtherAudioDuckingConfiguration`, `mainMixerNode` in either file (case-insensitive grep section-wise). Run: `cd capture && grep -rin "aec" Sources/mr-capture/MicCapture.swift Sources/mr-capture/main.swift` → expect only the `"aec": false` meta key.
2. It compiles cleanly: `cd capture && ./build.sh` exits 0 and prints "==> done:" (if `./build.sh` lacks permission on your host, run `bash build.sh`). Report the exact stdout tail.
OUT OF SCOPE: `SystemTap.swift`, `Wav.swift`, `Resample.swift`, any Python (`mr/`), tests, docs. Do not reformat untouched lines.
REPORT: reply with STATUS, FILES CHANGED, VERIFICATION (the grep result + build.sh tail), and NOTES.