import Foundation

// mr-capture — spike: system audio (process tap) + mic (AVAudioEngine, optional AEC) -> 16 kHz mono WAVs.
// Usage: mr-capture --out <dir> [--no-aec]
// Runs until SIGINT/SIGTERM, then finalizes the WAVs and exits 0.

func die(_ msg: String, _ code: Int32 = 1) -> Never {
    FileHandle.standardError.write(Data(("mr-capture: " + msg + "\n").utf8))
    exit(code)
}
func log(_ msg: String) { FileHandle.standardError.write(Data((msg + "\n").utf8)) }

// MARK: - CLI

let args = Array(CommandLine.arguments.dropFirst())
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
guard let outDir = outArg else { die("usage: mr-capture --out <dir> [--no-aec]", 2) }
do {
    try FileManager.default.createDirectory(atPath: outDir, withIntermediateDirectories: true)
} catch { die("cannot create \(outDir): \(error)", 2) }

// MARK: - Start capture

// Mic first (TCC prompt, if any, happens here), then the system tap —
// both start about the same time.
let mic: MicCapture
do { mic = try MicCapture(outPath: outDir + "/mic.wav") } catch { die("\(error)") }
do { try mic.start(aec: aec) } catch {
    mic.writer.close()
    die("mic: \(error)")
}
log("mic: \(mic.deviceName) @ \(mic.nativeSampleRate) Hz x\(mic.nativeChannels) (aec=\(mic.aecEnabled))")

let systemWriter: WavWriter
do { systemWriter = try WavWriter(path: outDir + "/system.wav") } catch { die("\(error)") }
let system = SystemTapCapture(writer: systemWriter)
do { try system.start() } catch { die("system tap: \(error)") }
log("system: \(system.deviceName) @ \(system.nativeSampleRate) Hz x\(system.nativeChannels)")
log("recording to \(outDir) — Ctrl-C to stop")

// MARK: - Stop on SIGINT / SIGTERM

func machToSeconds(_ t: UInt64) -> Double {
    var info = mach_timebase_info_data_t()
    mach_timebase_info(&info)
    return Double(t) * Double(info.numer) / Double(info.denom) / 1_000_000_000.0
}

func writeMeta(_ dir: String) {
    let sw = mic.writer.samplesWritten
    let ow = systemWriter.samplesWritten
    let firstMicHost = mic.firstSampleHostTime                 // mach UInt64
    let firstSysHost = system.firstSampleHostTime              // mach UInt64
    let meta: [String: Any] = [
        "macos_version": ProcessInfo.processInfo.operatingSystemVersionString,
        "aec": mic.aecEnabled,
        "started_at": ISO8601DateFormatter().string(from: Date()),
        "duration_seconds": max(mic.writer.durationSeconds, systemWriter.durationSeconds),
        "mic": [
            "device_name": mic.deviceName,
            "native_sample_rate": mic.nativeSampleRate,
            "native_channels": mic.nativeChannels,
            "first_sample_seconds": (firstMicHost != nil) ? machToSeconds(firstMicHost!) : 0,
            "samples_written": sw,
        ],
        "system": [
            "device_name": system.deviceName,
            "native_sample_rate": system.nativeSampleRate,
            "native_channels": system.nativeChannels,
            "first_sample_seconds": (firstSysHost != nil) ? machToSeconds(firstSysHost!) : 0,
            "samples_written": ow,
        ],
    ]
    let url = URL(fileURLWithPath: dir + "/meta.json")
    guard let data = try? JSONSerialization.data(withJSONObject: meta, options: [.prettyPrinted, .sortedKeys])
    else { return }
    try? data.write(to: url)
}

func shutdown() -> Never {
    log("stopping…")
    mic.stop()
    mic.writer.close()
    system.stop()
    systemWriter.close()
    writeMeta(outDir)
    log(String(format: "mic.wav: %.1f s", mic.writer.durationSeconds))
    log(String(format: "system.wav: %.1f s (%d callbacks)", systemWriter.durationSeconds, system.callbackCount))
    log("meta.json written")
    exit(0)
}

signal(SIGINT, SIG_IGN)
signal(SIGTERM, SIG_IGN)
let sigint = DispatchSource.makeSignalSource(signal: SIGINT, queue: .main)
let sigterm = DispatchSource.makeSignalSource(signal: SIGTERM, queue: .main)
sigint.setEventHandler { shutdown() }
sigterm.setEventHandler { shutdown() }
sigint.resume()
sigterm.resume()

dispatchMain()
