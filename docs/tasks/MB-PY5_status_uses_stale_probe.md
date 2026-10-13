# MB-PY5 — `mr status` must report `recording: no` when the capture process is dead (stale pidfile)

## TASK: MB-PY5 — Make `mr status` honour PID liveness (stale pidfile ⇒ "recording: no")

**GOAL:** When the recording state pidfile exists but its recorded PID is no longer alive, `mr status` must print `recording: no` (not `recording: yes`) and still surface the stale-pidfile note. A live PID must keep reporting `recording: yes`.

**CONTEXT:**

Project: local Mac meeting recorder. Python CLI lives in `mr/`. State is a JSON pidfile at `<out_root>/.state/recording.json`. The `status` command currently reports `recording: yes` whenever `read_state()` returns a state object, i.e. purely on pidfile existence — so a stale pidfile (crash, interrupted `mr stop`) keeps reporting `yes` forever and the menu-bar icon stays red.

Two ready-made helpers exist in `mr/state.py`:

```python
def read_state(out_root: str) -> RecordingState | None: ...   # None if no file / malformed
def is_stale(state: RecordingState) -> bool:                  # True if os.kill(pid,0) raises ProcessLookupError
```

Current `status()` in `mr/cli.py` (lines ~325-347):

```python
@app.command()
def status() -> None:
    """Show whether a capture is active and the most recent transcript."""
    cfg = load_config()
    state = read_state(cfg.out_root)
    if state is None:
        typer.echo("recording: no")
    else:
        typer.echo("recording: yes")
        typer.echo(f"pid: {state.pid}")
        typer.echo(f"out_dir: {state.out_dir}")
        typer.echo(f"stamp: {state.stamp}")
        typer.echo(f"started_at: {state.started_at}")
        if is_stale(state):
            typer.echo("stale pidfile; run `mr stop` to clear", err=True)
    tdir = _transcripts_dir(cfg)
    ...
```

`is_stale` is already imported at the top of `mr/cli.py` (`from mr.state import ... is_stale ...`). The menu-bar Swift app parses "recording: yes"/"recording: no" from exit-0 stdout of `mr status` (see `menu-bar/Sources/mrBar/MRCLI.swift` line 95-96), so the literal output strings must not change.

**Intended new behaviour:**

- `read_state` is `None` → `recording: no` (unchanged).
- state exists AND `is_stale(state)` is False (PID alive) → `recording: yes` + pid/out_dir/stamp/started_at (unchanged).
- state exists AND `is_stale(state)` is True (PID dead) → print:
  ```
  recording: no
  pid: <pid>
  out_dir: <out_dir>
  stamp: <stamp>
  started_at: <started_at>
  ```
  followed on **stderr** by the existing note `stale pidfile; run \`mr stop\` to clear` (keep it on stderr so it can't be mistaken for the parsed `recording:` line). Keep printing the pid/out_dir/stamp/started_at under a stale pidfile too (diagnostic value; they are accurate facts about the leftover file).

The transcript-section logic (`tdir` glob at the bottom) must remain completely unchanged.

**FILES:**
- `mr/cli.py` (only the `status()` body)
- `tests/test_cli_start_stop_toggle_status_doctor.py` (only the `status` tests area, lines ~72-108)

**READ FIRST:**
- `mr/cli.py` lines 324-347 (the `status` command; `is_stale` imported at line 45)
- `mr/state.py` lines 135-154 (`is_clear`, `is_stale`)
- `tests/test_cli_start_stop_toggle_status_doctor.py` lines 72-108 (`test_status_idle`, `test_status_active`, `test_status_active_but_transcripts_dir_empty`)

**STEPS:**
1. Edit the `status()` body in `mr/cli.py`: replace the `else:` branch so the live/stale decision is made on `is_stale(state)`. Suggested shape:
   ```python
   if state is None:
       typer.echo("recording: no")
   else:
       recording = not is_stale(state)
       typer.echo(f"recording: {'yes' if recording else 'no'}")
       typer.echo(f"pid: {state.pid}")
       typer.echo(f"out_dir: {state.out_dir}")
       typer.echo(f"stamp: {state.stamp}")
       typer.echo(f"started_at: {state.started_at}")
       if not recording:
           typer.echo("stale pidfile; run `mr stop` to clear", err=True)
   ```
2. Keep the transcript-section code (the `tdir` glob) byte-for-byte unchanged.
3. In the test file, the existing `test_status_active` and `test_status_active_but_transcripts_dir_empty` patch `read_state` to return a state but do NOT patch `is_stale`; they currently assert `recording: yes`. `is_stale(5566)` will do a real `os.kill(5566, 0)` which raises `ProcessLookupError` → `is_stale` returns True → under the new logic these tests would now expect `recording: no`. Patch `is_stale` in those two tests to return `False` so they keep asserting `recording: yes` (representing a live PID). Update the monkeypatch on `mr.cli.is_stale` accordingly.
4. Add a new test `test_status_stale_prints_no` (mirroring `test_status_active`): patch `read_state` to return the same state and patch `mr.cli.is_stale` to return `True`; assert output contains `recording: no`, still contains `pid:`/`out_dir:`/`stamp:`/`started_at:`, and assert the stale note is present. Assert the stale note appears on stderr (CliRunner captures both; `result.stderr` contains "stale pidfile").

**ACCEPTANCE:**
- `./spike/.venv/bin/python -m pytest tests/test_cli_start_stop_toggle_status_doctor.py -q` → all pass.
- `./spike/.venv/bin/python -m pytest tests/ -q` → 136 pass (135 existing + 1 new).
- `./spike/.venv/bin/ruff check mr tests` → clean.

**OUT OF SCOPE:**
- Do NOT change `_do_stop`, `toggle`, `clear_state`, `read_state`, or `is_stale` in `mr/state.py`.
- Do NOT change the transcript-section output logic, any other command, or the Swift app.
- Do NOT auto-clear the stale pidfile inside `status` (that stays a manual `mr stop` action; clearing-on-read is a separate decision not requested).
- No dependency upgrades, refactors, renames, or formatting of untouched code.

**REPORT:** Reply with STATUS (done/failed), FILES CHANGED, VERIFICATION (the commands above and their output), and NOTES.
