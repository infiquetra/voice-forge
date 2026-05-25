"""Command-line interface for voice-forge.

Commands:
    voice-forge serve [--host 0.0.0.0 --port 9876]
    voice-forge synth <voice_id> <text-or-file-or-dash> [--out file.wav]
    voice-forge voices
    voice-forge voice add <voice_id> <ref.wav> [--ref-text "..." --backend neutts]
    voice-forge voice from-elevenlabs <voice_id> --elevenlabs-voice-id <id>
    voice-forge voice delete <voice_id>
    voice-forge health
"""

from __future__ import annotations

import json
import sys
import time
import wave
from pathlib import Path

import click
import numpy as np

from . import __version__


def _import_backend(backend_name: str):
    """Import a backend module to trigger its register_backend() call."""
    if backend_name == "neutts":
        from .backends import neutts  # noqa: F401 — triggers register
    # Add other backend imports here as they ship
    else:
        click.echo(f"Unknown backend: {backend_name}", err=True)
        sys.exit(2)


def _write_wav(path: Path, samples: np.ndarray, sample_rate: int = 24_000) -> None:
    """Write float32 PCM array to a WAV file (16-bit int)."""
    pcm = (np.clip(samples.flatten(), -1.0, 1.0) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(sample_rate)
        f.writeframes(pcm.tobytes())


def _resolve_text_arg(text_arg: str) -> str:
    """Allow text input as: literal string | path to file | '-' for stdin."""
    if text_arg == "-":
        return sys.stdin.read().strip()
    p = Path(text_arg).expanduser()
    if p.exists() and p.is_file():
        return p.read_text().strip()
    return text_arg


@click.group()
@click.version_option(version=__version__, prog_name="voice-forge")
def main() -> None:
    """voice-forge — pluggable TTS service for agent voices."""


# ----- serve -----


@main.command()
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", default=9876, type=int, show_default=True)
@click.option("--reload", is_flag=True, help="Reload server on code changes (dev only)")
def serve(host: str, port: int, reload: bool) -> None:
    """Run the voice-forge HTTP server."""
    import uvicorn

    uvicorn.run("voice_forge.server:app", host=host, port=port, reload=reload)


# ----- synth -----


@main.command()
@click.argument("voice_id")
@click.argument("text")
@click.option(
    "--out",
    "out_path",
    default=None,
    help="Output WAV path (default: /tmp/voice_forge_<voice>_<ts>.wav)",
)
def synth(voice_id: str, text: str, out_path: str | None) -> None:
    """Synthesize text directly via in-process backend (no server needed).

    This is the "test loop" that voice-forge is explicitly designed for —
    text in, WAV out, no Discord or chat platform required.

    Example:
        voice-forge synth example "Hello world." /tmp/probe.wav
        voice-forge synth saga - < story.txt
    """
    from .registry import Registry

    resolved_text = _resolve_text_arg(text)
    if not resolved_text:
        click.echo("error: empty text", err=True)
        sys.exit(1)

    registry = Registry()
    try:
        ref = registry.get(voice_id)
    except KeyError:
        click.echo(
            f"error: voice {voice_id!r} not in registry. Run `voice-forge voices` to list.",
            err=True,
        )
        sys.exit(1)

    _import_backend(ref.backend)
    from .backends import get_backend

    backend_cls = get_backend(ref.backend)
    backend = backend_cls()
    click.echo(f"loading {ref.backend} backend...", err=True)
    t_load = time.time()
    backend.load(ref.metadata)
    click.echo(f"  loaded in {time.time() - t_load:.2f}s", err=True)

    if out_path is None:
        out_path = f"/tmp/voice_forge_{voice_id}_{int(time.time())}.wav"
    out = Path(out_path).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)

    click.echo(f"synthesizing {len(resolved_text)} chars → {out}...", err=True)
    t_synth = time.time()
    audio = backend.synthesize(resolved_text, ref)
    synth_sec = time.time() - t_synth
    audio_sec = len(audio) / 24_000.0
    rtf = synth_sec / max(audio_sec, 0.01)

    _write_wav(out, audio)
    click.echo(
        f"  synth={synth_sec:.2f}s audio={audio_sec:.2f}s RTF={rtf:.2f} → {out}",
        err=True,
    )
    click.echo(str(out))


# ----- voices (list) -----


@main.command()
def voices() -> None:
    """List registered voices."""
    from .registry import Registry

    registry = Registry()
    items = registry.list()
    if not items:
        click.echo("(no voices registered)")
        click.echo(
            "Hint: `voice-forge voice add <id> <ref.wav>` or "
            "`voice-forge voice from-elevenlabs <id> --elevenlabs-voice-id <eid>`",
            err=True,
        )
        return
    for ref in items:
        click.echo(
            f"{ref.voice_id:30s} backend={ref.backend:10s} "
            f"lang={ref.metadata.get('language', '?'):5s} "
            f"{ref.metadata.get('description', '')}"
        )


# ----- voice (subgroup) -----


@main.group()
def voice() -> None:
    """Voice management subcommands (add, delete, from-elevenlabs)."""


@voice.command("add")
@click.argument("voice_id")
@click.argument("ref_audio_path", type=click.Path(exists=True, dir_okay=False))
@click.option(
    "--ref-text", default=None, help="Matching transcript (will Whisper-transcribe if absent)"
)
@click.option("--backend", default="neutts", show_default=True)
@click.option("--language", default="en", show_default=True)
@click.option("--description", default="")
@click.option("--overwrite", is_flag=True, help="Replace existing voice with same id")
def voice_add(
    voice_id: str,
    ref_audio_path: str,
    ref_text: str | None,
    backend: str,
    language: str,
    description: str,
    overwrite: bool,
) -> None:
    """Add a voice from a local WAV file."""
    from .registry import Registry

    if ref_text is None:
        click.echo("Whisper-transcribing ref audio (forced language=en)...", err=True)
        from .voice_lab.whisper import transcribe

        ref_text = transcribe(ref_audio_path, language=language)
        click.echo(f"  transcript: {ref_text!r}", err=True)

    metadata = {"language": language, "description": description}
    registry = Registry()
    try:
        ref = registry.register(
            voice_id=voice_id,
            ref_audio_path=ref_audio_path,
            ref_text=ref_text,
            backend=backend,
            metadata=metadata,
            overwrite=overwrite,
        )
    except FileExistsError as exc:
        click.echo(f"error: {exc}. Re-run with --overwrite to replace.", err=True)
        sys.exit(1)
    click.echo(f"registered {ref.voice_id} (backend={ref.backend})")


@voice.command("from-elevenlabs")
@click.argument("voice_id")
@click.option("--elevenlabs-voice-id", required=True, help="Source voice in ElevenLabs")
@click.option("--api-key", default=None, help="ElevenLabs API key (or set ELEVENLABS_API_KEY env)")
@click.option("--backend", default="neutts", show_default=True)
@click.option("--max-seconds", default=14.0, type=float, show_default=True)
@click.option("--no-trim", is_flag=True, help="Skip sentence-boundary trim; use full preview")
@click.option("--language", default="en", show_default=True)
@click.option("--overwrite", is_flag=True)
def voice_from_elevenlabs(
    voice_id: str,
    elevenlabs_voice_id: str,
    api_key: str | None,
    backend: str,
    max_seconds: float,
    no_trim: bool,
    language: str,
    overwrite: bool,
) -> None:
    """Pull a voice from ElevenLabs Voice Lab.

    Downloads the FROZEN preview MP3 (not fresh synthesis — fresh synth strips
    the accent that was in the Voice Design preview). Optionally trims to a
    clean sentence boundary via Whisper.
    """
    from .registry import Registry
    from .voice_lab.elevenlabs import pull_and_prepare

    click.echo(f"pulling preview for ElevenLabs voice {elevenlabs_voice_id}...", err=True)
    trim_arg = None if no_trim else max_seconds
    wav_path, ref_text = pull_and_prepare(
        voice_id=elevenlabs_voice_id,
        api_key=api_key,
        trim_to_seconds=trim_arg,
    )
    click.echo(f"  ref WAV: {wav_path}", err=True)
    click.echo(f"  ref text: {ref_text!r}", err=True)

    registry = Registry()
    metadata = {
        "language": language,
        "source": f"elevenlabs:{elevenlabs_voice_id}",
    }
    try:
        ref = registry.register(
            voice_id=voice_id,
            ref_audio_path=wav_path,
            ref_text=ref_text,
            backend=backend,
            metadata=metadata,
            overwrite=overwrite,
        )
    except FileExistsError as exc:
        click.echo(f"error: {exc}. Re-run with --overwrite to replace.", err=True)
        sys.exit(1)
    click.echo(f"registered {ref.voice_id} (backend={ref.backend})")


@voice.command("delete")
@click.argument("voice_id")
def voice_delete(voice_id: str) -> None:
    """Remove a voice from the registry."""
    from .registry import Registry

    registry = Registry()
    if not registry.exists(voice_id):
        click.echo(f"voice {voice_id!r} not in registry", err=True)
        sys.exit(1)
    registry.delete(voice_id)
    click.echo(f"deleted {voice_id}")


@voice.command("retrim")
@click.argument("voice_id")
@click.option("--max-seconds", default=14.0, type=float, show_default=True)
@click.option("--language", default="en", show_default=True)
def voice_retrim(voice_id: str, max_seconds: float, language: str) -> None:
    """Re-trim an existing voice's ref WAV to a clean sentence boundary."""
    from .registry import Registry
    from .voice_lab.whisper import trim_to_sentence_boundary

    registry = Registry()
    ref = registry.get(voice_id)
    if ref.ref_audio_path is None:
        click.echo(f"voice {voice_id!r} has no ref_audio (preset voice?)", err=True)
        sys.exit(1)
    _, new_text = trim_to_sentence_boundary(
        ref.ref_audio_path,
        max_seconds=max_seconds,
        language=language,
    )
    registry.register(
        voice_id=voice_id,
        ref_audio_path=ref.ref_audio_path,
        ref_text=new_text,
        backend=ref.backend,
        metadata=ref.metadata,
        overwrite=True,
    )
    click.echo(f"re-trimmed {voice_id} → text: {new_text!r}")


# ----- health -----


@main.command()
def health() -> None:
    """Report local voice-forge state (registry voices + available backends)."""
    from .backends import available_backends
    from .registry import Registry

    # Trigger backend module imports so they self-register
    try:
        _import_backend("neutts")
    except SystemExit:
        pass  # Backend missing is fine for a health check

    registry = Registry()
    info = {
        "version": __version__,
        "registry_dir": str(registry.root),
        "voices_count": len(registry.list()),
        "backends_available": available_backends(),
    }
    click.echo(json.dumps(info, indent=2))


if __name__ == "__main__":
    main()
