import Foundation
import CoreAudio
import AudioToolbox

// System-audio capture via a Core Audio process tap (macOS 14.2+).
//
// Pipeline: CATapDescription (global stereo, excluding our own process)
//   -> AudioHardwareCreateProcessTap
//   -> private aggregate device {main sub-device = default output, taps = [tap]}
//   -> IOProc block -> downmix to mono -> BoxResampler -> WavWriter.
//
// NOTE: the tap AudioObjectID is NOT directly readable by AudioQueue
// (AudioQueueStart fails with -10478); the aggregate device is required.

struct CaptureError: Error, CustomStringConvertible {
    let description: String
    init(_ what: String, _ status: OSStatus) {
        description = "\(what) failed: OSStatus \(status) (0x\(String(UInt32(bitPattern: status), radix: 16)))"
    }
    init(_ msg: String) { description = msg }
}

// MARK: - small Core Audio helpers

func caAddress(_ selector: AudioObjectPropertySelector,
               _ scope: AudioObjectPropertyScope = kAudioObjectPropertyScopeGlobal) -> AudioObjectPropertyAddress {
    AudioObjectPropertyAddress(mSelector: selector, mScope: scope, mElement: kAudioObjectPropertyElementMain)
}

func caGetString(_ obj: AudioObjectID, _ selector: AudioObjectPropertySelector) -> String? {
    var addr = caAddress(selector)
    var value: Unmanaged<CFString>?
    var size = UInt32(MemoryLayout<Unmanaged<CFString>?>.size)
    let st = withUnsafeMutablePointer(to: &value) { p in
        AudioObjectGetPropertyData(obj, &addr, 0, nil, &size, p)
    }
    guard st == noErr, let value else { return nil }
    return value.takeRetainedValue() as String
}

func caGetUInt32(_ obj: AudioObjectID, _ selector: AudioObjectPropertySelector) -> UInt32? {
    var addr = caAddress(selector)
    var v: UInt32 = 0
    var size = UInt32(MemoryLayout<UInt32>.size)
    return AudioObjectGetPropertyData(obj, &addr, 0, nil, &size, &v) == noErr ? v : nil
}

func defaultOutputDeviceID() -> AudioObjectID? {
    caGetUInt32(AudioObjectID(kAudioObjectSystemObject), kAudioHardwarePropertyDefaultOutputDevice)
}

/// Our own CoreAudio process object (needed for the exclude list; raw PIDs are rejected).
func ownProcessObjectID() -> AudioObjectID? {
    var addr = caAddress(kAudioHardwarePropertyTranslatePIDToProcessObject)
    var pid = getpid()
    var obj = AudioObjectID(0)
    var size = UInt32(MemoryLayout<AudioObjectID>.size)
    let st = AudioObjectGetPropertyData(AudioObjectID(kAudioObjectSystemObject), &addr,
                                        UInt32(MemoryLayout<pid_t>.size), &pid, &size, &obj)
    return (st == noErr && obj != kAudioObjectUnknown) ? obj : nil
}

// MARK: - SystemTapCapture

final class SystemTapCapture {
    private let writer: WavWriter
    private var tapID = AudioObjectID(kAudioObjectUnknown)
    private var aggID = AudioObjectID(kAudioObjectUnknown)
    private var procID: AudioDeviceIOProcID?
    private var resampler: BoxResampler?
    private let ioQueue = DispatchQueue(label: "mr-capture.systemtap", qos: .userInteractive)
    private let lock = NSLock()
    private var _firstHostTime: UInt64?
    private var _callbacks = 0

    /// Native sample rate of the tap stream (valid after start()).
    private(set) var nativeSampleRate: Double = 0
    /// Native channel count of the tap stream (valid after start()).
    private(set) var nativeChannels: UInt32 = 0
    /// Name of the output device whose mix is being tapped (valid after start()).
    private(set) var deviceName: String = "unknown"

    /// mach host time (mach_absolute_time units) of the first captured sample.
    var firstSampleHostTime: UInt64? { lock.lock(); defer { lock.unlock() }; return _firstHostTime }
    var callbackCount: Int { lock.lock(); defer { lock.unlock() }; return _callbacks }

    init(writer: WavWriter) { self.writer = writer }

    func start() throws {
        // 1. Tap: everything except ourselves, stereo mixdown, private, unmuted.
        let exclude = ownProcessObjectID().map { [$0] } ?? []
        let desc = CATapDescription(stereoGlobalTapButExcludeProcesses: exclude)
        desc.name = "mr-capture system tap"
        desc.isPrivate = true
        desc.muteBehavior = .unmuted
        var st = AudioHardwareCreateProcessTap(desc, &tapID)
        guard st == noErr else { throw CaptureError("AudioHardwareCreateProcessTap", st) }

        // 2. Tap format.
        var fmtAddr = caAddress(kAudioTapPropertyFormat)
        var asbd = AudioStreamBasicDescription()
        var asbdSize = UInt32(MemoryLayout<AudioStreamBasicDescription>.size)
        st = AudioObjectGetPropertyData(tapID, &fmtAddr, 0, nil, &asbdSize, &asbd)
        guard st == noErr else { throw CaptureError("get kAudioTapPropertyFormat", st) }
        guard asbd.mFormatID == kAudioFormatLinearPCM,
              asbd.mFormatFlags & kAudioFormatFlagIsFloat != 0,
              asbd.mBitsPerChannel == 32 else {
            throw CaptureError("unexpected tap format: id=\(asbd.mFormatID) flags=\(asbd.mFormatFlags) bits=\(asbd.mBitsPerChannel)")
        }
        nativeSampleRate = asbd.mSampleRate
        nativeChannels = asbd.mChannelsPerFrame
        resampler = BoxResampler(sourceRate: asbd.mSampleRate)

        // 3. Private aggregate device wrapping the default output + the tap.
        guard let outID = defaultOutputDeviceID(),
              let outUID = caGetString(outID, kAudioDevicePropertyDeviceUID) else {
            throw CaptureError("could not resolve default output device")
        }
        deviceName = caGetString(outID, kAudioObjectPropertyName) ?? outUID
        let aggDesc: [String: Any] = [
            kAudioAggregateDeviceNameKey: "mr-capture-tap",
            kAudioAggregateDeviceUIDKey: "mr-capture-tap-\(UUID().uuidString)",
            kAudioAggregateDeviceMainSubDeviceKey: outUID,
            kAudioAggregateDeviceIsPrivateKey: true,
            kAudioAggregateDeviceIsStackedKey: false,
            kAudioAggregateDeviceTapAutoStartKey: true,
            kAudioAggregateDeviceSubDeviceListKey: [[kAudioSubDeviceUIDKey: outUID]],
            kAudioAggregateDeviceTapListKey: [[
                kAudioSubTapDriftCompensationKey: true,
                kAudioSubTapUIDKey: desc.uuid.uuidString,
            ]],
        ]
        st = AudioHardwareCreateAggregateDevice(aggDesc as CFDictionary, &aggID)
        guard st == noErr else { throw CaptureError("AudioHardwareCreateAggregateDevice", st) }

        // 4. IOProc: input buffers carry the tap audio (interleaved float32).
        st = AudioDeviceCreateIOProcIDWithBlock(&procID, aggID, ioQueue) {
            [weak self] _, inInputData, inInputTime, _, _ in
            self?.handle(inInputData, inInputTime)
        }
        guard st == noErr, procID != nil else { throw CaptureError("AudioDeviceCreateIOProcIDWithBlock", st) }

        // 5. Go. (First start triggers the "System Audio Recording" TCC prompt;
        //    if denied, the stream runs but delivers silence.)
        st = AudioDeviceStart(aggID, procID)
        guard st == noErr else { throw CaptureError("AudioDeviceStart", st) }
    }

    private func handle(_ abl: UnsafePointer<AudioBufferList>, _ time: UnsafePointer<AudioTimeStamp>) {
        guard let resampler else { return }
        let buffers = UnsafeMutableAudioBufferListPointer(UnsafeMutablePointer(mutating: abl))
        guard let first = buffers.first, first.mDataByteSize > 0, first.mData != nil else { return }

        // Downmix every channel of every buffer (interleaved or not) to mono.
        let frames = Int(first.mDataByteSize) / (4 * Int(max(1, first.mNumberChannels)))
        guard frames > 0 else { return }
        var mono = [Float](repeating: 0, count: frames)
        var totalCh = 0
        for b in buffers {
            guard let data = b.mData else { continue }
            let ch = Int(max(1, b.mNumberChannels))
            let f = data.assumingMemoryBound(to: Float.self)
            let n = min(frames, Int(b.mDataByteSize) / (4 * ch))
            for i in 0..<n {
                var s: Float = 0
                for c in 0..<ch { s += f[i * ch + c] }
                mono[i] += s
            }
            totalCh += ch
        }
        if totalCh > 1 {
            let k = 1 / Float(totalCh)
            for i in 0..<frames { mono[i] *= k }
        }

        lock.lock()
        if _firstHostTime == nil, time.pointee.mFlags.contains(.hostTimeValid) {
            _firstHostTime = time.pointee.mHostTime
        }
        _callbacks += 1
        lock.unlock()

        writer.append(resampler.process(mono))
    }

    /// Stop the IOProc and tear down aggregate device + tap. Idempotent.
    /// Does not close the WavWriter (caller owns it).
    func stop() {
        if aggID != kAudioObjectUnknown {
            if let procID {
                AudioDeviceStop(aggID, procID)
                AudioDeviceDestroyIOProcID(aggID, procID)
            }
            procID = nil
            ioQueue.sync {}  // drain in-flight callbacks
            AudioHardwareDestroyAggregateDevice(aggID)
            aggID = AudioObjectID(kAudioObjectUnknown)
        }
        if tapID != kAudioObjectUnknown {
            AudioHardwareDestroyProcessTap(tapID)
            tapID = AudioObjectID(kAudioObjectUnknown)
        }
    }
}
