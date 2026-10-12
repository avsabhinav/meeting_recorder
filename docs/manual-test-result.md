# Manual Conversation Test — RESULT (P1 pause checkpoint)

Date: 2026-10-12 · Real mic + real system capture via spike `mr-capture` → production
`mr.core` (transcribe + merge + output). Scripted 1:2 product-review conversation
(5 Alex lines via TTS through speakers; 5 You lines read aloud).

## Outcome: PIPELINE WORKS END-TO-END (with one documented mic-hallucination issue)

### Captured (`spike/out/manual/`, from `meta.json`)
- `aec: true`; `duration_seconds: 69.7`
- mic: MacBook Pro Microphone @48kHz x9ch, 1,115,200 samples; system: MacBook Pro Speakers @48kHz x2ch, 871,936 samples
- macos_version `27.0.1 (26A434)` (host shows as 27; target still macOS 14.2+ at runtime)

### Transcription speed (KEY for the 45-min real call tomorrow)
- mic (69.7s audio) transcribed in **4.51s** ≈ **15x realtime**
- system (54.5s audio) transcribed in **0.86s** ≈ **63x realtime** (silence trims by VAD)
- => a full 45-min call (both tracks) should finish in ~ **2–4 min**. Comfortable for the helper.

### Correct
- Both tracks present; attribution correct and deterministic (mic→You, system→Them).
- Chronological interleaving with accurate MM:SS timestamps.
- **Echo handling worked:** Alex's 5 lines appear ONCE (as Them) — none leaked as duplicate You copies (AEC + merge dedup did their job).
- `.md` renders exactly per spec (duration, participants, source header, `**You (MM:SS):**` rows).

### CORRECTED finding (user clarification): no hallucination — background show on mic
The "Courtney and Amanda ... chopping block ... girl power" segments at 0.00–15.50 were
**real audio from a show/TV playing in the room**, captured by the mic (which is correct
behavior) and faithfully transcribed + attributed to **You** (mic track). Not hallucinated film.
- Whisper transcribed the room audio accurately.
- Attribution is honest: anything on the mic = You, even if it is not your voice (inherent to the 1:1 model).

### Real remaining item
Your line 2 got garbled on first pass — **"Good deduct here" (00:21)** appeared as a separate You
segment *overlapping* Alex's clip; the intended "Sure, happy to help" also came through correctly at
00:32. Likely the play-over of the background show + you speaking created a low-confidence splice.
Lines 3–5 transcribed **correctly** ("I think the colors look good but the blue one could be a bit
darker", "I'll check the mobile spacing...", "Sounds good... talk tomorrow").

### Correct (unchanged)
- Both tracks present; attribution correct + deterministic (mic→You, system→Them).
- Chronological interleaving with accurate MM:SS timestamps.
- **Echo handling worked:** Alex's 5 lines appear ONCE (as Them) — none leaked as duplicate You copies.
- `.md` renders exactly per spec.


## What to carry to the real meeting tomorrow
- Capture + transcription + merge + output all validated on real hardware.
- Expect ~2–4 min transcribe for a full 45-min call.
- Attribution is honest: the mic captures *everything* in front of it (including room
  background audio) and attributes it to **You**. For a clean transcript in a real call,
  be aware that background conversations/hum become "You" lines — restate clearly, and keep
  the mic free of unrelated speech for best results. This is inherent to the 1:1 mic/system design.
