TASK: P2.8 Add `examples/manual/verify_transcript.py` — automated transcript verification

GOAL: Give the human a one-command **automated verdict** after the simulated-conversation test,
replacing manual transcript inspection. `verify_transcript.py <transcript.md> [recording_dir]`
parses the attributed transcript and the recording's `meta.json`, and prints a clear PASS/FAIL
summary: both speakers present, timestamps in non-decreasing time order, both tracks have
non-zero samples in `meta.json`, no duplicate text appearing as both You and Them. Exit 0 if all
checks pass, non-zero (with reasons) otherwise.

CONTEXT:
- Repo: `meeting recorder/` (space in path — quote paths).
- The simulated test (P2.7) is documented in `docs/simulated-test-production.md`; its Step 3 is
  currently manual. This script automates that step.
- Transcript `.md` format (from `mr/core/output.py` `render_transcript_md`): header lines then a
  `## Transcript` section with one line per segment:
  `**You (MM:SS):** <text>` / `**Them (MM:SS):** <text>` (blank lines between). `MM:SS` may be
  2-digit minutes only (from `format_ts`), e.g. `00:00`, `01:07`.
- Recording dir `meta.json` format (from `mr/core/schema.py` `from_capture_dict` / the Swift
  `writeMeta`): keys `mic` and `system`, each with `samples_written` (int) and `device_name`.
- The script is a **standalone example/diagnostic**, NOT part of the installed package. It should
  import nothing from `mr.*` if possible (pure stdlib: `re`, `json`, `sys`, `argparse`, `pathlib`)
  so a human can run it with any python3. `argparse` for CLI.
- Keep it dependency-free and robust to an unexpected/missing transcript.

FILES (create/modify only):
- `examples/manual/verify_transcript.py` (CREATE, executable `chmod +x`)
- `examples/manual/README.md` (EDIT — add a line for the new script)

READ FIRST:
1. `docs/simulated-test-production.md` (Step 3, lines 111-136) — what it must check.
2. `mr/core/output.py` lines 25-47 — the exact `.md` line format to parse.
3. `mr/core/schema.py` lines 46-98 — the `meta.json` (CaptureMeta) shape.
4. `examples/manual/README.md` — where to add the script reference.

STEPS:
1. Create `examples/manual/verify_transcript.py` (stdlib only, `#!/usr/bin/env python3`):
   - `argparse`: positional `transcript` (path to the `.md`); optional `--recording <dir>` defaulting
     to the transcript's `Source` if derivable, else None; optional `--json` to also read the JSON
     sidecar if present (not required).
   - Parse the `.md`: a regex like `^\*\*(You|Them) \((\d{2}):(\d{2})\): (.*)$` over the transcript.
     Collect `(speaker, mm, ss, text, lineno)` in order.
   - Checks and their reasons:
     a. `both_speakers`: at least one `You` and one `Them` segment present (else FAIL "missing
        X side").
     b. `time_order`: as we walk the parsed lines, each timestamp (`mm*60+ss`) is >= the previous
        (allowing equal for overlaps); if a later line is earlier, FAIL "out of order at line N".
     c. `no_full_echo`: if the *lowercased, stripped text* of any segment appears as BOTH You and
        Them (exact-ish match after collapse of whitespace), flag WARN/FAIL "line duplicated across
        speakers (possible echo)" — this is a soft warning, not a hard fail (echo dedup may keep a
        legitimate echo). Default: report as WARN but still PASS the overall unless truly absent.
     d. `meta_samples` (if `--recording` given and `meta.json` exists): `mic.samples_written > 0`
        and `system.samples_written > 0` (else FAIL "track silent: X").
   - Print a concise PASS/FAIL block: a line per check with `[PASS]` / `[FAIL]`/`[WARN]` and the
     reason, then a summary `OVERALL: PASS` (exit 0) or `OVERALL: FAIL` (exit 1). `a` and `d`
     are hard fails; `b` is a hard fail; `c` is a WARN (does not fail overall). If the transcript
     can't be parsed (0 lines), FAIL with "no segments parsed".
   - Handle missing file gracefully (print error, exit 2).
2. Edit `examples/manual/README.md` to add `verify_transcript.py` (automated PASS/FAIL on the
   transcript + meta; usage `verify_transcript.py <transcript.md> --recording <dir>`).
3. Write a small unit test OR a self-check: run the script on a sample transcript you create
   (`examples/manual/fixtures/` or a temp file) and confirm it prints PASS for a well-formed
   transcript and FAIL for a missing-side / out-of-order one. Add `tests/test_verify_transcript.py`
   if it fits the repo suite easily (offline, invoke via subprocess or import the parse fn). If a
   unit test is heavy, a manual self-check in the report suffices — prefer a light test that imports
   the script's parse/check functions (make the script importable as a module by guarding `main()`).
4. Run ruff on `examples/manual/verify_transcript.py` (project ruff config) and the test.

ACCEPTANCE:
- `examples/manual/verify_transcript.py` runs and gives PASS on a correct sample and FAIL (exit 1)
  on a missing-side/out-of-order sample.
- `examples/manual/README.md` documents it.
- `./spike/.venv/bin/python -m pytest tests/ -q` still passes (all existing).
- `./spike/.venv/bin/ruff check examples/manual/verify_transcript.py` clean (or that path is
  included; if ruff ignores `examples/` in config, note it and use a clean import-style guard).
- Script uses only stdlib (no `mr.*` import required to run the checks).

OUT OF SCOPE:
- Do NOT modify `mr/`, `capture/`, `tests/` (except a NEW `tests/test_verify_transcript.py` if you
  add one), `docs/simulated-test-production.md`, `pyproject.toml`.
- Do NOT record anything. Do NOT change the transcript `.md` format.
- Do NOT commit (CTO agent owns git).

REPORT: reply with STATUS, FILES CHANGED, VERIFICATION (commands + sample PASS/FAIL output), NOTES.