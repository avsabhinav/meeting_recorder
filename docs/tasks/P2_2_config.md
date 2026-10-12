TASK: P2.2 Create `mr/config.py` — TOML config loader

GOAL: A `Config` dataclass + loader that reads `~/.config/mr/config.toml` (falling back to
sane defaults when the file is missing or a key is absent), expands `~`/env in the `out_root`
path, validates types, and exposes the values the CLI + capture need: `out_root`, `model`,
`language`, `dedup_threshold`, `keep_audio`. This is the config layer P2.4 (`mr start/stop/
toggle/status/doctor`) and P2.2+ code will import — it must be pure, offline, and unit-testable.

CONTEXT:
- Repo: `meeting recorder/` (space in path — quote paths). Python 3.12+, stdlib only:
  `tomllib` (in 3.11+), `pathlib`, `os`, `dataclasses`. No new dependencies.
- Config lives at `~/.config/mr/config.toml` (per PLAN.md §4.5 and `docs/architecture.md`).
  Sample at repo `config.toml.example`:
  ```
  out_root = "~/Meetings"                       # recordings/ + transcripts/ under this
  model = "mlx-community/whisper-large-v3-turbo"
  language = "en"
  dedup_threshold = 0.6
  keep_audio = true
  ```
- Defaults (when file absent / key missing): `out_root="~/Meetings"`,
  `model=DEFAULT_MODEL` (import from `mr.core.transcribe`),
  `language="en"`, `dedup_threshold=0.6`, `keep_audio=True`.
  `out_root` must be `~`-expanded (`os.path.expanduser`) and made absolute
  (`Path(...).resolve()`); other paths/env in it are NOT expanded (keep simple).
- `DEFAULT_MODEL` lives in `mr.core.transcribe`: `DEFAULT_MODEL = "mlx-community/whisper-large-v3-turbo"`.
  Import it at module top (transcribe.py imports no heavy deps at top level — it only
  `import numpy/soundfile` — so importing it is safe and offline).
- Validation rules:
  - `model`: must be a non-empty str (else ValueError).
  - `language`: non-empty str (else ValueError).
  - `dedup_threshold`: float in [0.0, 1.0] (else ValueError).
  - `keep_audio`: coerce to bool; accept `true`/`false` (TOML) — keep it bool-native, raise
    if not a bool.
  - `out_root`: str (else ValueError).
- Unknown keys in the TOML are tolerated (ignore them) — forward-compatible cfg.
- The loader must NOT fail on network or I/O beyond reading the one file; a missing file is
  not an error (defaults). A present-but-malformed TOML *is* an error (propagate `tomllib.TOMLDecodeError`).

FILES (create only):
- `mr/config.py`
- `tests/test_config.py`

READ FIRST:
1. `config.toml.example` (repo root) — the exact keys/defaults to honor.
2. `mr/core/transcribe.py` line 38 — `DEFAULT_MODEL` (to import).
3. `docs/architecture.md` lines 9,16 — confirms `config.py` loads `~/.config/mr/config.toml`.
4. `tests/test_schema.py` — existing style conventions (imports/monkeypatch usage) to match.

STEPS:
1. Create `mr/config.py`:
   - `from __future__ import annotations`; `import os, tomllib`, `from dataclasses import dataclass, field`, `from pathlib import Path`.
   - `from mr.core.transcribe import DEFAULT_MODEL`.
   - `CONFIG_DIR = "~/.config/mr"` constant and `CONFIG_FILE = "config.toml"` (resolved path
     computed lazily/at call, not at import).
   - `@dataclass(frozen=True) class Config:` with fields exactly:
     `out_root: str`, `model: str`, `language: str`, `dedup_threshold: float`, `keep_audio: bool`.
     (No defaults on the dataclass itself — `load()` always populates all five.)
   - `def default_config() -> Config:` returns a `Config` built from the defaults above
     (out_root expanded + resolved).
   - `def load_config(path: str | Path | None = None) -> Config:`:
     - Determine real path: if `path` is None → `Path(os.path.expanduser(CONFIG_DIR)) / CONFIG_FILE`.
     - If the file does not exist: return `default_config()`.
     - Else read + `tomllib.loads` (or `tomllib.load`); on `TOMLDecodeError` propagate it.
     - Apply per-key overrides over the defaults; validate each as above (raise `ValueError`
       with a clear message naming the key and expected type/range).
     - `out_root`: expanduser + resolve before storing.
     - Return a `Config` with defaults for any key not present in the file.
   - Keep it a pure module: no I/O except reading the one TOML file; no CLI.
2. Write `tests/test_config.py` (offline, stdlib + `tomllib`, no network):
   - `test_missing_file_returns_defaults(tmp_path, monkeypatch)`: point path at a nonexistent
     TOML; `load_config` returns a `Config` equal to `default_config()`; assert each default.
   - `test_empty_file_returns_defaults`: write an empty `{}` (or a file with only comments);
     assert defaults.
   - `test_parses_all_keys`: write a TOML with all five keys set; assert the returned `Config`
     matches (including `out_root` being `~`-expanded + absolute).
   - `test_out_root_expansion`: set `out_root="~/Meetings"` and assert `Path(cfg.out_root)` starts
     with the expanded home and is absolute.
   - `test_unknown_keys_ignored`: add an unknown key; assert it's ignored (no error, defaults kept).
   - `test_invalid_dedup_raises` / `test_invalid_model_raises` (and one more type guard):
     pass a bad value (dedup > 1, empty model, non-bool keep_audio) and assert `ValueError`.
   - `test_malformed_toml_raises`: write malformed TOML; assert `tomllib.TOMLDecodeError`.
   - ~6-8 focused tests.
3. Run the suite + ruff on `mr/config.py` and `tests/test_config.py`.

ACCEPTANCE:
- `./spike/.venv/bin/python -m pytest tests/ -q` — all tests pass (existing 56 + your new).
- `./spike/.venv/bin/ruff check mr/config.py tests/test_config.py` — clean.
- `./spike/.venv/bin/python -c "from mr.config import Config, load_config, default_config; c=load_config(); print(c.out_root)"`
  works (reads no file if absent → prints expanded `~/Meetings`).
- Module imports nothing heavy (no mlx_whisper, no typer at top level).

OUT OF SCOPE:
- Do NOT add `state.py` (P2.3) or CLI wiring (P2.4). Do NOT modify `mr/core/*`, `mr/cli.py`,
  pyproject.toml, or any existing file.
- Do NOT read env vars for config (only `~` expansion in out_root). Do NOT add logging/CLI.
- Do NOT make `out_root` a Path object — keep it a `str` field (contract with P2.4).
- Do NOT commit (CTO agent owns git).

REPORT: reply with STATUS, FILES CHANGED, VERIFICATION (commands + output), NOTES.