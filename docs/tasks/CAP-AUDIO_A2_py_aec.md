TASK: CAP-AUDIO/A2 Remove the `--aec`/`--no-aec` plumbing from the Python CLI and capture wrapper
GOAL: `mr start` / `mr toggle` accept NO `--aec`/`--no-aec` option, and `RecordSession`/`_spawn_capture`/`_do_start` drop the `aec` parameter entirely. The CLI always records the raw mic (the Swift helper no longer supports voice processing). All Python tests are updated so pytest + ruff are green.
CONTEXT: This is a local-first macOS meeting recorder. `mr-capture` (Swift) previously took `--no-aec`; task A1 removed voice processing and the `--no-aec` flag from the binary (contract is now `mr-capture --out <dir>`, always raw mic). The Python layer still passes `--no-aec` and threads an `aec` flag through — it must be stripped here so the CLI never passes an unsupported flag. The `meta.json` `"aec"` key is KEPT (schema still parses it; it is unused by merge/output logic) — do NOT touch schema.py.

Below is the exact current code to change (from these files — read each file fully first):

mr/core/capture.py (relevant parts):
```python
    def __init__(
        self,
        out_dir: str,
        *,
        aec: bool = True,
        capture_bin: str | None = None,
    ) -> None:
        self.out_dir = str(Path(out_dir).resolve())
        self.aec = aec
        self.capture_bin = capture_bin
        self.proc: subprocess.Popen[bytes] | None = None
        self.meta: CaptureMeta | None = None
        self.returncode: int = -1
...
        os.makedirs(self.out_dir, exist_ok=True)
        cmd = [bin_path, "--out", self.out_dir]
        if not self.aec:
            cmd.append("--no-aec")
        self.proc = subprocess.Popen(cmd)
        return self
```

mr/cli.py (relevant parts):
```python
def _spawn_capture(out_dir: str, binary: str, aec: bool) -> int:
    """Spawn the (long-lived) ``mr-capture`` helper and return its PID.

    The child must outlive this short-lived CLI process, so it is started
    with ``subprocess.Popen`` and not reaped here; the PID is persisted to
    the state pidfile by the caller.
    """
    p = subprocess.Popen([binary, "--out", out_dir] + ([] if aec else ["--no-aec"]))
    return p.pid
```
```python
def _do_start(cfg: Config, aec: bool) -> None:
    """Start a capture (shared by ``start`` and ``toggle``)."""
    if not is_clear(cfg.out_root):
        state = read_state(cfg.out_root)
        stamp = state.stamp if state is not None else "?"
        out_dir = state.out_dir if state is not None else "?"
        typer.echo(f"already recording (stamp {stamp}, out_dir {out_dir})")
        return

    stamp = new_stamp()
    out_dir = _recordings_dir(cfg) / stamp
    out_dir.mkdir(parents=True, exist_ok=True)
    binary = assert_capture_bin()
    pid = _spawn_capture(str(out_dir), binary, aec)
    write_state(cfg.out_root, pid, str(out_dir), stamp, datetime.now().isoformat())
    typer.echo(f"recording started (stamp {stamp})\nout_dir: {out_dir}")
```
```python
@app.command()
def start(
    aec: Annotated[
        bool, typer.Option("--aec/--no-aec", help="Enable AEC on the capture helper")
    ] = True,
) -> None:
    """Start recording (spawns ``mr-capture``; it keeps running after exit)."""
    _do_start(load_config(), aec)
```
```python
@app.command()
def toggle(
    aec: Annotated[bool, typer.Option("--aec/--no-aec", help="AEC when starting")] = True,
    json: Annotated[bool, typer.Option("--json", help="JSON sidecar when stopping")] = False,
) -> None:
    """Start recording if idle, otherwise stop it and write the transcript."""
    cfg = load_config()
    state = read_state(cfg.out_root)
    if state is None or is_clear(cfg.out_root) or is_stale(state):
        _do_start(cfg, aec)
    else:
        _do_stop(cfg, json)
```

tests/test_capture.py (current asserts to update):
```python
def test_enter_creates_outdir_and_spawns(...):
    ...
    session = RecordSession(str(out_dir), aec=False)
    with session:
        pass
    ...
    assert args[1:3] == ["--out", abs_outdir]
    assert "--no-aec" in args
```
```python
def test_enter_args_default_aec(...):
    ...
    with RecordSession(str(tmp_path / "rec")):
        pass
    args = popen.call_args[0][0]
    assert "--no-aec" not in args
```
(The `SAMPLE_META` dict keeps `"aec": True` — schema tolerates it, no change needed; `RecordSession(str(...), aec=False)` calls must drop the `aec=False` kwarg.)

tests/test_cli_start_stop_toggle_status_doctor.py (current asserts to update):
```python
def test_start_happy(cfg, monkeypatch) -> None:
    monkeypatch.setattr(mr.cli, "_spawn_capture", lambda out_dir, binary, aec: 5566)
```
```python
def test_toggle_idle_starts(cfg, monkeypatch) -> None:
    ...
    def _spawn(out_dir: str, binary: str, aec: bool) -> int:
        spawned.append((out_dir, binary, aec))
        return 5566
    monkeypatch.setattr(mr.cli, "_spawn_capture", _spawn)
    ...
    assert spawned[0][2] is True  # aec default
```
FILES (create/modify ONLY these): mr/core/capture.py, mr/cli.py, tests/test_capture.py, tests/test_cli_start_stop_toggle_status_doctor.py
READ FIRST:
- mr/core/capture.py (142 lines) — note the module docstring at the top mentions `[--no-aec]`; update it to `--out <dir>`.
- mr/cli.py (439 lines) — only the lines above; also check the module docstring/README_refs for `--no-aec` mentions in comments and remove them. Do NOT change the CLI commands' core behavior, `_do_stop`, heartbeat, or status.
- tests/test_capture.py and tests/test_cli_start_stop_toggle_status_doctor.py — read fully; update every `aec`-related call/assert.
STEPS:
1. `mr/core/capture.py`: change `RecordSession.__init__` to `(self, out_dir, *, capture_bin: str | None = None)`; remove `self.aec`; in `__enter__` remove the `if not self.aec: cmd.append("--no-aec")` block (keep `cmd = [bin_path, "--out", self.out_dir]`). Update the module docstring `mr-capture --out <dir> [--no-aec]` → `mr-capture --out <dir>`.
2. `mr/cli.py`: `_spawn_capture(out_dir: str, binary: str) -> int` with body `subprocess.Popen([binary, "--out", out_dir])`; `_do_start(cfg: Config)` (drop `aec`), body uses `pid = _spawn_capture(str(out_dir), binary)`; `start` command drops its `aec` param (just `def start() -> None:` calling `_do_start(load_config())`); `toggle` drops its `aec` param (keep `json`), calling `_do_start(cfg)`. Remove any `--no-aec`/aec mentions in the module docstring or comments.
3. `tests/test_capture.py`: `RecordSession(str(out_dir), aec=False)` → `RecordSession(str(out_dir))`; remove the `assert "--no-aec" in args` line; `test_enter_args_default_aec` → rename to `test_enter_args_plain` (or similar), body keeps `args[1:3] == ["--out", abs...]` and asserts there is NO third arg (e.g. `assert len(args) == 3` i.e. `[bin, "--out", dir]`). Keep `SAMPLE_META` as-is.
4. `tests/test_cli_...py`: `test_start_happy` → `_spawn_capture = lambda out_dir, binary: 5566`; `test_toggle_idle_starts` → `_spawn(out_dir, binary)` appending `(out_dir, binary)` and `assert spawned[0][1] == "/x/mr-capture"` (drop the aec assert). Check for any other `aec`/`--aec` references and remove them.
5. Run the acceptance commands below.
ACCEPTANCE:
1. `cd "/Users/abhinavademmagari/Documents/Projects/meeting recorder" && ./spike/.venv/bin/python -m pytest tests/test_capture.py tests/test_cli_start_stop_toggle_status_doctor.py -q` → all pass (report the count).
2. `cd "/Users/abhinavademmagari/Documents/Projects/meeting recorder" && ./spike/.venv/bin/python -m pytest tests/ -q` → all pass (report total).
3. `cd "/Users/abhinavademmagari/Documents/Projects/meeting recorder" && ./spike/.venv/bin/ruff check mr tests` → clean.
4. `cd "/Users/abhinavademmagari/Documents/Projects/meeting recorder" && ./spike/.venv/bin/python -c "import re,pathlib; [print(p, len(re.findall(r'(?i)aec|no-aec', pathlib.Path(p).read_text()))) for p in ['mr/cli.py','mr/core/capture.py','tests/test_capture.py','tests/test_cli_start_stop_toggle_status_doctor.py']]"` → each prints 0 (no `aec`/`no-aec` matches left; if any >0, they must be only in a comment that is acceptable, but prefer zero).
OUT OF SCOPE: `mr/core/schema.py`, `mr/config.py`, Swift files, any other module. Do not reformat untouched code lines.
REPORT: reply with STATUS, FILES CHANGED, VERIFICATION (pytest totals, ruff, the grep count line), and NOTES.