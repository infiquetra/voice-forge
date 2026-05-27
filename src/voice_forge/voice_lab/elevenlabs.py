"""ElevenLabs Voice Lab puller.

Downloads the FROZEN preview MP3 for a given voice — NOT a fresh synthesis.
This is the key insight from the home-lab NeuTTS investigation 2026-05-24:
ElevenLabs's API synthesis strips the accent that was present in the original
Voice Design preview. Pulling the preview MP3 preserves the accent for cloning.

Flow:
    1. GET /v1/voices/{voice_id} from ElevenLabs API → preview_url
    2. Download MP3 from preview_url
    3. ffmpeg convert to 24kHz mono WAV
    4. Caller can then run voice_lab.whisper.trim_to_sentence_boundary()
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

ELEVENLABS_VOICE_ENDPOINT = "https://api.elevenlabs.io/v1/voices/{voice_id}"


def _safe_urlopen(target: str | urllib.request.Request, **kwargs):
    """Wrap urllib.request.urlopen with an explicit https-only scheme guard.

    Either a URL string or a pre-built ``urllib.request.Request`` is accepted.
    ElevenLabs API responses include ``preview_url`` strings that we download
    — bandit flags bare ``urlopen()`` because it would technically follow
    ``file://`` or ``ftp://`` schemes. We've never seen ElevenLabs return
    anything other than ``https://`` previews, but enforce it explicitly so
    a future API change can't silently let us read a local file.
    """
    url = target if isinstance(target, str) else target.full_url
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("https", "http"):
        raise ValueError(
            f"refusing to open URL with non-http(s) scheme: {parsed.scheme!r} (url={url!r})"
        )
    return urllib.request.urlopen(target, **kwargs)  # nosec B310 — scheme validated above


def _find_ffmpeg() -> str:
    ffmpeg = shutil.which("ffmpeg") or shutil.which("/opt/homebrew/bin/ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg not found in PATH")
    return ffmpeg


def _resolve_api_key(api_key: str | None) -> str:
    """Return the API key from arg or env. Raises ValueError if missing."""
    key = api_key or os.environ.get("ELEVENLABS_API_KEY")
    if not key:
        raise ValueError(
            "ElevenLabs API key not provided. Pass api_key= or set ELEVENLABS_API_KEY env var."
        )
    return key


def fetch_voice_metadata(voice_id: str, api_key: str | None = None) -> dict:
    """GET /v1/voices/{id} → full voice metadata dict including preview_url."""
    key = _resolve_api_key(api_key)
    req = urllib.request.Request(
        ELEVENLABS_VOICE_ENDPOINT.format(voice_id=voice_id),
        headers={"xi-api-key": key, "Accept": "application/json"},
    )
    with _safe_urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def pull_preview(
    voice_id: str,
    api_key: str | None = None,
    output_path: Path | str | None = None,
) -> Path:
    """Download the Voice Lab preview MP3 for a given ElevenLabs voice.

    Args:
        voice_id: ElevenLabs voice_id (e.g., "c7qAAWgc7aGYHCLDzd8Y")
        api_key: ElevenLabs API key (or set ELEVENLABS_API_KEY env)
        output_path: where to write the MP3. If None, writes to a temp file
            at ``/tmp/voice_forge_{voice_id}_preview.mp3``.

    Returns:
        Path to the downloaded MP3.

    Raises:
        ValueError: API key missing OR voice has no preview_url.
        urllib.error.HTTPError: ElevenLabs API failure (404, 401, etc.).
    """
    voice = fetch_voice_metadata(voice_id, api_key)
    preview_url = voice.get("preview_url")
    if not preview_url:
        raise ValueError(f"voice {voice_id!r} has no preview_url in ElevenLabs metadata")

    if output_path is None:
        output_path = Path(tempfile.gettempdir()) / f"voice_forge_{voice_id}_preview.mp3"
    output_path = Path(output_path).expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with _safe_urlopen(preview_url, timeout=60) as resp:
        output_path.write_bytes(resp.read())
    return output_path


def mp3_to_wav(
    mp3_path: Path | str,
    output_path: Path | str | None = None,
    sample_rate: int = 24_000,
) -> Path:
    """Convert MP3 to mono WAV at the target sample rate (default 24kHz for NeuTTS)."""
    mp3 = Path(mp3_path).expanduser()
    if not mp3.exists():
        raise FileNotFoundError(mp3)
    if output_path is None:
        output_path = mp3.with_suffix(".wav")
    output_path = Path(output_path).expanduser()

    ffmpeg = _find_ffmpeg()
    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-i",
            str(mp3),
            "-ar",
            str(sample_rate),
            "-ac",
            "1",
            "-loglevel",
            "error",
            str(output_path),
        ],
        check=True,
    )
    return output_path


def pull_and_prepare(
    voice_id: str,
    api_key: str | None = None,
    trim_to_seconds: float | None = 14.0,
    output_dir: Path | str | None = None,
) -> tuple[Path, str]:
    """Full pipeline: download preview MP3 → convert to WAV → optionally trim.

    Args:
        voice_id: ElevenLabs voice_id
        api_key: ElevenLabs API key (or env)
        trim_to_seconds: if not None, trim WAV to last complete-sentence boundary
            within this many seconds (uses voice_lab.whisper.trim_to_sentence_boundary).
        output_dir: where to write final WAV + transcript. Default /tmp.

    Returns:
        (wav_path, ref_text) — ready to hand to registry.register().
    """
    if output_dir is None:
        output_dir = Path(tempfile.gettempdir()) / f"voice_forge_{voice_id}"
    output_dir = Path(output_dir).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)

    mp3 = pull_preview(voice_id, api_key, output_dir / "preview.mp3")
    wav = mp3_to_wav(mp3, output_dir / "ref_full.wav")

    if trim_to_seconds is None:
        # Just transcribe what we have
        from .whisper import transcribe

        text = transcribe(wav)
        return wav, text

    from .whisper import trim_to_sentence_boundary

    trimmed_path, text = trim_to_sentence_boundary(
        wav, max_seconds=trim_to_seconds, output_path=output_dir / "ref.wav"
    )
    return trimmed_path, text
