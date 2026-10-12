# Simulated Conversation Test — Production `mr` CLI (P2.7)

> **⚠️ This test requires a human to speak and play audio — a recording will be started.**
> **Do not run it in an automated or headless context.** The recording steps (Step 2)
> must be performed by a person at a Mac with speakers and a mic, in a real Terminal.

This is the **canonical production simulated-conversation test**. It supersedes the
older spike-binary + in-process driver approach in
[`docs/manual-test-conversation.md`](manual-test-conversation.md) (kept for history).

## What this validates

End-to-end production flow with a controllable scripted conversation:

1. **`mr toggle` start** — spawns the `mr-capture` helper (mic + system-audio tap, AEC).
2. **`mr toggle` stop** — stops capture, runs the real local `mlx-whisper`
   transcription (offline, cache-only), merges the two tracks with echo dedup.
3. **Attributed transcript** — writes `~/Meetings/transcripts/<stamp>.md` with You/Them
   speakers and `MM:SS` timestamps (attribution is directly checkable).
4. **Notification** — the macOS notification is posted when the transcript is ready.

The **Them side is played from the speakers** (TTS clips), so it lands in `system.wav`
via the process tap AND acoustically in `mic.wav` — exactly the echo case the merge
dedup must handle. **You speak your lines aloud** into the mic.

## The scripted scenario (inline)

A short fictional 1:1 **product review** chat.

Them lines (played from speakers) — "Alex":

```
1. Hi, this is Alex from the design team. Thanks for making time today.
2. I wanted to get your thoughts on the new dashboard layout before we ship it on Friday.
3. Do you think the chart colors are clear enough, or should we make them stronger?
4. One more thing, could you also look at the spacing on the mobile view?
5. Great, that's really helpful. I'll pass that on and we can finalize tomorrow.
```

You lines (spoken aloud, in the prompts) — "you":

```
1. Good to talk to you too.
2. Sure, happy to help.
3. I think the colors look good, but the blue one could be a bit darker.   ← speak OVER Alex's line 3 (overlap/dedup case)
4. I'll check the mobile spacing and send you notes after this.
5. Sounds good, talk tomorrow.
```

## Prerequisites

1. **Helper built** (P2.1): `bash capture/build.sh` (produces `capture/.build/release/mr-capture`).
2. **Model cached** (one-time, needs network): `./spike/.venv/bin/python -m mr.cli doctor --fetch-model`
3. **Environment ready**: `./spike/.venv/bin/python -m mr.cli doctor`
   should show the helper path and `model cached: yes`.
4. Permissions: Microphone + System audio (Input Monitoring / Screen Recording as
   applicable) granted to the Terminal app that runs the CLI — see
   [README.md](../README.md) (permissions section) and
   [docs/permissions-troubleshooting.md](permissions-troubleshooting.md).

All commands run from the repo root (`meeting recorder/`).

## Step 1 — Them-side audio assets

Pre-built assets usually exist at `spike/out/manual/them_1..5.wav` (gitignored).
Check first; only rebuild if missing:

```sh
ls spike/out/manual/them_1.wav && echo "assets present" \
  || bash examples/manual/prep_clips.sh   # builds them_1..them_5.wav via `say` (Samantha, 16 kHz)
```

## Step 2 — record (human, in Terminal — NOT in an agent session)

> **Optional:** to keep the test out of your real `~/Meetings` tree, temporarily point
> `out_root` at a scratch dir — edit `~/.config/mr/config.toml`:
> `out_root = "~/Meetings-dev"` — and restore it afterwards.

**Terminal 1 — start recording:**

```sh
./spike/.venv/bin/python -m mr.cli toggle --no-aec
```

(Use the default `--aec` if you want to exercise Apple's AEC instead; `--no-aec`
exercises the software echo-dedup path, which is the case under test here.)

**Terminal 2 — timed Them playback (same moment, or right after):**

```sh
bash examples/manual/play_timed.sh
```

The script plays each Alex line and prints `>>> Your turn: '...'` prompts — **speak your
matching line aloud** at each prompt. For line 3 it prints the prompt while Alex is
still speaking: speak **over** it on purpose (the overlap line the dedup must absorb).

**After the last prompt**, back in Terminal 1:

```sh
./spike/.venv/bin/python -m mr.cli toggle
```

`toggle` now stops the capture, transcribes both WAVs, merges with echo dedup, and
writes `~/Meetings/transcripts/<stamp>.md` (or your scratch `out_root`), then posts the
macOS notification.

> **Exit code 3** = model not cached — run `mr doctor --fetch-model`, then re-run
> `mr stop` (state is kept so you can retry; `mr status` shows the recording).

## Step 3 — verify

1. `./spike/.venv/bin/python -m mr.cli status` → `recording: no` (no active capture
   after stop) and `last transcript: <path to the new .md>`.
2. Open the transcript `~/Meetings/transcripts/<stamp>.md` and check:
   - You and Them lines are **interleaved in time order** with `MM:SS` timestamps.
   - **Attribution is correct**: your spoken lines → **You**, the played Alex lines →
     **Them** (no swaps).
   - **No full echo duplicate** of Alex's line 3 as a spurious "You" segment — the
     intentional overlap should be gone (dedup absorbed it) or clearly attributed to Them.
   - **No hallucinated text** in the silent gaps between lines.
   - Header shows participants + a plausible duration for the ~40–60 s of playback.
3. Check `meta.json` in the recording dir (`~/Meetings/recordings/<stamp>/`):
   `samples_written` should be non-zero for **both** the mic and system tracks
   (system audio captured, mic captured).

## Step 4 — what to report

- The transcript `.md` content (paste or link).
- `meta.json` `samples_written` for both tracks (and capture duration).
- Whether the **osascript/macOS notification** appeared when the transcript was written.
- **Permission-prompt behavior**: did the Microphone / system-audio TCC prompt appear
  (first run), and for which app? Any denied prompts?
- Any attribution, echo, or hallucination issues — quote the offending lines.
- Exit codes of each `mr` command (all should be `0`, except a one-off `3` if the model
  was not yet cached).

## Scripts

- `examples/manual/prep_clips.sh` — build the 5 Them WAVs.
- `examples/manual/play_timed.sh` — timed playback with "Your turn" prompts.
- `examples/manual/driver.py` — **deprecated**; superseded by `mr stop` / `mr toggle`.
- See `examples/manual/README.md` for the short script reference.
