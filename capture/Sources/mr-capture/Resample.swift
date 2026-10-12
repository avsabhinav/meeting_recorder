import Foundation

// Streaming mono resampler to 16 kHz Int16 using box-filter ("area") averaging:
// each output sample is the mean of the input samples that fall inside its
// time slot. Acts as a crude anti-alias low-pass, good enough for speech ASR,
// and handles non-integer ratios (e.g. 44.1 kHz). State carries across calls.
//
// Callers downmix to mono first (Float, nominal range -1...1).
final class BoxResampler {
    let sourceRate: Double
    let targetRate: Double
    private let step: Double          // input samples per output sample
    private var acc: Double = 0       // running sum for current output slot
    private var accCount: Int = 0
    private var slotEnd: Double       // input-sample index (absolute) where current slot ends
    private var consumed: Double = 0  // absolute input samples consumed so far

    init(sourceRate: Double, targetRate: Double = 16000) {
        self.sourceRate = sourceRate
        self.targetRate = targetRate
        self.step = sourceRate / targetRate
        self.slotEnd = sourceRate / targetRate
    }

    func process(_ mono: UnsafePointer<Float>, count: Int) -> [Int16] {
        var out = [Int16]()
        out.reserveCapacity(Int(Double(count) / step) + 2)
        for i in 0..<count {
            acc += Double(mono[i]); accCount += 1
            consumed += 1
            if consumed >= slotEnd {
                let v = accCount > 0 ? acc / Double(accCount) : 0
                out.append(Self.toInt16(v))
                acc = 0; accCount = 0
                slotEnd += step
            }
        }
        return out
    }

    func process(_ mono: [Float]) -> [Int16] {
        mono.withUnsafeBufferPointer { b in
            guard let base = b.baseAddress else { return [] }
            return process(base, count: b.count)
        }
    }

    @inline(__always) static func toInt16(_ x: Double) -> Int16 {
        let v = (x * 32767).rounded()
        return Int16(max(-32768, min(32767, v)))
    }
}
