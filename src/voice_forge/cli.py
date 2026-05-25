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
from .backends import known_backends, load_backend_module


def _load_backend_or_exit(backend_name: str) -> None:
    """Import the named backend module; sys.exit(2) with a friendly message on failure.

    Used by CLI commands that absolutely need the backend (synth). The `health`
    command catches the underlying KeyError/ImportError directly so it can keep
    reporting state even when a backend isn't installed.
    """
    try:
        load_backend_module(backend_name)
    except KeyError:
        click.echo(
            f"error: unknown backend {backend_name!r}; known: {known_backends()}",
            err=True,
        )
        sys.exit(2)
    except ImportError as exc:
        click.echo(
            f"error: backend {backend_name!r} known but not installed; "
            f"install with `pip install voice-forge-tts[{backend_name}]` ({exc})",
            err=True,
        )
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

    _load_backend_or_exit(ref.backend)
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


def _parse_sampling_value(s: str) -> int | float | str | bool:
    """Coerce a CLI string value to its narrowest numeric type, fallback string.

    Examples:
        "42"   → 42  (int)
        "1.5"  → 1.5 (float)
        "true" → True (bool)
        "none" → None
        "af_bella" → "af_bella" (str)
    """
    low = s.strip().lower()
    if low in ("true", "yes"):
        return True
    if low in ("false", "no"):
        return False
    if low in ("none", "null"):
        return None  # type: ignore[return-value]
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        pass
    return s


def _parse_sampling_kv(items: tuple[str, ...]) -> dict:
    """Parse repeatable ``--sampling key=value`` flags into a dict."""
    out: dict = {}
    for item in items:
        if "=" not in item:
            raise click.BadParameter(
                f"--sampling expects key=value, got: {item!r}",
                param_hint="--sampling",
            )
        key, _, val = item.partition("=")
        out[key.strip()] = _parse_sampling_value(val)
    return out


@voice.command("add")
@click.argument("voice_id")
@click.argument(
    "ref_audio_path",
    required=False,
    type=click.Path(exists=True, dir_okay=False),
    default=None,
)
@click.option(
    "--ref-text", default=None, help="Matching transcript (will Whisper-transcribe if absent)"
)
@click.option(
    "--preset",
    "preset_id",
    default=None,
    help="Preset voice name for backends that don't use ref audio (e.g. kokoro 'af_bella')",
)
@click.option("--backend", default="f5", show_default=True)
@click.option("--language", default="en", show_default=True)
@click.option("--description", default="")
@click.option(
    "--sampling",
    "sampling_overrides",
    multiple=True,
    metavar="KEY=VALUE",
    help=(
        "Per-voice sampling override; repeat for multiple keys. Examples: "
        "--sampling speed=1.1 --sampling seed=42. Values are coerced "
        "int/float/bool/None when possible; otherwise treated as strings. "
        "See docs/BACKENDS.md for per-backend tunables."
    ),
)
@click.option("--overwrite", is_flag=True, help="Replace existing voice with same id")
def voice_add(
    voice_id: str,
    ref_audio_path: str | None,
    ref_text: str | None,
    preset_id: str | None,
    backend: str,
    language: str,
    description: str,
    sampling_overrides: tuple[str, ...],
    overwrite: bool,
) -> None:
    """Add a voice — from a ref WAV (cloning backends) OR a --preset name (preset backends)."""
    from .registry import Registry

    if not ref_audio_path and not preset_id:
        click.echo(
            "error: provide either REF_AUDIO_PATH (for cloning backends like neutts) "
            "or --preset <name> (for preset backends like kokoro).",
            err=True,
        )
        sys.exit(2)
    if ref_audio_path and preset_id:
        click.echo(
            "error: REF_AUDIO_PATH and --preset are mutually exclusive — pick one.",
            err=True,
        )
        sys.exit(2)

    metadata: dict = {"language": language, "description": description}
    if preset_id:
        metadata["preset_id"] = preset_id
    if sampling_overrides:
        metadata["sampling"] = _parse_sampling_kv(sampling_overrides)

    if ref_audio_path and ref_text is None:
        click.echo("Whisper-transcribing ref audio (forced language=en)...", err=True)
        from .voice_lab.whisper import transcribe

        ref_text = transcribe(ref_audio_path, language=language)
        click.echo(f"  transcript: {ref_text!r}", err=True)

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
    suffix_bits = []
    if preset_id:
        suffix_bits.append(f"preset={preset_id!r}")
    if sampling_overrides:
        suffix_bits.append(f"sampling={metadata['sampling']!r}")
    suffix = " " + " ".join(suffix_bits) if suffix_bits else ""
    click.echo(f"registered {ref.voice_id} (backend={ref.backend}){suffix}")


@voice.command("tune")
@click.argument("voice_id")
@click.option(
    "--sampling",
    "sampling_overrides",
    multiple=True,
    metavar="KEY=VALUE",
    help=(
        "Sampling-param override; repeat for multiple keys. Existing keys are "
        "preserved unless explicitly overwritten here."
    ),
)
@click.option(
    "--clear-sampling",
    is_flag=True,
    help="Remove the entire sampling block (resets to backend defaults).",
)
def voice_tune(
    voice_id: str,
    sampling_overrides: tuple[str, ...],
    clear_sampling: bool,
) -> None:
    """Adjust the per-voice sampling params on an already-registered voice.

    Examples:
        voice-forge voice tune saga-comms-f5 --sampling cfg_strength=2.5 --sampling seed=42
        voice-forge voice tune heid-research-dia --sampling max_new_tokens=8192
        voice-forge voice tune saga-comms-f5 --clear-sampling
    """
    from .registry import Registry

    if not sampling_overrides and not clear_sampling:
        click.echo(
            "error: pass at least one --sampling key=value (or --clear-sampling to reset).",
            err=True,
        )
        sys.exit(2)
    if sampling_overrides and clear_sampling:
        click.echo(
            "error: --sampling and --clear-sampling are mutually exclusive.",
            err=True,
        )
        sys.exit(2)

    overrides = _parse_sampling_kv(sampling_overrides) if sampling_overrides else None
    registry = Registry()
    try:
        ref = registry.tune(voice_id, sampling_overrides=overrides, clear=clear_sampling)
    except KeyError as exc:
        click.echo(f"error: {exc}", err=True)
        sys.exit(1)
    new_sampling = ref.metadata.get("sampling") or "(cleared)"
    click.echo(f"tuned {voice_id} sampling={new_sampling!r}")


@voice.command("from-elevenlabs")
@click.argument("voice_id")
@click.option("--elevenlabs-voice-id", required=True, help="Source voice in ElevenLabs")
@click.option("--api-key", default=None, help="ElevenLabs API key (or set ELEVENLABS_API_KEY env)")
@click.option("--backend", default="f5", show_default=True)
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

    # Trigger backend module imports so they self-register. Missing-backend
    # is fine for a health check — we still want to report what IS available.
    for backend_name in known_backends():
        try:
            load_backend_module(backend_name)
        except (KeyError, ImportError):
            pass

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
