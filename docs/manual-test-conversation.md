# Manual Test — Scripted Conversation (pause checkpoint after Phase 1)

> → Production CLI version: see `docs/simulated-test-production.md`.

> **Why we stop here:** Phase 1 core is complete and unit-tested (schema, output, merge,
> transcribe). Before building the live `mr start/stop/toggle` control layer (Phase 2),
> we validate the whole real pipeline once: **spike `mr-capture`** (already-proven capture)
> → **production `mr.core`** (transcribe + merge + output) → review the attributed `.md`.

## What this validates
1. Real mic + system capture works (spike binary), AEC on, two 16 kHz mono WAVs.
2. Production `transcribe_audio` runs real `mlx-whisper large-v3-turbo` locally (offline) on the captured WAVs.
3. Production `merge_transcripts` interleaves You/Them + drops residual echo.
4. Production `render_transcript_md` produces the exact expected `.md`.
5. Attribution: mic→You, system→Them, correct; no hallucinations on silence.

## The scripted scenario
A short, natural 1:2 fictional **product review** chat. The **Them side is played from the
speakers** (TTS via `say` → `afplay`), so it lands in `system.wav` via the process tap AND
acoustically in `mic.wav` (this is exactly the echo case we care about). **You speak your
lines aloud** into the mic.

Them lines (played from speakers) — "Alex":
```
Hi, this is Alex from the design team. Thanks for making time today.
I wanted to get your thoughts on the new dashboard layout before we ship it on Friday.
Do you think the chart colors are clear enough, or should we make them stronger?
One more thing, could you also look at the spacing on the mobile view?
Great, that's really helpful. I'll pass that on and we can finalize tomorrow.
```
You lines (read aloud, in the pauses) — "you":
```
Good to talk to you too.
Sure, happy to help.
I think the colors look good, but the blue one could be a bit darker.
I'll check the mobile spacing and send you notes after this.
Sounds good, talk tomorrow.
```

## Step 1 — prepare the Them-side system audio
Run once (builds a short spoken WAV with `say`, e.g. ~30s):
```sh
mkdir -p spike/out/manual
say -v Samantha -o spike/out/manual/them.m4a \
  "Hi, this is Alex from the design team. Thanks for making time today. \
I wanted to get your thoughts on the new dashboard layout before we ship it on Friday. \
Do you think the chart colors are clear enough, or should we make them stronger? \
One more thing, could you also look at the spacing on the mobile view. \
Great, that's really helpful. I'll pass that on and we can finalize tomorrow."
```
(If m4a is not playable by afplay on this machine, use `say -v Samantha -o spike/out/manual/them.wav --data-format=LEI16@16000 ...` for a WAV.)

## Step 2 — record (do this in Terminal, not in this agent session)
```sh
mkdir -p spike/out/manual
spike/capture/.build/release/mr-capture --out spike/out/manual     # AEC on, Ctrl-C to stop
```
Then, in a SECOND Terminal window, play the Them side on a loop and follow the timing:
- Start `afplay spike/out/manual/them.m4a` (or `them.wav`).
- Read your Your-lines in the natural pauses (you can re-play the audio; speak over it a
  little to exercise AEC/echo).
- When done, press **Ctrl-C** in the recording window (flushes WAVs + writes `meta.json`).

> **Timing tip:** To create the mid "conversation" overlap, start your 3rd line ("I think
> the colors look good...") just as the Them side is speaking — that spatial/temporal overlap
> is what the dedup safety net removes.

## Step 3 — run the production pipeline on the captured WAVs
```sh
./spike/.venv/bin/python examples/manual/driver.py spike/out/manual
```
This runs `transcribe_audio` (mic→You, system→Them), `merge_transcripts`, and
`render_transcript_md`, writing:
- `spike/out/manual/transcript.md`
- `spike/out/manual/transcript.json`

## Step 4 — review `spike/out/manual/transcript.md`
Check:
- You and Them lines are *interleaved in time order* with correct `MM:SS` timestamps.
- Your spoken lines are attributed to **You**, the played lines to **Them** (no swaps).
- No full **echo** line: you should not also see a duplicate "You" copy of a line that is
  clearly the played Them speech (that would mean dedup/overlap missed it).
- No **hallucinated** text in silent stretches.
- Dashboard header shows the right participants + duration.

## What to report back
Paste (or point to) `transcript.md` + `meta.json` contents, and note: capture duration,
any AEC ducking you heard, any attribution/echo/hallucination issues.

## Notes / fallbacks
- If no mic permission prompt appeared / mic silent, check System Settings → Privacy → Microphone
  for the Terminal app that launched `mr-capture`; this is exactly what we're testing (spike
  couldn't verify TCC prompts from a normal Terminal).
- If system audio is empty, confirm the tap captured (see `meta.json` `samples_written` for
  the system stream) and that the audio was actually playing out of the speakers.
- The driver prints each track's audio_seconds + wall_seconds (also the 45-min real-call
  speed sanity signal).
