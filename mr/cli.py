"""`mr` command-line interface (typer app).

Currently exposes the ``process`` subcommand: transcribe an existing
``--mic``/``--system`` 16 kHz mono WAV pair with the production core, merge
with echo dedup, and write the attributed Markdown transcript (plus optional
JSON sidecar).

Further subcommands (``start``/``stop``/``toggle``/``status``/``doctor``) are
added to this same :data:`app` object — see the P2.4 brief.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from mr.core.merge import merge_transcripts
from mr.core.output import (
    render_transcript_json,
    render_transcript_md,
    write_json,
    write_transcript,
)
from mr.core.transcribe import DEFAULT_MODEL, ModelNotCachedError, transcribe_audio

app = typer.Typer(help="Local-first meeting recorder: capture and transcribe 1:1 calls.")


@app.callback()
def _root() -> None:
    """Keep the app multi-command even while only ``process`` exists.

    Without a callback (or a second command), typer collapses a single-command
    app into that command itself, breaking ``mr process``. P2.4 will add
    ``start``/``stop``/``toggle``/``status``/``doctor`` here.
    """
    return None


@app.command()
def process(
    mic: Annotated[Path, typer.Option("--mic", help="You-side 16 kHz mono mic WAV")],
    system: Annotated[
        Path, typer.Option("--system", help="Them-side 16 kHz mono system WAV")
    ],
    model: Annotated[str, typer.Option(help="HF model id")] = DEFAULT_MODEL,
    language: Annotated[str, typer.Option(help="Language code")] = "en",
    dedup_threshold: Annotated[
        float, typer.Option("--dedup-threshold", min=0.0, max=1.0)
    ] = 0.6,
    json: Annotated[bool, typer.Option("--json", help="Also write a JSON sidecar")] = False,
    stamp: Annotated[str, typer.Option(help="Stamp/label for the transcript")] = "",
    out_dir: Annotated[
        Path | None, typer.Option("--out-dir", help="Directory for transcript.md/json")
    ] = None,
) -> None:
    """Transcribe both WAVs, merge with echo dedup, and write the transcript."""
    for label, path in (("--mic", mic), ("--system", system)):
        if not path.is_file():
            raise typer.BadParameter(f"{label} file not found: {path}")

    try:
        you = transcribe_audio(str(mic), speaker="You", model=model, language=language)
        them = transcribe_audio(str(system), speaker="Them", model=model, language=language)
    except ModelNotCachedError as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(code=3) from e

    merged = merge_transcripts(
        list(you.segments), list(them.segments), dedup_threshold=dedup_threshold
    )
    duration = max((s.end for s in list(you.segments) + list(them.segments)), default=0.0)

    out = out_dir or system.parent
    stamp = stamp or system.stem
    md_path = out / f"{stamp}.md"
    write_transcript(
        md_path,
        render_transcript_md(
            stamp=stamp,
            source_dir=f"recordings/{stamp}",
            segments=merged,
            duration_seconds=duration,
        ),
    )
    typer.echo(f"wrote {md_path}")
    if json:
        json_path = out / f"{stamp}.json"
        write_json(json_path, render_transcript_json(merged, stamp=stamp))
        typer.echo(f"wrote {json_path}")
    typer.echo(f"kept {len(merged)} segments")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
