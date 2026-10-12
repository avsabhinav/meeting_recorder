# TASK: P1.1 — Scaffold production `mr` Python package

TASK: P1/1.1 Scaffold the production Python package for the meeting-recorder tool.

GOAL: A clean, installable Python package named `mr` with a `mr.core` subpackage,
ruff + pytest configured, a gitignore, LICENSE, README stub, and a `config.toml.example`.
Nothing functional yet — just the structure and tooling so later tasks drop modules in.

CONTEXT:
- This is a local-first macOS tool that records a 1:1 call (mic + system audio) and
  transcribes it locally to an attributed Markdown transcript. Full plan: `PLAN.md`.
- Working dir (workspace root): `/Users/abhinavademmagari/Documents/Projects/meeting recorder`
  (a path WITH spaces — quote it). A git repo already exists on branch `main`.
- Python 3.12+ (the machine has a working `spike/.venv` with CPython 3.12).
- The package layout must match this exact structure:
```
mr/
  __init__.py        # version string __version__ = "0.1.0"
  core/
    __init__.py
tests/
  __init__.py
  test_smoke.py      # trivial import test
examples/
  demo/
    README.md        # placeholder
docs/
  ...                # ALREADY EXISTS (docs/backlog/BACKLOG.md, docs/architecture.md) — LEAVE AS IS
pyproject.toml
ruff.toml            # (or config in pyproject) ruff settings
.gitignore           # extend the existing top-level gitignore
LICENSE              # MIT
README.md            # stub, will be expanded by a later task
config.toml.example  # documented sample config
```
- Each of `mr/__init__.py`, `mr/core/__init__.py`, `tests/__init__.py` should exist and be
  minimal (version string in `mr/__init__.py`).
- There is already a `spike/` directory (throwaway code) and `docs/` — do not touch them.
- A `.gitignore` may already exist at root (there is one inside `spike/`). Create/extend the
  top-level one.

pyproject.toml must include:
- `[project]` name `meeting-recorder`, version `0.1.0`, requires-python `>=3.12`,
  dependencies: `mlx-whisper>=0.4`, `typer>=0.12`, `soundfile>=0.12`,
  `rapidfuzz>=3.0`. (tomllib is stdlib → no dep needed for TOML parsing.)
- `[project.optional-dependencies] dev = ["pytest>=8", "ruff>=0.4"]`
- `[build-system]` using setuptools, and a `[tool.setuptools]` / `packages.find` config that
  includes `mr*`.
- `[tool.pytest.ini_options] testpaths = ["tests"]`, `pythonpath = ["."]`.
- `[tool.ruff]` sensible defaults: `line-length = 100`, `target-version = "py312"`;
  lint select = E,F,I,UP.

FILES (create or modify ONLY these):
- `/Users/abhinavademmagari/Documents/Projects/meeting recorder/pyproject.toml`
- `/Users/abhinavademmagari/Documents/Projects/meeting recorder/ruff.toml`
- `/Users/abhinavademmagari/Documents/Projects/meeting recorder/.gitignore`
- `/Users/abhinavademmagari/Documents/Projects/meeting recorder/LICENSE`
- `/Users/abhinavademmagari/Documents/Projects/meeting recorder/README.md`
- `/Users/abhinavademmagari/Documents/Projects/meeting recorder/config.toml.example`
- `/Users/abhinavademmagari/Documents/Projects/meeting recorder/mr/__init__.py`
- `/Users/abhinavademmagari/Documents/Projects/meeting recorder/mr/core/__init__.py`
- `/Users/abhinavademmagari/Documents/Projects/meeting recorder/tests/__init__.py`
- `/Users/abhinavademmagari/Documents/Projects/meeting recorder/tests/test_smoke.py`
- `/Users/abhinavademmagari/Documents/Projects/meeting recorder/examples/demo/README.md`

READ FIRST:
- `PLAN.md` (§6 repo layout) at repo root.
- `docs/architecture.md` (module map + deps).
- `spike/.gitignore` (contents to fold into top-level gitignore, minus the throwaway bits).

STEPS:
1. Create the directories `mr/core`, `tests`, `examples/demo` (mkdir -p).
2. Write `pyproject.toml` per the spec above (setuptools backend; packages.find includes `mr*`).
3. Write `ruff.toml` with line-length 100, target-version py312, select E,F,I,UP.
4. Write/extend top-level `.gitignore`: ignore `__pycache__/`, `*.pyc`, `.venv/`,
   `.DS_Store`, `dist/`, `build/`, `*.egg-info/`, `.pytest_cache/`, `.ruff_cache/`,
   `capture/.build/`, `examples/demo/output/`, and `spike/out/`. Keep existing entries.
5. Write `mr/__init__.py` (`__version__ = "0.1.0"`), `mr/core/__init__.py` (docstring only),
   `tests/__init__.py` (docstring only).
6. Write `tests/test_smoke.py`: asserts `import mr; assert mr.__version__ == "0.1.0"` and
   that `from mr.core import __name__` works (imports fine).
7. Write `LICENSE` (MIT, copyright year 2026, holder "Meeting Recorder contributors").
   Keep the notice short.
8. Write `README.md` stub: one-paragraph description + "record + transcribe to attributed
   Markdown, all local" + a "Developing" section with `pip install -e ".[dev]"`, `ruff
   check mr tests`, `pytest`.
9. Write `config.toml.example` with documented placeholder keys: `out_root =
   "~/Meetings"`, `model = "mlx-community/whisper-large-v3-turbo"`, `language = "en"`,
   `dedup_threshold = 0.6`, `keep_audio = true`, plus brief `#` comments.
10. `examples/demo/README.md`: brief placeholder ("demo outputs will live here").

ACCEPTANCE:
- `cd "/Users/abhinavademmagari/Documents/Projects/meeting recorder"` then:
  - `.venv/bin/python -c "import sys; sys.path.insert(0,'.'); import mr; print(mr.__version__)"`
    → prints `0.1.0`. (If there is no venv, use the `spike/.venv/bin/python` — it exists.)
  - `./spike/.venv/bin/python -m pytest -q` → ≥1 test passes.
  - `./spike/.venv/bin/python -m ruff check mr tests` → no errors (ruff must be installed;
    if not available in that venv, note it and ensure the config is syntactically valid).
  - All 11 listed files exist.

OUT OF SCOPE: Do NOT write any real logic (transcribe/merge/output/capture/config/state).
Do NOT touch `spike/`, `docs/`, `PLAN.md`, `PHASE0_SPIKE.md`, `Project Goal.md`. Do NOT create
the Swift package yet. Do NOT add the `typer` console-script entry point yet (that is a later task).

REPORT: reply with STATUS, FILES CHANGED, VERIFICATION (output of the commands above), NOTES.
