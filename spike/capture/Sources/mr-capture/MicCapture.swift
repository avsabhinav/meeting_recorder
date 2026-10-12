import Foundation
import CoreAudio
import AVFoundation

// Microphone capture via AVAudioEngine, with optional voice processing (AEC).
//
// Pipeline (macOS):
//   inputNode (voice processing enabled BEFORE engine.start() when AEC on)
//     -> mainMixerNode -> outputNode   (VPIO needs the engine to render to a
//                                       real output device)
//     -> inputNode tap (bus 0) -> channel 0 only (with VP enabled the format
//        can be 2ch = mic+reference; channel 0 is the user's voice)
//     -> BoxResampler -> WavWriter.
//
// Note: enabling voice processing may trigger the microphone TCC prompt.
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
    /// Whether voice processing (AEC) is enabled (valid after start()).
    private(set) var aecEnabled = false

    init(outPath: String) throws {
        writer = try WavWriter(path: outPath)
    }

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

    private func handle(_ buf: AVAudioPCMBuffer) {
        guard let resampler, let data = buf.floatChannelData else { return }
        let frames = Int(buf.frameLength)
        guard frames > 0 else { return }
        let ch0 = data.pointee   // channel 0 = user's voice (mic + reference mix)

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
