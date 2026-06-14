"""Thin ElevenLabs REST client for Voice Design + voice management.

Scope of this module: just the HTTP wrapping and the three Voice Design
endpoints voice-forge needs to create persona voices. NOT a general
ElevenLabs SDK — for full coverage, use the official ``elevenlabs`` PyPI
package. We use ``urllib`` here to keep voice_design dependency-free so
it works in environments that don't install the ``[voice-design]`` extra.

Endpoints covered:
- ``POST /v1/text-to-voice/create-previews`` — Voice Design audition; returns
  N preview voices keyed by ``generated_voice_id`` (ephemeral; expire if
  not persisted).
- ``POST /v1/text-to-voice/create-voice-from-preview`` — persist a chosen
  preview as a permanent voice in the user's library; returns ``voice_id``.
- ``POST /v1/text-to-speech/{voice_id}`` — synth speech from a saved
  voice (used by ``voice-design regen`` to re-render reference WAVs
  without re-auditioning).

API key is taken from the ``ELEVENLABS_API_KEY`` env var by default; the
caller can pass it explicitly. We deliberately do NOT support reading
from Ansible Vault or other deploy systems here — that's the caller's
concern. See ``scripts/voice_design.py`` for the env-var → API-key wiring.
"""

from __future__ import annotations

import base64
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib import error, request

logger = logging.getLogger("voice_forge.voice_design.elevenlabs")

BASE_URL = "https://api.elevenlabs.io"
DEFAULT_TIMEOUT_SEC = 60


class ElevenLabsError(RuntimeError):
    """Raised when the ElevenLabs API returns a non-2xx response."""

    def __init__(self, method: str, path: str, status: int, body: str) -> None:
        super().__init__(f"ElevenLabs {method} {path} → HTTP {status}: {body}")
        self.method = method
        self.path = path
        self.status = status
        self.body = body


@dataclass(frozen=True)
class Preview:
    """One Voice Design preview from ``/create-previews``.

    ``generated_voice_id`` is ephemeral — pass it to
    ``create_voice_from_preview`` to persist. ``audio`` is decoded MP3
    bytes; write to a file with ``.mp3`` suffix.
    """

    generated_voice_id: str
    audio: bytes


def _resolve_api_key(api_key: str | None) -> str:
    """Resolution chain: explicit kwarg → env var → vault.

    The vault is consulted via :func:`voice_forge.secrets.get_secret` which
    handles its own missing-file / missing-password tolerance, so it's
    safe to call even on hosts without a vault configured. The import is
    deferred so the secrets module's ``cryptography`` dependency isn't
    a hard requirement for env-var-only users.
    """
    if api_key:
        return api_key
    env = os.environ.get("ELEVENLABS_API_KEY")
    if env:
        return env
    try:
        from voice_forge.secrets import get_secret  # noqa: PLC0415 — defer import

        vault_val = get_secret("elevenlabs.api_key")
        if vault_val:
            return vault_val
    except ImportError:
        pass
    raise RuntimeError(
        "ElevenLabs API key required: pass api_key=..., set ELEVENLABS_API_KEY env var, "
        "or `voice-forge-secrets set elevenlabs.api_key <key>`"
    )


def _http(
    method: str,
    path: str,
    api_key: str,
    *,
    body: dict | None = None,
    accept: str = "application/json",
    timeout: int = DEFAULT_TIMEOUT_SEC,
) -> bytes:
    """Low-level HTTP call. Returns raw response bytes; caller decodes."""
    req = request.Request(
        f"{BASE_URL}{path}",
        method=method,
        headers={
            "xi-api-key": api_key,
            "Accept": accept,
            "Content-Type": "application/json",
        },
        data=(json.dumps(body).encode("utf-8") if body is not None else None),
    )
    try:
        # B310: urlopen with non-http(s) scheme is the only real concern;
        # BASE_URL is hardcoded https.
        with request.urlopen(req, timeout=timeout) as resp:  # nosec B310
            return resp.read()
    except error.HTTPError as e:
        detail = e.read().decode(errors="replace")
        raise ElevenLabsError(method, path, e.code, detail) from None


def create_voice_previews(
    description: str,
    sample_text: str,
    *,
    api_key: str | None = None,
) -> list[Preview]:
    """Voice Design audition. Returns the previews (typically 3).

    ``description`` is the Voice Design prompt — see
    :mod:`voice_forge.voice_design.prompt_builder` for best-practices
    construction. ``sample_text`` is the sentence the previews will speak
    so you can compare them. Both are sent to ElevenLabs as-is.
    """
    api_key = _resolve_api_key(api_key)
    raw = _http(
        "POST",
        "/v1/text-to-voice/create-previews",
        api_key,
        body={"voice_description": description, "text": sample_text},
    )
    payload = json.loads(raw.decode())
    previews_raw = payload.get("previews") or []
    if not previews_raw:
        raise ElevenLabsError("POST", "/v1/text-to-voice/create-previews", 200, str(payload))
    out: list[Preview] = []
    for p in previews_raw:
        b64 = p.get("audio_base_64") or p.get("audio_base64") or ""
        gen_id = p.get("generated_voice_id") or ""
        if not (b64 and gen_id):
            continue
        out.append(Preview(generated_voice_id=gen_id, audio=base64.b64decode(b64)))
    return out


def create_voice_from_preview(
    voice_name: str,
    description: str,
    generated_voice_id: str,
    *,
    api_key: str | None = None,
) -> str:
    """Persist a preview as a permanent voice in the user's library.

    Returns the permanent ``voice_id`` to drop into your fleet config.
    """
    api_key = _resolve_api_key(api_key)
    raw = _http(
        "POST",
        "/v1/text-to-voice/create-voice-from-preview",
        api_key,
        body={
            "voice_name": voice_name,
            "voice_description": description,
            "generated_voice_id": generated_voice_id,
        },
    )
    payload = json.loads(raw.decode())
    voice_id = payload.get("voice_id")
    if not voice_id:
        raise ElevenLabsError(
            "POST", "/v1/text-to-voice/create-voice-from-preview", 200, str(payload)
        )
    return voice_id


@dataclass(frozen=True)
class SharedVoice:
    """One voice from the public Voice Library (``/v1/shared-voices``).

    ``voice_id`` + ``public_owner_id`` together identify the voice for the
    add-to-library call. ``preview_url`` is a static MP3 we can fetch
    directly (no API key needed) to let the user audition before adopting.

    Note on accent labels: ElevenLabs's library taxonomy lumps Norwegian /
    Swedish / Danish / Icelandic into a small set of values, usually
    ``swedish`` or ``nordic``. The free-text ``description`` is more
    accurate. Don't trust ``accent`` to disambiguate Scandinavian sub-
    accents — read ``description`` too.
    """

    voice_id: str
    public_owner_id: str
    name: str
    description: str
    gender: str
    age: str
    accent: str
    language: str
    locale: str
    preview_url: str
    category: str
    descriptive: str
    use_case: str
    cloned_by_count: int


def search_shared_voices(
    *,
    api_key: str | None = None,
    language: str = "en",
    gender: str | None = None,
    accent: str | None = None,
    age: str | None = None,
    search: str | None = None,
    page_size: int = 20,
) -> list[SharedVoice]:
    """Query the public Voice Library. Returns voices matching the filters.

    None-valued filters are omitted (the server treats absence as 'any').
    ``search`` is a free-text query that ElevenLabs runs against name +
    description + tags.
    """
    api_key = _resolve_api_key(api_key)
    from urllib.parse import urlencode  # noqa: PLC0415 — local stdlib only

    params: dict[str, str] = {"language": language, "page_size": str(page_size)}
    if gender:
        params["gender"] = gender
    if accent:
        params["accent"] = accent
    if age:
        params["age"] = age
    if search:
        params["search"] = search
    raw = _http(
        "GET",
        f"/v1/shared-voices?{urlencode(params)}",
        api_key,
    )
    payload = json.loads(raw.decode())
    out: list[SharedVoice] = []
    for v in payload.get("voices") or []:
        out.append(
            SharedVoice(
                voice_id=v.get("voice_id", ""),
                public_owner_id=v.get("public_owner_id", ""),
                name=v.get("name", ""),
                description=v.get("description", ""),
                gender=v.get("gender", ""),
                age=v.get("age", ""),
                accent=v.get("accent", ""),
                language=v.get("language", ""),
                locale=v.get("locale", ""),
                preview_url=v.get("preview_url", ""),
                category=v.get("category", ""),
                descriptive=v.get("descriptive", ""),
                use_case=v.get("use_case", ""),
                cloned_by_count=int(v.get("cloned_by_count") or 0),
            )
        )
    return out


def download_preview(voice: SharedVoice, out_path: Path) -> Path:
    """Fetch a shared voice's preview MP3 to ``out_path``.

    The preview URLs are public Google Cloud Storage links; no API key
    needed. We use urllib so this module stays dependency-light.
    """
    from urllib.request import Request, urlopen  # noqa: PLC0415

    req = Request(voice.preview_url, headers={"User-Agent": "voice-forge"})
    with urlopen(
        req, timeout=30
    ) as resp:  # noqa: S310  # nosec B310 — preview_url is an https GCS link from the ElevenLabs API
        data = resp.read()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(data)
    return out_path


def add_shared_voice_to_library(
    public_owner_id: str,
    voice_id: str,
    new_name: str,
    *,
    api_key: str | None = None,
) -> str:
    """Adopt a public shared voice into the caller's private library.

    Returns the NEW private ``voice_id`` (different from the public one).
    Drop this into ``fleet.yaml`` under ``elevenlabs_voice_id`` to use
    the voice in voice-forge's regen + cloning pipeline.
    """
    api_key = _resolve_api_key(api_key)
    raw = _http(
        "POST",
        f"/v1/voices/add/{public_owner_id}/{voice_id}",
        api_key,
        body={"new_name": new_name},
    )
    payload = json.loads(raw.decode())
    new_voice_id = payload.get("voice_id")
    if not new_voice_id:
        raise ElevenLabsError(
            "POST", f"/v1/voices/add/{public_owner_id}/{voice_id}", 200, str(payload)
        )
    return new_voice_id


def text_to_speech(
    voice_id: str,
    text: str,
    *,
    api_key: str | None = None,
    model_id: str = "eleven_multilingual_v2",
    output_format: str = "pcm_24000",
    voice_settings: dict[str, Any] | None = None,
) -> bytes:
    """Synthesize speech from a persisted voice. Returns raw audio bytes.

    Default ``output_format=pcm_24000`` returns raw signed-16-bit PCM at
    24 kHz mono — the format voice-forge's F5/NeuTTS reference encoders
    expect. Use ``mp3_44100_128`` for general playback. The endpoint
    returns the audio body directly (no JSON wrapper).

    Bug fix 2026-05-26: ``output_format`` is a QUERY parameter, not a
    body field. Earlier versions of this function passed it in the body,
    which ElevenLabs silently ignored — the API fell back to the default
    ``mp3_44100_128`` regardless of what the caller requested. Code that
    treated the result as PCM (e.g. wrapping in a 24kHz int16 WAV
    header) produced pure noise. Now correctly emitted in the query string.
    """
    api_key = _resolve_api_key(api_key)
    body: dict[str, Any] = {
        "text": text,
        "model_id": model_id,
    }
    if voice_settings:
        body["voice_settings"] = voice_settings
    from urllib.parse import urlencode  # noqa: PLC0415 — local stdlib only

    qs = urlencode({"output_format": output_format})
    return _http(
        "POST",
        f"/v1/text-to-speech/{voice_id}?{qs}",
        api_key,
        body=body,
        accept="audio/*",
    )
