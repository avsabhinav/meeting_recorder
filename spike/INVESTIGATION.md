# Phase 0 Spike — Investigation Log & To‑Do

> Working notes while implementing the Phase 0 spike described in
> `../PHASE0_SPIKE.md` (see also `../PLAN.md` §7 and `../Project Goal.md`).
> This file is the scratchpad: environment facts, API research, and decisions
> made along the way, plus the live to‑do list. `SPIKE_RESULTS.md` (once
> filled in) is the actual deliverable report — this file is supporting
> evidence for *why* the code looks the way it does.

## To‑do list (live)

- [ ] Scaffold `spike/` structure (capture package, scripts, docs)
- [ ] Write `mr-capture` Swift (tap + VPIO mic + resample + WAV + meta + SIGINT)
- [ ] Build the Swift binary and verify it compiles
- [ ] Self-test capture (beep + short recording + SIGINT) → validate WAVs
- [ ] Write `transcribe.py` (mlx-whisper), `align_check.py`, `echo_check.py`
- [ ] Set up Python env + install mlx-whisper + fetch the model
- [ ] Run align/echo/transcribe checks on self-test data
- [ ] Write `README.md`, `.gitignore`, `SPIKE_RESULTS.md` (fill in what's verifiable)
- [ ] **Human-only step (cannot be automated here):** record a real ~45 min
      1:1 call on laptop speakers with consent, plus a ~5 min `--no-aec`
      comparison clip, then re-run transcribe/echo_check on that data and
      finish `SPIKE_RESULTS.md`.

---

## Environment recon (done)

| Item | Finding |
|---|---|
| macOS | `ProductVersion: 27.0.1`, `BuildVersion: 26A434` — far above the 14.2+ floor the tap API needs |
| Arch | `arm64` (Apple Silicon) — M‑series, matches target hardware |
| Swift | `/usr/bin/swift`, swift-driver 1.168.6, Apple Swift 6.4, target `arm64-apple-macosx27.0.0` |
| xcodebuild | present (`/usr/bin/xcodebuild`) |
| System Python | `/usr/bin/python3`, 3.9.6 (old; fine for stdlib use, but mlx-whisper stack will go in its own env) |
| pip | 21.2.4 (system, old) |
| node | v26.5.1 at `/opt/homebrew/bin/node` (irrelevant to this spike) |
| `uv` | **present** at `/opt/homebrew/bin/uv`, 0.12.1 → use this to create an isolated venv for the ML stack instead of fighting system Python 3.9 |
| `pyenv`, `pipx` | not present |
| ML packages (mlx_whisper, huggingface_hub, numpy, soundfile, rapidfuzz) | **none installed** on system Python — need a venv |
| HF cache | `~/.cache/huggingface/hub` exists, has unrelated models (Qwen3‑TTS, bge‑small, Qwen3‑ASR GGUF); **no whisper large‑v3‑turbo yet** — first run will download it |
| Disk free | 692 GiB free on `/` — plenty of room for the model (~1.6 GB) and WAVs |
| Network | `curl https://huggingface.co` → `200` — model download should work |

**Decision:** use `uv venv` under `spike/` (e.g. `spike/.venv`) to get a modern
Python (3.11/3.12) for `mlx-whisper`, `huggingface_hub`, `numpy`, `soundfile`,
`rapidfuzz`, rather than fighting the system 3.9.6 interpreter.

---

## Core Audio process-tap API research (done)

Goal: confirm the exact signatures before writing Swift, since this API is
under-documented. Read the actual SDK headers rather than relying on memory.

SDK used: `/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk`
(`xcrun --show-sdk-path`).

### `AudioHardwareTapping.h` (CoreAudio framework)

```c
extern OSStatus
AudioHardwareCreateProcessTap(CATapDescription* inDescription,
                              AudioObjectID*  outTapID)        API_AVAILABLE(macos(14.2));

extern OSStatus
AudioHardwareDestroyProcessTap(AudioObjectID inTapID)          API_AVAILABLE(macos(14.2));
```

Confirms macOS 14.2+ floor matches the plan.

### `CATapDescription.h` (CoreAudio framework, Obj‑C class)

Key initializers / properties:

- `initStereoMixdownOfProcesses:` — only the given processes, mixed to stereo.
- `initStereoGlobalTapButExcludeProcesses:` — **everything except** the given
  processes, mixed to stereo. **This is what we want**: pass our own PID so
  we exclude ourselves and tap everything else (the call app, etc.).
- `initMonoMixdownOfProcesses:` / `initMonoGlobalTapButExcludeProcesses:` — mono variants.
- `initWithProcesses:andDeviceUID:withStream:` / `initExcludingProcesses:andDeviceUID:withStream:` — tap tied to one physical output device/stream.
- Properties: `name`, `UUID`, `processes`, `bundleIDs` (macOS 26+ only),
  `mono`, `exclusive`, `mixdown`, `privateTap` (getter `isPrivate`, setter
  `setPrivate:` — set **true** so only our process can see/read the tap),
  `processRestoreEnabled` (macOS 26+), `muteBehavior` (`CATapUnmuted` /
  `CATapMuted` / `CATapMutedWhenTapped` — leave unmuted so the call audio
  keeps playing normally through the speakers), `deviceUID`, `stream`.

**Decision:** `initStereoGlobalTapButExcludeProcesses:[ourPID]`, `privateTap = true`,
default `muteBehavior` (`CATapUnmuted`) so we don't mute the call for the user.

### Reading from the tap device

The task description says: tap → "private aggregate device containing the
tap" → IOProc → downmix/resample → WAV. Investigated whether that extra
aggregate-device step is actually required.

Finding: `AudioHardwareCreateProcessTap` returns an `AudioObjectID` that is
itself a live input device (this is exactly how BlackHole-free capture tools
read taps in the wild). It can be read directly with a plain
`AudioQueueNewInput` targeting that device — no aggregate device needed.

**Decision:** read the tap directly via `AudioQueue` instead of wrapping it
in a private aggregate device. Simpler, less code, same result. Documented
as a deliberate simplification (not a deviation that changes behavior).

### `AudioQueue.h` (AudioToolbox framework) — exact signatures captured

```c
typedef void (*AudioQueueInputCallback)(
    void * __nullable               inUserData,
    AudioQueueRef                   inAQ,
    AudioQueueBufferRef             inBuffer,
    const AudioTimeStamp *          inStartTime,
    UInt32                          inNumberPacketDescriptions,
    const AudioStreamPacketDescription * __nullable inPacketDescs);

extern OSStatus
AudioQueueNewInput(const AudioStreamBasicDescription *inFormat,
                    AudioQueueInputCallback         inCallbackProc,
                    void * __nullable               inUserData,
                    CFRunLoopRef __nullable         inCallbackRunLoop,
                    CFStringRef __nullable          inCallbackRunLoopMode,
                    UInt32                          inFlags,
                    AudioQueueRef __nullable * __nonnull outAQ);

typedef struct AudioQueueBuffer {
    const UInt32 mAudioDataBytesCapacity;
    void * const mAudioData;
    UInt32       mAudioDataByteSize;
    void * __nullable mUserData;
    const UInt32 mPacketDescriptionCapacity;
    AudioStreamPacketDescription * const __nullable mPacketDescriptions;
    UInt32       mPacketDescriptionCount;
} AudioQueueBuffer;
typedef AudioQueueBuffer *AudioQueueBufferRef;
```
Plus `AudioQueueAllocateBuffer`, `AudioQueueEnqueueBuffer`, `AudioQueueStart`,
`AudioQueueStop`, `AudioQueueSetProperty`, `AudioQueueDispose` confirmed present.

**Plan:** `AudioQueueSetProperty(kAudioQueueProperty_CurrentDevice, <tap UID>)`
(or construct the queue against the tap's device UID) so the queue pulls from
the tap instead of the default input device; query the tap's native stream
format first so the requested `AudioStreamBasicDescription` matches (avoids
silent format-mismatch failures).

---

## Mic capture + AEC API research (done)

Task text says: "`AVAudioEngine` input node with `setVoiceProcessingEnabled(true)`."
Verified this exists, but **not** where expected:

- `grep`ing `AVAudioEngine.h` directly found nothing — because the
  `AVFoundation.framework` header is just a one-line re-export:
  `#import <AVFAudio/AVAudioEngine.h>`. The real implementation lives in the
  separate `AVFAudio.framework`.
- Found it in `AVFAudio.framework/Headers/AVAudioIONode.h`:

```objc
@property (nonatomic, readonly, getter=isVoiceProcessingEnabled) BOOL voiceProcessingEnabled
    API_AVAILABLE(macos(10.15), ios(13.0), watchos(6.0), tvos(13.0));

- (BOOL)setVoiceProcessingEnabled:(BOOL)enabled error:(NSError **)outError
    API_AVAILABLE(macos(10.15), ios(13.0), watchos(6.0), tvos(13.0));
```

It's declared on `AVAudioIONode`, the **shared base class** of both
`AVAudioInputNode` and `AVAudioOutputNode` — not a method you'd expect to find
by grepping just `AVAudioEngine.h`.

Important documented constraints (straight from the header comment), which
directly shape the implementation:

1. "If enabled, the input node does signal processing on the incoming audio
   (taking out any of the audio that is played from the device at a given
   time from the incoming audio)." → On macOS this reads as: VPIO's echo
   reference is **the device's current output**, not something we have to
   feed in manually (unlike the classic iOS pattern of wiring a far-end
   reference buffer by hand). This is good news for our use case (cancelling
   the remote party's voice coming out of the laptop speakers) and is exactly
   the mechanism the spike needs to validate empirically.
2. "Voice processing requires both input **and** output nodes to be in voice
   processing mode. Enabling it on either node auto-enables it on the other."
3. "Voice processing is only supported when the engine is rendering to the
   audio device and **not** in manual rendering mode." → the engine must
   actually be started with real device I/O (mic in, speaker out), even if
   the thing we render to the output is silence. Plan: connect
   `mainMixerNode` → `outputNode` (silence) purely to satisfy this
   "is rendering" requirement, then tap `inputNode`.
4. "Voice processing can only be enabled or disabled while the engine is
   stopped." → call `setVoiceProcessingEnabled` before `engine.start()`.
5. "The output format of the input node and the input format of the output
   node have to match, and can only be changed while stopped." → set formats
   up front, before starting.

**Open risk flagged for `SPIKE_RESULTS.md`:** it's unverified until tested on
real call audio whether macOS's device-level echo reference actually
cancels *another app's* played audio (Zoom/Meet/Teams audio on laptop
speakers) as opposed to only audio this engine itself renders. The plan's
own fallback (always-on text-overlap dedup in `echo_check.py`) exists
precisely because this might not fully work — that is what Task 5 is for.
**Decision:** implement the simple, spec'd approach (`setVoiceProcessingEnabled(true)`
on the input node, silent render to satisfy the "rendering" requirement),
measure with `echo_check.py` on both AEC‑on and AEC‑off recordings, and
report the real behavior rather than assuming it works. If it under‑performs,
that's a valid, useful spike finding — not a blocker — because dedup is the
always‑on safety net per `PLAN.md`.

A harder alternative (feed the system-audio tap in as an explicit far-end
reference into the VPIO render path) was considered and **rejected for the
spike**: it requires routing the engine's output away from the physical
speakers to avoid an audible feedback loop, which is real production-grade
work, not a ≤1-day spike. Noted as a possible Phase 2 refinement if AEC alone
underperforms badly.

---

## Build approach for the Swift binary

Deliverable asks for a SwiftPM package (`spike/capture/`) → `mr-capture`
binary, **plus** an embedded Info.plist (`NSMicrophoneUsageDescription`,
`NSAudioCaptureUsageDescription`) via linker `-sectcreate __TEXT __info_plist`.

Problem: SwiftPM's `unsafeFlags` linker settings take flags relative to the
build working directory, not the package root, which makes embedding a
sibling `Info.plist` file fragile across `swift build` invocations.

**Decision:** keep `Package.swift` as the real SwiftPM package definition
(so `swift build` / `swift run` work normally for iterating on the code), and
do the release build + Info.plist injection via a `build.sh` script that:
1. Runs `swift build -c release` to get a linked binary with all symbols resolved.
2. Re-invokes `swiftc`/`ld` semantics is overkill; instead uses
   `swift build -c release -Xlinker -sectcreate -Xlinker __TEXT -Xlinker __info_plist -Xlinker <absolute path to Info.plist>`
   — `-Xlinker` flags on the `swift build` command line *are* passed straight
   to the linker with absolute paths resolved by the shell, sidestepping the
   `unsafeFlags`-relative-path issue entirely.
3. Verifies the section landed with `otool -s __TEXT __info_plist <binary>`.

This keeps the deliverable a genuine, buildable SwiftPM package while still
reliably producing a binary with the embedded usage-description plist.

---

## What this spike run can and cannot verify end-to-end

Can verify now, without a human on a call:
- Swift binary builds and runs; both WAVs + `meta.json` are produced; SIGINT
  finalizes cleanly.
- Alignment: play a click/beep via `afplay` at the start/end of a short
  `--no-aec` recording, measure offset/drift with `align_check.py`.
- Transcription: `mlx-whisper large-v3-turbo` on the captured tracks; timing;
  hallucination behavior on silence; HF cache reuse with `HF_HUB_OFFLINE=1`.
- Echo-check mechanics (`echo_check.py` text-overlap scoring) on whatever
  audio is available, including the self-test recording.

Cannot verify in this environment (needs a human + a real call):
- A genuine ~45 min 1:1 call on laptop speakers in Zoom/Meet/Teams, with the
  other party's consent, to measure real-world echo/AEC behavior, ducking,
  and sustained capture over time.
- The Shortcuts "Run Shell Script" permission-attribution check (requires
  interactively creating a Shortcut and granting TCC permissions).

These are called out explicitly in `SPIKE_RESULTS.md` as follow-up steps for
a human to run, with exact commands to do so, rather than silently skipped.
