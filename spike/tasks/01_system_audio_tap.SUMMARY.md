# Task 1 — system audio tap → system.wav (STATUS: done — finished by lead)

- Local worker left it non-building; once built, the "read the tap directly via
  AudioQueue" design **failed at runtime**: `AudioQueueStart` → -10478,
  device props → -66680. The INVESTIGATION.md claim was wrong.
- Lead rewrote to the Apple-documented path: tap → **private aggregate device**
  (main sub-device = default output, `taps = [tap UUID]`, tapautostart) →
  `AudioDeviceCreateIOProcIDWithBlock` → mono downmix → resample → WAV.
- Also fixed a WAV header bug (`"ftm "` instead of `"fmt "`) and dropped the
  buggy Int16 resampler path (tap is always float32).
- Code split into reusable files under `capture/Sources/mr-capture/`:
  `Wav.swift` (thread-safe incremental `WavWriter`, header patched ~1 s),
  `Resample.swift` (`BoxResampler`, box-filter to 16 kHz Int16),
  `SystemTap.swift` (`SystemTapCapture` + CoreAudio helpers), `main.swift`.
- Self-check: 5.8 s run with `afplay Ping.aiff` x3 → `afinfo`: 1 ch, 16000 Hz,
  Int16; peak 0.294, RMS 0.013; 548 IOProc callbacks; SIGINT → exit 0.
  No TCC prompt appeared (run from the DSH host process).
- Excluding our own process uses `kAudioHardwarePropertyTranslatePIDToProcessObject`.
