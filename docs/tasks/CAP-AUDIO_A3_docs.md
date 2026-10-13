TASK: CAP-AUDIO/A3 Update current user-facing/operational docs after the raw-mic (no AEC) change
GOAL: The documenting CLI reference and the "how it works / echo handling" sections that users and future contributors actually read must no longer mention `--aec/--no-aec` or capture-time echo cancellation, and must state clearly that recording is invisible to the live call (raw mic + system tap) with echo handled by the merge-time text-overlap dedup. Any copy-paste CLI example that would now fail must be fixed.
CONTEXT: Task A1 removed voice processing (Echo Cancellation/AEC) from the `mr-capture` Swift helper, and task A2 removed the `--aec/--no-aec` CLI options (`mr start`, `mr toggle`, `RecordSession` no longer accept them). The new truth: `mr-capture --out <dir>` and `mr start`/`mr toggle` record the RAW mic + system audio, do NOT degrade an active call, and rely on the existing always-on text-overlap dedup (`dedup_threshold`, default 0.6) for echo. Historical/plan/spike docs (PLAN.md, PHASE0_SPIKE.md, docs/tasks/P1_*/P2_*/MB_*, spike/**) record past work and are NOT in scope — do not touch them.
FILES (create/modify ONLY these):
- README.md
- docs/architecture.md
- docs/simulated-test-production.md
- examples/manual/README.md
READ FIRST: README.md (full), docs/architecture.md (full), then the specific lines in docs/simulated-test-production.md and examples/manual/README.md that run `toggle --no-aec`.
STEPS:
1. README.md:
   - "How it works" (around line 13-16): the step describing the mic says "via the voice-processing I/O path, with automatic echo cancellation". Rewrite to say the mic is recorded RAW (no voice processing) so recording never lowers the call volume or ducks the remote participant; system audio via the Core Audio tap; echo is removed later by dedup.
   - CLI reference: `mr toggle` usage line `mr toggle [--aec | --no-aec] [--json]` → `mr toggle [--json]`; remove the `--aec`/`--no-aec` bullet. `mr start` section `mr start [--aec | --no-aec]` → `mr start`; remove the aec bullet. Any other `--aec/--no-aec` mention in the CLI reference → remove.
   - "Echo handling" (around line 277): currently "AEC at capture time does the heavy lifting; the merge step's text-overlap dedup ... catches anything AEC couldn't cancel." Rewrite: there is NO capture-time AEC so the call is untouched; the merge step's text-overlap dedup is the echo handling. Also adjust "How it works" step 1's phrase "with automatic echo cancellation".
2. docs/architecture.md:
   - Decision (2) "Echo philosophy": replace the statement that "AEC (voice-processing I/O) does the heavy lifting" with a statement that capture is RAW (no voice processing by design, so recording never degrades an active call) and the text-overlap dedup is the sole echo handling at a chosen threshold.
   - Decision (1) mentions "VPIO input (AEC on) reports 9 channels". Update to note that voice processing was removed (real call showed it degraded audio); the mic is now a raw 1-channel tap.
3. docs/simulated-test-production.md:
   - `./spike/.venv/bin/python -m mr.cli toggle --no-aec` → `./spike/.venv/bin/python -m mr.cli toggle`. Remove the parenthetical "(Use the default `--aec` ...; `--no-aec` exercises the software echo-dedup path ...)". Replace with a short note that echo dedup is the (only) echo handling; the default toggle records raw mic.
   - Line 15 ("spawns the mr-capture helper (mic + system-audio tap, AEC)") → drop "AEC".
4. examples/manual/README.md: any `mr.cli toggle --no-aec` → `mr.cli toggle`.
5. Do NOT touch PLAN.md, PHASE0_SPIKE.md, docs/tasks/*, spike/*, config.toml.example, or any code/tests.
ACCEPTANCE:
1. `grep -rinE "\-\-aec|\-\-no-aec" README.md docs/architecture.md docs/simulated-test-production.md examples/manual/README.md` → zero matches.
2. `grep -rinE "automatic echo cancel|AEC at capture|AEC \(voice" README.md docs/architecture.md` → zero matches.
3. `git diff --stat` for the four files is reasonable (< ~120 changed lines total); diff reads cleanly (no unrelated reformatting of untouched lines).
OUT OF SCOPE: any code/test file, config.toml.example, historical docs, and the `aec: false` meta-field docs (schema keeps that key; no need to document further).
REPORT: reply with STATUS, FILES CHANGED, VERIFICATION (the two grep results + diff stat), and NOTES.