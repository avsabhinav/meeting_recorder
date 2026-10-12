TASK: P1.7 Create `mr/cli.py` — `mr process` subcommand (typer)

GOAL: A working `mr` CLI (built on `typer`) with the `process` subcommand implemented end-to-end: given `--mic a.wav --system b.wav` (16 kHz mono WAVs), it transcribes both with the production core, merges with echo dedup, and writes the attributed Markdown transcript (and optional JSON sidecar). `mr process --help` and a successful run must both work when the CLI module is imported and executed with the spike venv.

CONTEXT:
- Repo: `meeting recorder/` (space in path affects every invocation of the interpreter).
- Python 3.12+, `typer` is already in `pyproject.toml` deps (`typer>=0.12`) and installed in the spike venv.
- You are building the `mr` app object that P2.4 will later extend with `start/stop/toggle/status/doctor`. Establish the typer app now with a clear structure so later tasks add subcommands without refactoring this file.
- The production core already exists and is fully tested (42 tests passing). Use it, do not reimplement:
  - `from mr.core.transcribe import transcribe_audio, ModelNotCachedError, DEFAULT_MODEL` (`mr/core/transcribe.py`)
  - `from mr.core.merge import merge_transcripts` — `merge_transcripts(you: list[Segment], them: list[Segment], *, dedup_threshold: float=0.6) -> list[Segment]`
  - `from mr.core.output import render_transcript_md, render_transcript_json, write_transcript, write_json, SCHEMA_VERSION` (`mr/core/output.py`) — read it to confirm exact signatures.
  - `from mr.core.schema import Segment`
- The `.md` format (do not change, from `output.py`): header `# Meeting — <stamp>`, `- Duration`, `- Participants: You (mic), Them (system)`, `- Source`, `## Transcript`, then `**You (MM:SS):** …` / `**Them (MM:SS):** …`.
- `transcribe_audio(path, *, speaker, model=DEFAULT_MODEL, language="en")` raises `ModelNotCachedError` if the model isn't cached offline. The CLI's `process` must catch it and print a clear error to stderr + exit non-zero (exit code 3) with a pointer to `mr doctor --fetch-model`.
- `transcribe.py` sets `HF_HUB_OFFLINE=1` itself at call time (offline cache-only), so you do NOT need to set it — but the CLI module importing `mlx_whisper` must remain lazy (the transcriber imports mlx_whisper lazily inside its own `transcribe`; the CLI just calls `transcribe_audio`, so nothing needs pre-importing).
- Defaults the CLI should use for `process`: `--model` default `DEFAULT_MODEL`, `--language` default `"en"`, `--dedup-threshold` default `0.6`, `--json` flag default off, `--out-dir` (optional; if given, write there instead of next to the system wav). The `--stamp` and `--source-dir` values passed to `render_transcript_md` should be derived: stamp from the out base name or a `--stamp` arg defaulting to the base name of the mic/system wav dir; `source_dir` as `"recordings/<stamp>"`.
- Testing approach: do NOT run a real mlx-whisper transcription in tests (model present locally but transcription is slow and heavy). Use typer's CliRunner (from `typer.testing`) and monkeypatch `mr.cli.transcribe_audio` (or `process`) to return synthetic `TranscriptionResult` objects. Confirm `mr/cli.py` exposes the typer `app` and a `process` callable.
- The spike venv interpreter is `./spike/.venv/bin/python`. Run tests with it.

FILES (create only):
- `mr/cli.py`
- `tests/test_cli_process.py`

READ FIRST:
1. `mr/core/output.py` — read the exact signatures of `render_transcript_md`, `render_transcript_json`, `write_transcript`, `write_json`, `SCHEMA_VERSION`.
2. `mr/core/transcribe.py` — confirm `transcribe_audio`/`DEFAULT_MODEL`/`ModelNotCachedError` and the `TranscriptionResult` fields (`track/speaker/model/audio_seconds/wall_seconds/settings/segments`).
3. `mr/core/merge.py` and `mr/core/schema.py` — `merge_transcripts` signature and `Segment`/`TranscriptionResult` shapes.
4. `examples/manual/driver.py` — the current manual pipeline to mirror (it is the reference; the CLI `process` replaces it).

STEPS:
1. Create `mr/cli.py`:
   - Imports: `typer`, and from `mr.core.transcribe` import `transcribe_audio, ModelNotCachedError, DEFAULT_MODEL`; from `mr.core.merge` import `merge_transcripts`; from `mr.core.output` import `render_transcript_md, render_transcript_json, write_transcript, write_json`.
   - `app = typer.Typer(help="Local-first meeting recorder: capture and transcribe 1:1 calls.")` and add it as a console-script in `pyproject.toml` `[project.scripts]` `mr = "mr.cli:app"` (edit `pyproject.toml` to add that — it's the only non-code file touch).
   - Define `process` as a typer command:
     ```
     @app.command()
     def process(
         mic: Annotated[Path, typer.Option("--mic", help="You-side 16 kHz mono mic WAV")],
         system: Annotated[Path, typer.Option("--system", help="Them-side 16 kHz mono system WAV")],
         model: Annotated[str, typer.Option(help="HF model id")] = DEFAULT_MODEL,
         language: Annotated[str, typer.Option(help="Language code")] = "en",
         dedup_threshold: Annotated[float, typer.Option("--dedup-threshold", min=0.0, max=1.0)] = 0.6,
         json: Annotated[bool, typer.Option("--json", help="Also write a JSON sidecar")] = False,
         stamp: Annotated[str, typer.Option(help="Stamp/label for the transcript")] = "",
         out_dir: Annotated[Path | None, typer.Option("--out-dir", help="Directory for transcript.md/json")] = None,
     ) -> None:
     ```
     (Use `Annotated` from `typing`; verify typer version installed (0.27) supports it — it does.)
   - Body of `process`:
     - Validate both files exist (else `typer.BadParameter`/`raise SystemExit(2)` with a clear message).
     - `you = transcribe_audio(str(mic), speaker="You", model=model, language=language)`; `them = transcribe_audio(str(system), speaker="Them", model=model, language=language)`. Wrap both in a single `try/except ModelNotCachedError` → `typer.echo(f"error: {e}", err=True)`; `raise typer.Exit(code=3)`.
     - `merged = merge_transcripts(list(you.segments), list(them.segments), dedup_threshold=dedup_threshold)`.
     - Compute `duration = max((s.end for s in you.segments + them.segments), default=0.0)`.
     - Derive `stamp = stamp or Path(out_dir or system).stem` — keep simple: if `stamp` empty, use the stem of the directory containing `system` (or the system file stem); the exact choice just needs to produce a sane name.
     - Resolve output dir: `out_dir or system.parent`. `md_path = out / f"{stamp}.md"`, `json_path = out / f"{stamp}.json"`.
     - Write using the existing destination helpers from `mr.core.output` (they makedirs parents automatically): `write_transcript(md_path, render_transcript_md(stamp=stamp, source_dir=f"recordings/{stamp}", segments=merged, duration_seconds=duration))`. If `--json`: `write_json(json_path, render_transcript_json(merged, stamp=stamp))`.
     - `typer.echo(f"wrote {md_path}")` (and json path if written). Optionally `typer.echo(f"kept {len(merged)} segments")`.
   - Keep `def main()` entrypoint: `def main() -> None: app()` guarded by `if __name__ == "__main__": main()`.
2. Edit `pyproject.toml`: add under `[project]`:
   ```
   [project.scripts]
   mr = "mr.cli:app"
   ```
   (append this table; keep the rest intact).
3. Write `tests/test_cli_process.py`:
   - Use `from typer.testing import CliRunner` and `runner = CliRunner()`.
   - For running real CLI code without transcription, monkeypatch `mr.cli.transcribe_audio` to return synthetic `TranscriptionResult`s (build small ones with `segments=(Segment(speaker="You", text="hello", start=0.0, end=1.2),)` and the `Them` one). Then `runner.invoke(app, ["process", "--mic", m, "--system", s, "--out-dir", tmp])`.
   - Write tiny throwaway WAVs in the test (either via `soundfile` with 16 kHz float data, or just create empty placeholder files — but `output.py`/transcribe won't read them since we monkeypatch transcribe; only file-existence is checked against mic/system paths, so placeholder empty files suffice; still, create real 16k WAVs with soundfile for realism if easy).
   - Assert: exit code 0; transcript file exists and contains `# Meeting — `, `**You (`, `**Them (`.
   - Test `--json` writes the `.json` sidecar.
   - Test the `ModelNotCachedError` path by monkeypatching `transcribe_audio` to `raise ModelNotCachedError("x")`; assert exit code 3 and stderr contains `fetch-model`.
   - Test missing-file → non-zero exit (2) and an error message.
   - ~5 tests, offline, no real whisper, no network.
4. Run the suite + ruff on the new files.

ACCEPTANCE:
- `./spike/.venv/bin/python -m pytest tests/ -q` — all tests pass (existing 42 + new).
- `./spike/.venv/bin/ruff check mr/cli.py tests/test_cli_process.py` — clean.
- `./spike/.venv/bin/python -m mr.cli --help` prints the app help with `process` listed. (Add `if __name__ == "__main__": main()` so this works.)
- After the test pass, a real smoke: `./spike/.venv/bin/python -m mr.cli process --help` shows the `--mic`/`--system` options.
- Optionally report `./spike/.venv/bin/python -m pytest -m "" -q` full count.

OUT OF SCOPE:
- Do NOT implement `start/stop/toggle/status/doctor` — those are P2.4 (just leave structure ready).
- Do NOT use `mr.core.capture.RecordSession` here (that wrapper is P1.6, used by P2.4 for record; `process` only re-processes existing wavs).
- Do NOT modify `mr/core/*` files (schema, transcribe, merge, output, capture) or spike files.
- Do NOT add new dependencies beyond what's already declared.

REPORT: reply with STATUS, FILES CHANGED, VERIFICATION (commands + output), NOTES (including whether typer 0.27 accepts `Annotated` options as expected).
