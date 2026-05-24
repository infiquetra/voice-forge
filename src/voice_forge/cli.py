"""Command-line interface for voice-forge.

Phase D fills out implementations. This file is a skeleton.

Commands:
  voice-forge serve [--host 0.0.0.0 --port 9876]
  voice-forge synth <voice_id> <text-or-file-or-dash> [--out file.wav]
  voice-forge voices
  voice-forge voice add <voice_id> <ref.wav> [--ref-text "..."]
  voice-forge voice from-elevenlabs <voice_id> --elevenlabs-voice-id <id>
  voice-forge voice delete <voice_id>
"""

from __future__ import annotations

import sys

import click


@click.group()
@click.version_option(version="0.1.0.dev0")
def main() -> None:
    """voice-forge — pluggable TTS service for agent voices."""


@main.command()
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", default=9876, type=int, show_default=True)
def serve(host: str, port: int) -> None:
    """Run the voice-forge HTTP server."""
    # TODO Phase D: import + run uvicorn against server.app
    click.echo(f"voice-forge serve {host}:{port} — implementation pending (Phase D)", err=True)
    sys.exit(1)


@main.command()
@click.argument("voice_id")
@click.argument("text")
@click.option("--out", "out_path", default=None, help="Output WAV path")
def synth(voice_id: str, text: str, out_path: str | None) -> None:
    """Synthesize text directly via in-process backend (no server needed)."""
    # TODO Phase D: load voice from registry, call backend, write WAV
    click.echo(f"voice-forge synth {voice_id} — implementation pending (Phase D)", err=True)
    sys.exit(1)


@main.command()
def voices() -> None:
    """List registered voices."""
    # TODO Phase D
    click.echo("voice-forge voices — implementation pending (Phase D)", err=True)
    sys.exit(1)


@main.group()
def voice() -> None:
    """Voice management subcommands (add, delete, from-elevenlabs, retrim)."""


@voice.command("add")
@click.argument("voice_id")
@click.argument("ref_audio_path", type=click.Path(exists=True))
@click.option("--ref-text", default=None, help="Matching transcript (will Whisper-transcribe if absent)")
@click.option("--backend", default="neutts", show_default=True)
def voice_add(voice_id: str, ref_audio_path: str, ref_text: str | None, backend: str) -> None:
    """Add a voice from a local WAV file."""
    # TODO Phase D
    click.echo(f"voice-forge voice add — implementation pending (Phase D)", err=True)
    sys.exit(1)


@voice.command("from-elevenlabs")
@click.argument("voice_id")
@click.option("--elevenlabs-voice-id", required=True)
@click.option("--auto-trim/--no-auto-trim", default=True)
def voice_from_elevenlabs(voice_id: str, elevenlabs_voice_id: str, auto_trim: bool) -> None:
    """Pull a voice from ElevenLabs Voice Lab."""
    # TODO Phase D
    click.echo(f"voice-forge voice from-elevenlabs — implementation pending (Phase D)", err=True)
    sys.exit(1)


if __name__ == "__main__":
    main()
