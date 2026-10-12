"""TOML configuration loader for meeting-recorder.

Reads ``~/.config/mr/config.toml`` (see ``config.toml.example``), falling back
to sane defaults when the file or individual keys are absent, and can
atomically write ``out_root`` back to the file (``set_out_root``). Pure and
offline: the only I/O is on the single config file; no CLI, no env vars
(besides ``~`` expansion of ``out_root``).
"""

from __future__ import annotations

import os
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path

from mr.core.transcribe import DEFAULT_MODEL

#: Default location of the config file (resolved per-user at load time).
CONFIG_DIR = "~/.config/mr"

DEFAULT_LANGUAGE = "en"
DEFAULT_DEDUP_THRESHOLD = 0.6
DEFAULT_OUT_ROOT = "~/Meetings"


@dataclass(frozen=True)
class Config:
    """Resolved settings for capture + transcription.

    ``out_root`` is an absolute, ``~``-expanded string path holding
    ``recordings/`` and ``transcripts/``.
    """

    out_root: str
    model: str
    language: str
    dedup_threshold: float
    keep_audio: bool


def _resolve_out_root(value: object) -> str:
    """Validate ``out_root`` and return it expanded + resolved as a string."""
    if not isinstance(value, str) or not value:
        raise ValueError(
            f"out_root must be a non-empty string (path), got {type(value).__name__}"
        )
    return str(Path(os.path.expanduser(value)).resolve())


def _nonempty_str(key: str, value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{key} must be a non-empty string, got {type(value).__name__}")
    return value


def _dedup_threshold(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(
            f"dedup_threshold must be a number in [0.0, 1.0], got {type(value).__name__}"
        )
    threshold = float(value)
    if not 0.0 <= threshold <= 1.0:
        raise ValueError(f"dedup_threshold must be in [0.0, 1.0], got {threshold}")
    return threshold


def _keep_audio(value: object) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"keep_audio must be a boolean, got {type(value).__name__}")
    return value


def default_config() -> Config:
    """The built-in defaults (used when the config file or a key is absent)."""
    return Config(
        out_root=_resolve_out_root(DEFAULT_OUT_ROOT),
        model=DEFAULT_MODEL,
        language=DEFAULT_LANGUAGE,
        dedup_threshold=DEFAULT_DEDUP_THRESHOLD,
        keep_audio=True,
    )


def _config_path() -> Path:
    return Path(os.path.expanduser(CONFIG_DIR)) / "config.toml"


def load_config(path: str | Path | None = None) -> Config:
    """Load a :class:`Config` from TOML.

    Reads ``path`` if given, else ``~/.config/mr/config.toml``. A missing
    file yields :func:`default_config`. Unknown keys are ignored; malformed
    TOML propagates :class:`tomllib.TOMLDecodeError`; invalid values raise
    :class:`ValueError` naming the offending key.
    """
    real_path = Path(path) if path is not None else _config_path()
    defaults = default_config()
    if not real_path.is_file():
        return defaults

    with real_path.open("rb") as fh:
        data = tomllib.load(fh)

    out_root = data.get("out_root")
    model = data.get("model")
    language = data.get("language")
    dedup_threshold = data.get("dedup_threshold")
    keep_audio = data.get("keep_audio")

    return Config(
        out_root=_resolve_out_root(out_root) if out_root is not None else defaults.out_root,
        model=_nonempty_str("model", model) if model is not None else defaults.model,
        language=(
            _nonempty_str("language", language)
            if language is not None
            else defaults.language
        ),
        dedup_threshold=(
            _dedup_threshold(dedup_threshold)
            if dedup_threshold is not None
            else defaults.dedup_threshold
        ),
        keep_audio=_keep_audio(keep_audio) if keep_audio is not None else defaults.keep_audio,
    )


def _atomic_write(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` atomically (temp file + ``os.replace``)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())  # best-effort durability before the rename
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _format_toml_value(value: object) -> str:
    """Render a scalar (or nested array/table) as a TOML value literal."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        escaped = (
            value.replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("\n", "\\n")
            .replace("\r", "\\r")
            .replace("\t", "\\t")
        )
        return f'"{escaped}"'
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_format_toml_value(item) for item in value) + "]"
    if isinstance(value, dict):
        return (
            "{"
            + ", ".join(f"{key} = {_format_toml_value(item)}" for key, item in value.items())
            + "}"
        )
    raise TypeError(f"cannot serialize {type(value).__name__} as a TOML value")


def set_out_root(path: str, *, config_path: str | Path | None = None) -> str:
    """Set ``out_root`` in the config TOML and return the resolved path.

    Validates ``path`` via :func:`_resolve_out_root` (raises
    :class:`ValueError` for empty/non-string input) and atomically rewrites
    ONLY the ``out_root`` key of the target file (``config_path``, or
    ``~/.config/mr/config.toml`` when ``None``), preserving every other key
    and its value/type. A missing or empty file is written with the defaults
    (see :func:`default_config`) plus the new ``out_root``. After the call,
    ``load_config(config_path).out_root`` equals the returned string.
    """
    new_root = _resolve_out_root(path)
    target = Path(config_path) if config_path is not None else _config_path()

    data: dict[str, object] = {}
    if target.is_file():
        with target.open("rb") as fh:
            data = tomllib.load(fh)

    if not data:  # missing or empty file: seed the documented defaults
        defaults = default_config()
        data = {
            "out_root": None,
            "model": defaults.model,
            "language": defaults.language,
            "dedup_threshold": defaults.dedup_threshold,
            "keep_audio": defaults.keep_audio,
        }
    data["out_root"] = new_root

    text = "\n".join(f"{key} = {_format_toml_value(value)}" for key, value in data.items()) + "\n"
    _atomic_write(target, text)
    return new_root
