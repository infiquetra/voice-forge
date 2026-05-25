"""FastAPI app — REST surface for voice-forge.

See ``docs/API_SPEC.md`` for the full endpoint spec. Highlights:

    POST /v1/audio/speech    Synthesize text → audio (OpenAI-compatible)
    GET  /v1/audio/voices    List registered voices
    POST /voices/{id}        Register a new voice
    POST /voices/from-elevenlabs   Pull from ElevenLabs Voice Lab
    DELETE /voices/{id}      Remove a voice
    GET  /voices/{id}        Get voice metadata
    GET  /health             Service health

Backend instances are cached in-process (loaded once, used for all
subsequent requests). Per-backend threading.Lock inside the backend itself
serializes inference.
"""

from __future__ import annotations

import io
import logging
import os
import shutil
import struct
import subprocess
import tempfile
import wave
from collections.abc import Iterator

import numpy as np
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from . import __version__
from .backends import available_backends, get_backend, known_backends, load_backend_module
from .registry import Registry

logger = logging.getLogger("voice_forge")
logging.basicConfig(level=os.environ.get("VOICE_FORGE_LOG_LEVEL", "INFO").upper())

SAMPLE_RATE = 24_000


app = FastAPI(
    title="voice-forge",
    version=__version__,
    description="Pluggable TTS service for agent voices",
)


# ----- Cache of loaded backend instances -----


_BACKENDS: dict[str, object] = {}


def _ensure_backend(name: str, config: dict | None = None):
    """Lazy-load + cache backend instances. One per backend name per process."""
    if name in _BACKENDS:
        return _BACKENDS[name]
    try:
        load_backend_module(name)
    except KeyError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"unknown backend: {name!r}; known: {known_backends()}",
        ) from exc
    except ImportError as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                f"backend {name!r} known but not installed; "
                f"install with `pip install voice-forge-tts[{name}]` ({exc})"
            ),
        ) from exc
    backend_cls = get_backend(name)
    backend = backend_cls()
    logger.info("loading backend %s ...", name)
    backend.load(config or {})
    logger.info("backend %s loaded", name)
    _BACKENDS[name] = backend
    return backend


def _registry() -> Registry:
    return Registry()


# ----- Schemas -----


class SpeechRequest(BaseModel):
    """OpenAI-compatible /v1/audio/speech request body."""

    model: str = Field(default="voice-forge", description="Mostly informational (for SDK compat)")
    input: str = Field(..., description="Text to synthesize")
    voice: str = Field(..., description="voice_id from registry")
    response_format: str = Field(default="wav", description="wav | mp3 | opus | pcm")
    # Backends honor speed differently: kokoro KPipeline accepts speed=
    # directly; NeuTTS has no native speed control and ignores it.
    # Plumbing through the TTSBackend Protocol is deferred (v0.2.x).
    speed: float = Field(
        default=1.0,
        ge=0.25,
        le=4.0,
        description="Playback speed (kokoro honors; neutts ignores)",
    )
    stream: bool = Field(
        default=False, description="Use chunked transfer for progressive synthesis"
    )


class VoiceInfo(BaseModel):
    id: str
    backend: str
    language: str | None = None
    description: str | None = None
    metadata: dict


class VoicesList(BaseModel):
    data: list[VoiceInfo]


class FromElevenLabsRequest(BaseModel):
    voice_id: str
    elevenlabs_voice_id: str
    elevenlabs_api_key: str | None = None
    backend: str = "neutts"
    max_seconds: float = 14.0
    auto_trim: bool = True
    language: str = "en"
    overwrite: bool = False


# ----- Helpers -----


def _samples_to_wav_bytes(samples: np.ndarray, sample_rate: int = SAMPLE_RATE) -> bytes:
    """Float32 [-1,1] PCM → WAV bytes (PCM 16-bit mono)."""
    pcm = (np.clip(samples.flatten(), -1.0, 1.0) * 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


def _streaming_wav_header(
    sample_rate: int = SAMPLE_RATE, channels: int = 1, bits: int = 16
) -> bytes:
    """WAV header with placeholder data size (0xFFFFFFFF) for streaming.

    Most decoders read until EOF when they see this — matches the home-lab
    daemon's FIFO streaming pattern.
    """
    byte_rate = sample_rate * channels * (bits // 8)
    block_align = channels * (bits // 8)
    header = b"RIFF"
    header += struct.pack("<I", 0xFFFFFFFF)
    header += b"WAVE"
    header += b"fmt "
    header += struct.pack("<I", 16)
    header += struct.pack("<H", 1)
    header += struct.pack("<H", channels)
    header += struct.pack("<I", sample_rate)
    header += struct.pack("<I", byte_rate)
    header += struct.pack("<H", block_align)
    header += struct.pack("<H", bits)
    header += b"data"
    header += struct.pack("<I", 0xFFFFFFFF)
    return header


def _samples_chunk_to_pcm_bytes(samples: np.ndarray) -> bytes:
    """Float32 chunk → raw PCM int16 bytes for streaming append."""
    pcm = (np.clip(samples.flatten(), -1.0, 1.0) * 32767).astype(np.int16)
    return pcm.tobytes()


def _stream_wav(audio_iter: Iterator[np.ndarray]) -> Iterator[bytes]:
    """Wrap a sample-iterator into a streaming WAV byte iterator."""
    yield _streaming_wav_header()
    for chunk in audio_iter:
        yield _samples_chunk_to_pcm_bytes(chunk)


def _wav_to_format(wav_bytes: bytes, target_format: str) -> bytes:
    """Convert in-memory WAV to mp3/opus via ffmpeg. PCM/wav pass through."""
    if target_format in ("wav", "pcm"):
        return wav_bytes
    ffmpeg = shutil.which("ffmpeg") or shutil.which("/opt/homebrew/bin/ffmpeg")
    if not ffmpeg:
        raise HTTPException(status_code=503, detail="ffmpeg not available for format conversion")
    fmt_args: dict[str, list[str]] = {
        "mp3": ["-f", "mp3", "-b:a", "192k"],
        "opus": ["-f", "opus", "-b:a", "96k"],
    }
    if target_format not in fmt_args:
        raise HTTPException(status_code=400, detail=f"unsupported format: {target_format}")
    proc = subprocess.run(
        [ffmpeg, "-y", "-i", "pipe:0", *fmt_args[target_format], "pipe:1", "-loglevel", "error"],
        input=wav_bytes,
        capture_output=True,
        check=True,
    )
    return proc.stdout


_CONTENT_TYPES = {
    "wav": "audio/wav",
    "mp3": "audio/mpeg",
    "opus": "audio/opus",
    "pcm": "audio/L16",
}


# ----- Endpoints -----


@app.get("/health")
async def health() -> dict:
    """Service health endpoint."""
    registry = _registry()
    return {
        "ok": True,
        "version": __version__,
        "registry_dir": str(registry.root),
        "voices_count": len(registry.list()),
        "backends_available": available_backends(),
        "backends_loaded": sorted(_BACKENDS.keys()),
    }


@app.post("/v1/audio/speech")
async def synthesize_speech(req: SpeechRequest):
    """OpenAI-compatible speech synthesis."""
    registry = _registry()
    try:
        ref = registry.get(req.voice)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"voice {req.voice!r} not in registry") from exc

    backend = _ensure_backend(ref.backend, ref.metadata)
    content_type = _CONTENT_TYPES.get(req.response_format, "application/octet-stream")

    if req.stream:
        # Streaming: only WAV is supported in v0 (chunked PCM). MP3/Opus need full
        # buffer to encode; falls back to non-stream for those.
        if req.response_format not in ("wav", "pcm"):
            # Streaming non-wav: synth all then return as one response (degrades to non-streaming)
            audio = backend.synthesize(req.input, ref)
            wav_bytes = _samples_to_wav_bytes(audio)
            body = _wav_to_format(wav_bytes, req.response_format)
            return Response(content=body, media_type=content_type)

        audio_iter = backend.synthesize_stream(req.input, ref)
        return StreamingResponse(
            _stream_wav(audio_iter),
            media_type=content_type,
            headers={"X-Voice-Forge-Backend": ref.backend},
        )

    # Batch (full synth before reply)
    audio = backend.synthesize(req.input, ref)
    wav_bytes = _samples_to_wav_bytes(audio)
    body = _wav_to_format(wav_bytes, req.response_format)
    audio_sec = len(audio) / SAMPLE_RATE
    return Response(
        content=body,
        media_type=content_type,
        headers={
            "X-Voice-Forge-Backend": ref.backend,
            "X-Voice-Forge-Audio-Sec": f"{audio_sec:.2f}",
        },
    )


@app.get("/v1/audio/voices", response_model=VoicesList)
async def list_voices() -> VoicesList:
    """List all registered voices (OpenAI-compatible-ish shape)."""
    registry = _registry()
    return VoicesList(
        data=[
            VoiceInfo(
                id=v.voice_id,
                backend=v.backend,
                language=v.metadata.get("language"),
                description=v.metadata.get("description"),
                metadata=v.metadata,
            )
            for v in registry.list()
        ]
    )


@app.get("/voices/{voice_id}", response_model=VoiceInfo)
async def get_voice(voice_id: str) -> VoiceInfo:
    """Get metadata for a single voice."""
    registry = _registry()
    try:
        v = registry.get(voice_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"voice {voice_id!r} not in registry") from exc
    return VoiceInfo(
        id=v.voice_id,
        backend=v.backend,
        language=v.metadata.get("language"),
        description=v.metadata.get("description"),
        metadata=v.metadata,
    )


@app.post("/voices/{voice_id}", response_model=VoiceInfo, status_code=201)
async def register_voice(
    voice_id: str,
    ref_audio: UploadFile = File(...),  # noqa: B008,
    ref_text: str | None = Form(default=None),
    backend: str = Form(default="neutts"),
    language: str = Form(default="en"),
    description: str = Form(default=""),
    overwrite: bool = Form(default=False),
) -> VoiceInfo:
    """Register a new voice from an uploaded ref WAV."""
    # Save upload to a unique temp file. registry.register will copy it
    # into the canonical store, so we delete the temp in the finally
    # block — prevents /tmp from growing over the life of the process.
    with tempfile.NamedTemporaryFile(
        suffix=".wav", delete=False, prefix="voice_forge_upload_"
    ) as tmp_f:
        tmp_path = tmp_f.name
        tmp_f.write(await ref_audio.read())

    try:
        # Whisper-transcribe if no ref_text provided. Whisper is sync +
        # CPU-bound, so push it off the event loop.
        if ref_text is None:
            from .voice_lab.whisper import transcribe

            try:
                ref_text = await run_in_threadpool(transcribe, tmp_path, language=language)
            except ImportError as exc:
                raise HTTPException(status_code=503, detail=str(exc)) from exc

        registry = _registry()
        try:
            v = registry.register(
                voice_id=voice_id,
                ref_audio_path=tmp_path,
                ref_text=ref_text,
                backend=backend,
                metadata={"language": language, "description": description},
                overwrite=overwrite,
            )
        except FileExistsError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return VoiceInfo(
            id=v.voice_id,
            backend=v.backend,
            language=v.metadata.get("language"),
            description=v.metadata.get("description"),
            metadata=v.metadata,
        )
    finally:
        try:
            os.unlink(tmp_path)
        except FileNotFoundError:
            pass


@app.post("/voices/from-elevenlabs", response_model=VoiceInfo, status_code=201)
async def pull_from_elevenlabs(req: FromElevenLabsRequest) -> VoiceInfo:
    """Pull a voice from ElevenLabs Voice Lab + auto-trim + register."""
    from .voice_lab.elevenlabs import pull_and_prepare

    trim = req.max_seconds if req.auto_trim else None
    try:
        wav_path, ref_text = pull_and_prepare(
            voice_id=req.elevenlabs_voice_id,
            api_key=req.elevenlabs_api_key,
            trim_to_seconds=trim,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    registry = _registry()
    try:
        v = registry.register(
            voice_id=req.voice_id,
            ref_audio_path=wav_path,
            ref_text=ref_text,
            backend=req.backend,
            metadata={
                "language": req.language,
                "source": f"elevenlabs:{req.elevenlabs_voice_id}",
            },
            overwrite=req.overwrite,
        )
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return VoiceInfo(
        id=v.voice_id,
        backend=v.backend,
        language=v.metadata.get("language"),
        description=v.metadata.get("description"),
        metadata=v.metadata,
    )


@app.delete("/voices/{voice_id}", status_code=204)
async def delete_voice(voice_id: str):
    """Remove a voice from the registry. Idempotent."""
    registry = _registry()
    registry.delete(voice_id)
    return Response(status_code=204)
