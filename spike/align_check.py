#!/usr/bin/env python3
"""align_check.py — measure offset and drift between mic.wav and system.wav.

Both files are 16 kHz mono WAV (s16le), captured simultaneously. A sound
played at the speakers appears in BOTH tracks (system tap directly, mic
acoustically), so a windowed cross-correlation of a short mic probe against
the system track recovers the relative lag (in samples).

Usage:
    align_check.py <dir> [--probe SECONDS]

Prints (no output files):
    offset_start_ms, offset_mid_ms, offset_end_ms,
    drift_ms_over_call, drift_rate_ms_per_hour,
    meta_first_sample_offset_ms (if <dir>/meta.json has first-sample times).
"""

import argparse
import json
import os

import numpy as np
import soundfile as sf

try:
    from scipy.signal import correlate as _scipy_correlate
except Exception:  # pragma: no cover - scipy normally present in spike/.venv
    _scipy_correlate = None

SR = 16000
RMS_FLOOR = 1e-4


def cross_correlate_valid(a, v):
    """Return c[i] = sum_n a[n+i] * v[n] for i = 0 .. len(a)-len(v) (v shorter).

    Uses scipy when available; otherwise an equivalent numpy rfft fallback.
    """
    if _scipy_correlate is not None:
        return _scipy_correlate(a, v, mode="valid")
    n = len(a) + len(v) - 1
    size = 1 << (n - 1).bit_length()
    fa = np.fft.rfft(a, size)
    fv = np.fft.rfft(v, size)
    r = np.fft.irfft(fa * np.conj(fv), size)  # r[k] = c[-k] (zero-padded)
    m = len(a) - len(v) + 1
    return np.array([r[(size - i) % size] for i in range(m)], dtype=np.float64)


def rms(x):
    if x.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(np.asarray(x, dtype=np.float64)))))


def measure(mic, sys_, probe_seconds):
    """Return dict window_name -> offset_ms (system lag relative to mic)."""
    n_common = min(len(mic), len(sys_))
    if n_common == 0:
        raise ValueError("no common audio samples")
    mic = (mic - mic.mean())[:n_common]
    sys_ = (sys_ - sys_.mean())[:n_common]

    n_win = max(1, n_common // 3)
    windows = {
        "start": (0, n_win),
        "middle": (n_win, 2 * n_win),
        "end": (2 * n_win, n_common),
    }

    results = {}
    for name, (w0, w1) in windows.items():
        mic_win = mic[w0:w1]
        sys_win = sys_[w0:w1]
        if rms(sys_win) < RMS_FLOOR or rms(mic_win) < RMS_FLOOR:
            print(f"[{name}] low-confidence window, skipping")
            continue
        p_len = min(int(probe_seconds * SR), len(sys_win))
        if p_len < 16:
            print(f"[{name}] window too short for probe, skipping")
            continue
        p = mic_win[:p_len]  # 1 s mic slice near window start (default)
        c = cross_correlate_valid(sys_win, p)
        lag = int(c.argmax())
        results[name] = (lag / SR) * 1000.0
    return results, n_win


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("dir", help="directory containing mic.wav and system.wav")
    ap.add_argument(
        "--probe",
        type=float,
        default=1.0,
        help="probe length in seconds (default 1.0)",
    )
    args = ap.parse_args()

    mic, sr_m = sf.read(os.path.join(args.dir, "mic.wav"), dtype="float32")
    sys_, sr_s = sf.read(os.path.join(args.dir, "system.wav"), dtype="float32")
    if sr_m != SR or sr_s != SR:
        raise ValueError(f"expected 16 kHz audio, got {sr_m} / {sr_s}")
    mic = mic.ravel()
    sys_ = sys_.ravel()

    results, n_win = measure(mic, sys_, args.probe)

    if "start" in results:
        print(f"offset_start_ms  = {results['start']:.1f}")
    if "middle" in results:
        print(f"offset_mid_ms    = {results['middle']:.1f}")
    if "end" in results:
        print(f"offset_end_ms    = {results['end']:.1f}")

    if "start" in results and "end" in results:
        drift = results["end"] - results["start"]
        span_hours = (2 * n_win) / SR / 3600.0  # probe-to-probe span (start→end window)
        print(f"drift_ms_over_call = {drift:.1f}")
        if span_hours > 0:
            print(f"drift_rate_ms_per_hour = {drift / span_hours:.1f}")

    meta_path = os.path.join(args.dir, "meta.json")
    if os.path.exists(meta_path):
        with open(meta_path) as f:
            meta = json.load(f)

        def first_seconds(track):
            node = meta.get(track)
            if isinstance(node, dict) and "first_sample_seconds" in node:
                return node["first_sample_seconds"]
            return meta.get(f"{track}.first_sample_seconds")

        t_mic = first_seconds("mic")
        t_sys = first_seconds("system")
        if t_mic is not None and t_sys is not None:
            print(
                f"meta_first_sample_offset_ms = "
                f"{(t_sys - t_mic) * 1000.0:.1f}"
            )
        else:
            print("meta.json present but missing mic/system first_sample_seconds")


if __name__ == "__main__":
    main()
