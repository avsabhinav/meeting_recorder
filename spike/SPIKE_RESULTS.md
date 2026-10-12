# Spike Results

- Date: 2026-10-12 / macOS Version 27.0.1 (Build 26A434) / hardware: MacBook Pro (Apple Silicon, arm64)
- Call app used: none — self-test audio via `say` (TTS) + `afplay` pings/click played out of the
  laptop speakers. **A real-human call clip is still required (see "What's left for a human").**

## Verdict: GO (with the caveats below verified on self-test audio, not a real call)

| Check | Result | Pass? | Notes |
|---|---|---|---|
| Capture | Both `mic.wav` & `system.wav` valid 16 kHz mono s16le for full run; no dropouts; Ctrl-C / SIGTERM finalizes cleanly (exit 0), `meta.json` written | ✅ | System tap via private aggregate device + IOProc; mic via AVAudioEngine + VPIO. AEC on → input format is **9 ch** (take ch 0 = user voice); AEC off → 1 ch. |
| Alignment (offset / drift) | Start offset **1.4 ms** (system leads mic) vs bar < 0.5 s. meta first-sample offset 477 ms (startup latency, not real drift). | ✅ | Measured with distinctive click at start recorded on a `say` test. Mid/end windows unreliable on speech (need clicks in every window to measure long-run drift). |
| Echo (AEC on vs off, best threshold) | **AEC on:** You line "Thank you" vs Them text → token_ratio 13.5, **0 flagged** at all thresholds. **AEC off:** You line = exact remote speech → ratio **96.7**, flagged at 0.5/0.6/0.7. | ✅ | AEC clearly cancels speaker audio leaked into the mic on self-test. Safety net: echo_check.py at ~0.6–0.7. Threshold must be re-validated on a real call. |
| Permissions (Terminal / Shortcuts) | Ran from the DSH host process with **no TCC prompt observed**. | ⚠️ partial | Release binary embeds Info.plist (`NSMicrophoneUsageDescription`, `NSAudioCaptureUsageDescription`) + adhoc codesign. Must confirm prompts/attribution from **Terminal** and **Shortcuts** by a human (Shortcuts step unverifiable here). |
| Speed (per track / total) | 19 s of audio, 2 tracks: **4.2 s + 0.6 s = 4.8 s total** (incl. ~3–4 s model load on first track; cached on 2nd). | ✅ | 45-min call: loading once ≈ few s then ~7× realtime ⇒ well under the ≤ ~3 min bar. Exact 45-min figure needs the real call. |
| Hallucination (setting used) | `no_speech_threshold=0.6`, `condition_on_previous_text=false`, `hallucination_silence_threshold=0.0`; empty-text segments dropped. No invented text seen in test silence. | ✅ (self-test) | VAD pre-pass (silero) not needed yet; revisit on real call/silence-only clips. |
| AEC ducking / artifacts | Not meaningfully measured (no real remote-party call audio to duck). | ⚠️ | `voiceProcessingOtherAudioDuckingConfiguration(.min)` set; must observe a real call for ducking/artifacts. |

## Surprises / gotchas
- **The tap AudioObjectID is NOT directly readable by `AudioQueue`** (INVESTIGATION.md was
  wrong): `AudioQueueStart` → `-10478`. The Apple-documented route — wrap the tap in a
  **private aggregate device** (main sub-device = default output, `taps` list) and read it with an
  **IOProc block** — works.
- **Excluding our own process** requires the CoreAudio *process object*, not the raw PID:
  `kAudioHardwarePropertyTranslatePIDToProcessObject`.
- **VPIO on macOS forces an odd input format**: with AEC on the input node reports **9 channels**;
  the user's voice is channel 0. Always take channel 0.
- `engine.connect(mainMixer → output, format:)` crashes with `IsFormatSampleRateAndChannelCountValid`
  if you pass `outputNode.outputFormat(forBus:)` before the engine starts; pass the **input node's
  format** instead. `engine.start()` then works (`setVoiceProcessingEnabled` before start; no `-10875`).
- No `ffmpeg` on this machine: mlx-whisper must be fed numpy float32 arrays (loaded by `soundfile`),
  never a file path.
- Swift build inside the DSH tool sandbox needs `--disable-sandbox` + a temp
  `CLANG_MODULE_CACHE_PATH` (sandbox-exec is blocked there). Normal terminal doesn't.
- `meta.json` first-sample times must use **one clock** — I switched both to `mach_absolute_time`
  (boot-seconds) so they're comparable.

## Recommended changes to PLAN.md
- Phase baseline: note that the tap must be read via an **aggregate device + IOProc**, not directly.
- Note the **9-channel VPIO input** quirk and "take channel 0".
- Keep the AEC *and* echo_check dedupe both on; AEC does the heavy lifting on self-test, dedupe is
  the safety net for cases AEC can't cancel (e.g. other apps' audio).
- Lock the mlx-whisper settings (`no_speech_threshold=0.6`, `condition_on_previous_text=false`).

## Sample output
AEC-on test (mic = `You`, system = `Them`):
```md
# Transcript

**Them (00:00):** This is a test of the meeting recorder. We are recording a conversation to verify echo cancellation and transcription. The quick brown fox jumps over the lazy dog.

**Them (00:11):** Please proceed with the quarterly review. The budget numbers look reasonable for next quarter.

**You (00:13):** Thank you.
```
AEC-off test (identical speech from speakers leaks fully into the mic — echo):
```md
**Them (00:00):** Please proceed with the quarterly review, the budget numbers look reasonable for next quarter.
**You (00:02):** Please proceed with the quarterly review. The budget numbers look reasonable for next quarter.   ← echo, ratio 96.7
```

## What's left for a human (cannot be automated here)
1. **Record a real ~45-min 1:1 call on laptop speakers** (Zoom/Meet/Teams) with the other party's
   consent: `mr-capture --out <dir>` (AEC on). Then a ~5-min `--no-aec` clip in similar conditions.
2. Re-run `transcribe.py`, `align_check.py`, `echo_check.py` on them; fill in the exact speed,
   drift, ducking/artifact, and real-call echo numbers above.
3. Confirm permissions from **Terminal** and from a **Shortcuts → "Run Shell Script"** action
   (note which app macOS asks permission for).
4. If hallucination appears on real-call silent stretches, add a `silero-vad` pre-pass and compare.