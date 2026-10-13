import Foundation
import CoreAudio
import AVFoundation

// Microphone capture via AVAudioEngine, recording the RAW mic with no voice
// processing, so capturing never degrades an active call (no mic attenuation,
// no ducking of remote audio). Echo is handled by downstream text dedup.
//
// Pipeline (macOS):
//   inputNode -> inputNode tap (bus 0) -> channel 0 (the user's raw voice)
//     -> BoxResampler -> WavWriter.
//
// Note: capturing the mic may trigger the microphone TCC prompt.
// If denied, the stream runs but delivers silence.

final class MicCapture {
    /// Owned WavWriter (created by init). Caller closes it on shutdown.
    private(set) var writer: WavWriter
    private let engine = AVAudioEngine()
    private var resampler: BoxResampler?
    private let lock = NSLock()
    private var _firstHostTime: UInt64?
    private var started = false

    /// mach host time (mach_absolute_time units) of the first captured sample.
    var firstSampleHostTime: UInt64? { lock.lock(); defer { lock.unlock() }; return _firstHostTime }

    /// Native sample rate of the input stream (valid after start()).
    private(set) var nativeSampleRate: Double = 0
    /// Native channel count of the input stream (valid after start()).
    private(set) var nativeChannels: UInt32 = 0
    /// Name of the input device (valid after start()).
    private(set) var deviceName: String = "unknown"

    init(outPath: String) throws {
        writer = try WavWriter(path: outPath)
    }

    func start() throws {
        let input = engine.inputNode
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

    private func handle(_ buf: AVAudioPCMBuffer) {
        guard let resampler, let data = buf.floatChannelData else { return }
        let frames = Int(buf.frameLength)
        guard frames > 0 else { return }
        let ch0 = data.pointee   // channel 0 = user's voice (raw mic)

        lock.lock()
        if _firstHostTime == nil { _firstHostTime = mach_absolute_time() }
        lock.unlock()

        writer.append(resampler.process(Array(UnsafeBufferPointer(start: ch0, count: frames))))
    }

    /// Stop the engine and remove the tap. Idempotent.
    /// Does not close the WavWriter (caller owns it).
    func stop() {
        guard started else { return }
        started = false
        engine.inputNode.removeTap(onBus: 0)
        engine.stop()
    }
}
