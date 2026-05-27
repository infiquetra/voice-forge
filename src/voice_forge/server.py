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

import asyncio
import io
import logging
import os
import shutil
import struct
import subprocess
import tempfile
import threading
import wave
from collections.abc import Iterator
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path
from typing import Literal

import numpy as np
from fastapi import FastAPI, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, HTMLResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

from . import __version__, config, lab_state, metrics
from .backends import available_backends, get_backend, known_backends, load_backend_module
from .persona_coverage import ensure_full_coverage
from .registry import Registry
from .sentence_buffer import SentenceBuffer

try:
    import psutil

    _PROCESS = psutil.Process()
except ImportError:  # pragma: no cover — psutil is a base dep, this is belt-and-suspenders
    psutil = None  # type: ignore[assignment]
    _PROCESS = None


def _process_rss_mb() -> float | None:
    """Current process RSS in MB, or None if psutil isn't available."""
    if _PROCESS is None:
        return None
    return _PROCESS.memory_info().rss / (1024 * 1024)


logger = logging.getLogger("voice_forge")
logging.basicConfig(level=os.environ.get("VOICE_FORGE_LOG_LEVEL", "INFO").upper())

SAMPLE_RATE = 24_000


FLEET_PATH_ENV = "VOICE_FORGE_FLEET_PATH"
DEFAULT_FLEET_PATH = Path("tests/functional/fleet.yaml")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Server-wide startup + shutdown hooks.

    On startup: run ``ensure_full_coverage`` against fleet.yaml so the
    /lab persona × backend matrix is fully populated. No-op when
    fleet.yaml is absent (the case for outside-user installs).
    """
    fleet_path = Path(os.environ.get(FLEET_PATH_ENV, str(DEFAULT_FLEET_PATH))).expanduser()
    try:
        summary = ensure_full_coverage(_registry(), fleet_path)
        if "skipped" in summary:
            logger.info("persona coverage: %s", summary["skipped"])
        else:
            logger.info(
                "persona coverage: created=%d, skipped_existing=%d, "
                "skipped_missing_ref=%d, skipped_backend_not_installed=%s",
                len(summary["created"]),
                len(summary["skipped_existing"]),
                len(summary["skipped_missing_ref"]),
                summary["skipped_backend_not_installed"],
            )
    except Exception:
        # ensure_full_coverage is non-essential; don't block server startup
        # on a registry quirk. Log + continue.
        logger.exception("ensure_full_coverage failed at startup; continuing")
    yield
    # No shutdown work today; placeholder for future cleanup hooks.


app = FastAPI(
    title="voice-forge",
    version=__version__,
    description="Pluggable TTS service for agent voices",
    lifespan=lifespan,
)


# ----- Cache of loaded backend instances -----


_BACKENDS: dict[str, object] = {}
# Per-backend lock so concurrent _ensure_backend calls don't each spawn a
# duplicate subprocess child during the cold-load window. The lock is
# acquired by the FIRST caller; subsequent callers block until the first
# call resolves, at which point _BACKENDS[name] is populated and they
# return immediately. Keyed by backend name so different backends can
# still cold-load in parallel.
_BACKEND_LOAD_LOCKS: dict[str, threading.Lock] = {}
_BACKEND_LOAD_LOCKS_GUARD = threading.Lock()


def _ensure_backend(name: str, config: dict | None = None):
    """Lazy-load + cache backend instances. One per backend name per process.

    Thread-safe via per-backend locks: concurrent calls for the same backend
    serialize; calls for different backends proceed in parallel. The first
    caller does the actual load; followers see the cached instance.
    """
    if name in _BACKENDS:
        return _BACKENDS[name]
    # Acquire (or create) the per-backend lock under a tiny global guard.
    with _BACKEND_LOAD_LOCKS_GUARD:
        lock = _BACKEND_LOAD_LOCKS.setdefault(name, threading.Lock())
    with lock:
        # Re-check after acquiring lock — another thread may have loaded it
        # while we waited.
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
        metrics.backend_loaded.labels(backend=name).set(1)
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
    persona: str | None = None
    language: str | None = None
    description: str | None = None
    metadata: dict


class VoicesList(BaseModel):
    data: list[VoiceInfo]


class FromElevenLabsRequest(BaseModel):
    voice_id: str
    elevenlabs_voice_id: str
    elevenlabs_api_key: str | None = None
    # The default flows from ``config.get_default_backend()`` so a runtime
    # PUT /v1/backends/default change is honored without restarting the
    # server. F5 is the hardcoded fallback (DECISIONS 2026-05-25).
    backend: str = Field(default_factory=config.get_default_backend)
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


@app.get("/metrics")
async def get_metrics() -> Response:
    """Prometheus scrape endpoint.

    Returns the canonical text/plain exposition format. Auth-exempt so
    monitoring infrastructure (Prometheus + Grafana) can scrape without
    needing a token rotation story.

    Voices-registered gauge is updated on every scrape — keeps the value
    fresh without paying the cost on every CRUD call.
    """
    metrics.voices_registered.set(len(_registry().list()))
    body, content_type = metrics.render()
    return Response(content=body, media_type=content_type)


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
    mode = "stream" if req.stream else "batch"
    metric_labels = {"backend": ref.backend, "voice_id": req.voice, "mode": mode}

    if req.stream:
        # Streaming: only WAV is supported in v0 (chunked PCM). MP3/Opus need full
        # buffer to encode; falls back to non-stream for those.
        if req.response_format not in ("wav", "pcm"):
            # Streaming non-wav: synth all then return as one response (degrades to non-streaming)
            import time as _time

            t0 = _time.monotonic()
            try:
                audio = backend.synthesize(req.input, ref)
            except Exception:
                metrics.synth_requests_total.labels(**metric_labels, status="fail").inc()
                raise
            metrics.synth_seconds.labels(**metric_labels).observe(_time.monotonic() - t0)
            metrics.synth_requests_total.labels(**metric_labels, status="ok").inc()
            wav_bytes = _samples_to_wav_bytes(audio)
            body = _wav_to_format(wav_bytes, req.response_format)
            return Response(content=body, media_type=content_type)

        # Native streaming path — instrument total wall-clock around the
        # generator. Histograms record once per request when the response
        # stream is fully consumed (or when an exception aborts it).
        import time as _time

        def _stream_wav_instrumented():
            t0 = _time.monotonic()
            status = "ok"
            try:
                yield from _stream_wav(backend.synthesize_stream(req.input, ref))
            except Exception:
                status = "fail"
                raise
            finally:
                metrics.synth_seconds.labels(**metric_labels).observe(_time.monotonic() - t0)
                metrics.synth_requests_total.labels(**metric_labels, status=status).inc()

        return StreamingResponse(
            _stream_wav_instrumented(),
            media_type=content_type,
            headers={"X-Voice-Forge-Backend": ref.backend},
        )

    # Batch (full synth before reply)
    import time as _time

    t0 = _time.monotonic()
    try:
        audio = backend.synthesize(req.input, ref)
    except Exception:
        metrics.synth_requests_total.labels(**metric_labels, status="fail").inc()
        raise
    metrics.synth_seconds.labels(**metric_labels).observe(_time.monotonic() - t0)
    metrics.synth_requests_total.labels(**metric_labels, status="ok").inc()
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


class BackendInfo(BaseModel):
    """Per-backend introspection payload for the demo page's conditional knob panel."""

    name: str
    known: bool
    installed: bool
    loaded: bool
    is_default: bool
    tunables: dict


class BackendsList(BaseModel):
    data: list[BackendInfo]


class BackendDefaultRequest(BaseModel):
    backend: str = Field(..., description="Backend name to make the new default")


class BackendDefaultResponse(BaseModel):
    default_backend: str


class BackendLifecycleResponse(BaseModel):
    """Returned by load / unload / DELETE-loaded endpoints.

    The RSS deltas are real measurements via psutil — see the partial-unload
    note in TTSBackend.unload() about realistic recovery being ~70-90% of a
    backend's resident set. The 30-10% residual is PyTorch / MPS / HF cache
    state that doesn't release without a process restart.
    """

    backend: str | None = None  # None for the bulk DELETE-loaded variant
    action: str  # "loaded" | "already_loaded" | "unloaded" | "already_unloaded" | "reset"
    affected_backends: list[str] = Field(default_factory=list)
    rss_before_mb: float | None = None
    rss_after_mb: float | None = None
    reclaimed_mb: float | None = None  # signed: positive on unload, ≤0 on load
    note: str | None = None


@app.get("/v1/backends", response_model=BackendsList)
async def list_backends() -> BackendsList:
    """List backends + tunable schemas + runtime load state.

    ``installed`` — backend extra is on this host (pip install voice-forge-tts[name]).
    ``loaded``    — backend instance currently in memory (consuming RSS).
    ``is_default``— this backend is the configured default for new voices.
    """
    current_default = config.get_default_backend()
    out: list[BackendInfo] = []
    for backend_name in known_backends():
        tunables: dict = {}
        is_installed = False
        try:
            load_backend_module(backend_name)
            cls = get_backend(backend_name)
            tunables = getattr(cls, "KNOWN_TUNABLES", {}) or {}
            is_installed = True
        except (ImportError, KeyError):
            is_installed = False
        out.append(
            BackendInfo(
                name=backend_name,
                known=True,
                installed=is_installed,
                loaded=backend_name in _BACKENDS,
                is_default=(backend_name == current_default),
                tunables=tunables,
            )
        )
    return BackendsList(data=out)


@app.post("/v1/backends/{name}/load", response_model=BackendLifecycleResponse)
async def load_backend_endpoint(name: str) -> BackendLifecycleResponse:
    """Explicitly warm a backend without needing a synth call.

    Useful at boot time to amortize cold-load latency before the first
    request. Idempotent — re-loading an already-loaded backend is a no-op
    that returns ``action="already_loaded"``.
    """
    if name not in known_backends():
        raise HTTPException(
            status_code=404, detail=f"unknown backend {name!r}; known: {known_backends()}"
        )
    if name in _BACKENDS:
        return BackendLifecycleResponse(
            backend=name,
            action="already_loaded",
            affected_backends=[name],
            rss_before_mb=_process_rss_mb(),
            rss_after_mb=_process_rss_mb(),
            reclaimed_mb=0.0,
        )
    rss_before = _process_rss_mb()
    try:
        _ensure_backend(name)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"load failed: {exc!r}") from exc
    rss_after = _process_rss_mb()
    return BackendLifecycleResponse(
        backend=name,
        action="loaded",
        affected_backends=[name],
        rss_before_mb=rss_before,
        rss_after_mb=rss_after,
        reclaimed_mb=(
            (rss_before - rss_after) if rss_before is not None and rss_after is not None else None
        ),
    )


@app.post("/v1/backends/{name}/unload", response_model=BackendLifecycleResponse)
async def unload_backend_endpoint(name: str) -> BackendLifecycleResponse:
    """Release a backend's model state. Reports actual RSS reclaimed.

    Realistic recovery is ~70-90% — framework caches (PyTorch MPS allocator,
    HuggingFace cache pages, shared libraries) persist until process restart.
    For full reclamation, restart ``voice-forge serve`` (~3 s boot).
    """
    if name not in known_backends():
        raise HTTPException(
            status_code=404, detail=f"unknown backend {name!r}; known: {known_backends()}"
        )
    if name not in _BACKENDS:
        return BackendLifecycleResponse(
            backend=name,
            action="already_unloaded",
            affected_backends=[],
            rss_before_mb=_process_rss_mb(),
            rss_after_mb=_process_rss_mb(),
            reclaimed_mb=0.0,
        )
    rss_before = _process_rss_mb()
    backend = _BACKENDS.pop(name)
    try:
        backend.unload()  # type: ignore[attr-defined]
    except Exception as exc:
        # Backend instance is already out of _BACKENDS; just log + continue
        logger.warning("[%s] unload() raised: %r", name, exc)
    metrics.backend_loaded.labels(backend=name).set(0)
    rss_after = _process_rss_mb()
    reclaimed = (
        (rss_before - rss_after) if rss_before is not None and rss_after is not None else None
    )
    note = None
    if reclaimed is not None and rss_before:
        # If less than 50% of the backend's RSS came back, surface that to the
        # caller — they may want to restart the process for full reclamation.
        # Estimates ASSUME the backend was the biggest RSS contributor.
        pass  # Could compute against backend-specific expected RSS; skip for now.
    return BackendLifecycleResponse(
        backend=name,
        action="unloaded",
        affected_backends=[name],
        rss_before_mb=rss_before,
        rss_after_mb=rss_after,
        reclaimed_mb=reclaimed,
        note=note,
    )


@app.delete("/v1/backends/loaded", response_model=BackendLifecycleResponse)
async def unload_all_backends() -> BackendLifecycleResponse:
    """Unload every currently-loaded backend. Idempotent (no-op if nothing loaded)."""
    loaded_names = list(_BACKENDS.keys())
    rss_before = _process_rss_mb()
    for name in loaded_names:
        backend = _BACKENDS.pop(name)
        try:
            backend.unload()  # type: ignore[attr-defined]
        except Exception as exc:
            logger.warning("[%s] unload() raised: %r", name, exc)
        metrics.backend_loaded.labels(backend=name).set(0)
    rss_after = _process_rss_mb()
    return BackendLifecycleResponse(
        backend=None,
        action="reset",
        affected_backends=loaded_names,
        rss_before_mb=rss_before,
        rss_after_mb=rss_after,
        reclaimed_mb=(
            (rss_before - rss_after) if rss_before is not None and rss_after is not None else None
        ),
    )


@app.put("/v1/backends/default", response_model=BackendDefaultResponse)
async def set_default_backend_endpoint(req: BackendDefaultRequest) -> BackendDefaultResponse:
    """Set the system-wide default backend.

    Persisted to ``~/.voice-forge/config.json`` so the change survives
    process restart. Affects new voice registrations + the
    ``backend=`` defaults on the REST + CLI surfaces. Does NOT
    re-route already-registered voices.
    """
    if req.backend not in known_backends():
        raise HTTPException(
            status_code=400,
            detail=f"unknown backend {req.backend!r}; known: {known_backends()}",
        )
    new_value = config.set_default_backend(req.backend)
    return BackendDefaultResponse(default_backend=new_value)


@app.get("/v1/audio/voices", response_model=VoicesList)
async def list_voices() -> VoicesList:
    """List all registered voices (OpenAI-compatible-ish shape)."""
    registry = _registry()
    return VoicesList(
        data=[
            VoiceInfo(
                id=v.voice_id,
                backend=v.backend,
                persona=v.persona,
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
        persona=v.persona,
        language=v.metadata.get("language"),
        description=v.metadata.get("description"),
        metadata=v.metadata,
    )


@app.post("/voices/{voice_id}", response_model=VoiceInfo, status_code=201)
async def register_voice(
    voice_id: str,
    ref_audio: UploadFile = File(...),  # noqa: B008,
    ref_text: str | None = Form(default=None),
    # backend defaults to the runtime-configured value (config.get_default_backend)
    # — Form's default= is evaluated at route definition, not per-request, so we
    # use None as the sentinel and resolve inside the body.
    backend: str | None = Form(default=None),
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
        # Resolve the runtime-configured default (was a Form default before,
        # but FastAPI evaluates Form(default=...) once at route registration;
        # we want it re-resolved per-request so PUT /v1/backends/default takes
        # effect without a restart).
        backend_resolved = backend or config.get_default_backend()

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
                backend=backend_resolved,
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
        persona=v.persona,
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


# ---- /lab persistence layer ----


class ScorecardCellRequest(BaseModel):
    """PUT body for /v1/scorecard/{persona}/{backend}."""

    matches_original: Literal["yes", "no", "partial"] | None = None
    notes: str | None = None


class PersonaPromptsRequest(BaseModel):
    """PUT body for /v1/personas/prompts/{persona}. All three lengths required.

    Three lengths is the contract: short = clone-match check, medium =
    persona intro, long = narrative stress test. UI never sends partial
    updates — Save writes all three.
    """

    short: str
    medium: str
    long: str


@app.get("/v1/scorecard")
async def get_scorecard() -> dict:
    """Return the full scorecard. Keyed by persona then backend."""
    return lab_state.read_scorecard()


@app.put("/v1/scorecard/{persona}/{backend}")
async def put_scorecard_cell(persona: str, backend: str, req: ScorecardCellRequest) -> dict:
    """Merge an update into one (persona, backend) scorecard cell.

    Either field may be omitted — only the keys you send are updated.
    Pass ``matches_original=null`` explicitly to clear that field.
    """
    try:
        cell = lab_state.update_scorecard_cell(
            persona,
            backend,
            matches_original=req.matches_original,
            notes=req.notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return cell


@app.get("/v1/personas/prompts")
async def get_personas_prompts() -> dict:
    """Return the full per-persona prompts dict."""
    return lab_state.read_persona_prompts()


@app.put("/v1/personas/prompts/{persona}")
async def put_persona_prompts(persona: str, req: PersonaPromptsRequest) -> dict:
    """Replace the prompts block for one persona (short/medium/long)."""
    try:
        block = lab_state.update_persona_prompts(
            persona, short=req.short, medium=req.medium, long=req.long
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return block


class PresetSampleRequest(BaseModel):
    """POST body for /v1/presets/{backend}/sample."""

    preset_id: str
    text: str = "Can you hear me?"


@app.get("/v1/presets/{backend}")
async def list_presets(backend: str) -> dict:
    """Return the backend's KNOWN_PRESETS catalog (id + language + gender + label).

    Works for any backend whose module imports — even when its subprocess
    venv isn't provisioned yet, so the UI can show the menu before install.
    Returns 404 if the backend is unknown OR doesn't declare KNOWN_PRESETS.
    """
    if backend not in known_backends():
        raise HTTPException(
            status_code=404, detail=f"unknown backend {backend!r}; known: {known_backends()}"
        )
    try:
        load_backend_module(backend)
    except (ImportError, KeyError) as exc:
        raise HTTPException(
            status_code=503,
            detail=f"backend {backend!r} module not importable: {exc!r}",
        ) from exc
    cls = get_backend(backend)
    presets = getattr(cls, "KNOWN_PRESETS", None)
    if presets is None:
        raise HTTPException(
            status_code=404,
            detail=f"backend {backend!r} has no KNOWN_PRESETS (not a preset backend?)",
        )
    return {"backend": backend, "data": presets}


@app.post("/v1/presets/{backend}/sample")
async def sample_preset(backend: str, req: PresetSampleRequest) -> Response:
    """Synthesize a one-shot sample from a backend preset without touching the registry.

    Used by /lab's preset browser so you can audition all 54 Kokoro presets
    (or 20 Piper voices, etc.) without registering them. Returns the WAV
    as audio/wav.

    503 if the backend's subprocess venv isn't provisioned
    (`voice-forge backend install <name>`).
    """
    if backend not in known_backends():
        raise HTTPException(
            status_code=404, detail=f"unknown backend {backend!r}; known: {known_backends()}"
        )
    try:
        backend_inst = _ensure_backend(backend)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"backend load failed: {exc!r}") from exc

    # Build a transient VoiceRef — preset_id set, no registry write.
    from .backends import VoiceRef as _VoiceRef

    transient_ref = _VoiceRef(
        voice_id=f"__preset_sample__{backend}_{req.preset_id}",
        backend=backend,
        preset_id=req.preset_id,
        metadata={"language": "en"},
    )
    try:
        audio = await run_in_threadpool(backend_inst.synthesize, req.text, transient_ref)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"preset sample synth failed: {exc!r}") from exc
    wav_bytes = _samples_to_wav_bytes(audio)
    return Response(content=wav_bytes, media_type="audio/wav")


@app.get("/v1/voices/{voice_id}/reference")
async def get_voice_reference(voice_id: str) -> FileResponse:
    """Serve the clone-source ref.wav for a voice.

    Used by /lab so reviewers can A/B the clone against the source audio.
    Returns 404 when the voice doesn't have a ref WAV — typical for
    preset-only backends (kokoro, piper, melotts).
    """
    registry = _registry()
    try:
        v = registry.get(voice_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"voice {voice_id!r} not in registry") from exc
    if not v.ref_audio_path or not Path(v.ref_audio_path).is_file():
        raise HTTPException(
            status_code=404,
            detail=f"voice {voice_id!r} has no reference audio (preset-only backend?)",
        )
    return FileResponse(v.ref_audio_path, media_type="audio/wav")


# ---- Live in-browser WS demo ----

_DEMO_HTML_PATH = Path(__file__).resolve().parent / "static" / "live_demo.html"
_LAB_HTML_PATH = Path(__file__).resolve().parent / "static" / "lab.html"


@app.get("/demo", response_class=HTMLResponse)
async def demo_page() -> FileResponse:
    """Static HTML demo page that opens a WebSocket back to this server.

    Visit ``http://<host>:<port>/demo`` in a browser. The page connects to
    ``ws://<host>:<port>/v1/tts/stream``, sends text the way an upstream LLM
    would (token-trickle), and plays each PCM frame the server pushes back
    using the Web Audio API. Same-origin keeps CORS out of the picture.
    """
    if not _DEMO_HTML_PATH.is_file():
        raise HTTPException(status_code=500, detail=f"demo page missing at {_DEMO_HTML_PATH}")
    return FileResponse(_DEMO_HTML_PATH, media_type="text/html")


@app.get("/lab", response_class=HTMLResponse)
async def lab_page() -> FileResponse:
    """Voice tuning + scoring workstation — persona × backend matrix.

    See ``.claude/plans/2026-05-25-voice-lab-tuning-workstation.md`` for the
    design. Pairs with /v1/scorecard + /v1/personas/prompts + /v1/presets/*
    + /v1/voices/{id}/reference endpoints.
    """
    if not _LAB_HTML_PATH.is_file():
        raise HTTPException(status_code=500, detail=f"lab page missing at {_LAB_HTML_PATH}")
    return FileResponse(_LAB_HTML_PATH, media_type="text/html")


# ---- Layer-2 streaming: WebSocket bidirectional ----

# Wire protocol (client ↔ server, all text frames are JSON):
#
#   client → server
#     {"voice": "saga-comms-f5"}              # FIRST message — voice binding
#     {"text": "Once upon "}                  # append text to buffer
#     {"text": "...", "end": true}            # final text + signal done
#     {"end": true}                           # standalone end signal
#
#   server → client
#     {"event":"session", "voice":..., "backend":..., "sample_rate":24000,
#      "channels":1, "format":"pcm_f32le"}
#     {"event":"sentence_start", "idx":0, "text":"Once upon a time."}
#     <binary frame: float32-LE PCM at sample_rate Hz>     # one per sentence
#     {"event":"sentence_done", "idx":0, "samples":12000, "synth_ms":4127}
#     {"event":"complete", "sentences_total": 4}
#     {"event":"error", "detail":"..."}     # then close
#
# The first-text-token to first-audio latency is what this surface is
# optimized for. Layer-1 HTTP streaming saves you "time-to-first-audio
# given a known utterance"; layer-2 also saves you the upstream LLM's
# generation time, because synth begins as soon as the FIRST complete
# sentence arrives — not when the whole utterance is known.


@app.websocket("/v1/tts/stream")
async def ws_tts_stream(ws: WebSocket) -> None:
    """Bidirectional streaming: text-in, audio-out, one sentence at a time."""
    await ws.accept()
    metrics.active_ws_connections.inc()
    try:
        try:
            init = await ws.receive_json()
        except WebSocketDisconnect:
            return
        await _handle_ws_session(ws, init)
    finally:
        metrics.active_ws_connections.dec()


async def _handle_ws_session(ws: WebSocket, init: object) -> None:
    """Body of ws_tts_stream extracted so the active-connections gauge can wrap it.

    Keeps the gauge balanced even on early returns / exceptions.
    """
    voice_id = init.get("voice") if isinstance(init, dict) else None
    if not voice_id:
        await ws.send_json({"event": "error", "detail": "first message must include 'voice'"})
        await ws.close(code=1008)
        return
    try:
        voice_ref = _registry().get(voice_id)
    except KeyError:
        await ws.send_json({"event": "error", "detail": f"voice {voice_id!r} not in registry"})
        await ws.close(code=1008)
        return

    # Optional request-scope sampling overrides on the init frame:
    #   {"voice": "saga", "sampling": {"nfe_step": 16, "cfg_strength": 2.5}}
    # The demo page sends this when the user has edited knob inputs. Clone the
    # voice_ref + merge so the registry's cached metadata isn't mutated by one
    # session's overrides.
    init_sampling = init.get("sampling") if isinstance(init, dict) else None
    if isinstance(init_sampling, dict) and init_sampling:
        merged_metadata = dict(voice_ref.metadata)
        merged_sampling = dict(merged_metadata.get("sampling") or {})
        merged_sampling.update(init_sampling)
        merged_metadata["sampling"] = merged_sampling
        voice_ref = replace(voice_ref, metadata=merged_metadata)

    try:
        backend = _ensure_backend(voice_ref.backend, voice_ref.metadata)
    except HTTPException as exc:
        await ws.send_json({"event": "error", "detail": exc.detail})
        await ws.close(code=1011)
        return

    await ws.send_json(
        {
            "event": "session",
            "voice": voice_id,
            "backend": voice_ref.backend,
            "sample_rate": SAMPLE_RATE,
            "channels": 1,
            "format": "pcm_f32le",
        }
    )

    buffer = SentenceBuffer()
    # asyncio.Queue lets the producer (WS-receive coroutine) hand sentences
    # to the consumer (synth-and-send coroutine) as soon as each sentence
    # boundary forms. The producer is then free to keep pulling text frames
    # while the consumer is mid-synth — which is the layer-2 pipelining win
    # (synth(s2) starts as soon as the SentenceBuffer emits it, NOT after
    # synth(s1) + send(s1) have finished). The F5 backend's threading.Lock
    # still serializes the actual synth work, but the WS receive path is no
    # longer blocked behind synth.
    #
    # ``None`` is the "no more sentences" sentinel pushed by the producer
    # once the client signals ``end: true`` and the buffer is flushed.
    sentence_queue: asyncio.Queue[tuple[int, str] | None] = asyncio.Queue()
    sentence_idx_total = 0  # mutated by the producer; read by the final complete frame
    error_state: dict[str, str] = {}  # set by either task on failure

    async def _synth_and_send(sentence: str, idx: int) -> None:
        import time

        await ws.send_json({"event": "sentence_start", "idx": idx, "text": sentence})
        t0 = time.monotonic()
        audio = await run_in_threadpool(backend.synthesize, sentence, voice_ref)
        synth_sec = time.monotonic() - t0
        synth_ms = int(synth_sec * 1000)
        metrics.synth_seconds.labels(
            backend=voice_ref.backend, voice_id=voice_id, mode="stream"
        ).observe(synth_sec)
        metrics.ws_sentences_total.labels(backend=voice_ref.backend, voice_id=voice_id).inc()
        await ws.send_bytes(np.asarray(audio, dtype=np.float32).tobytes())
        await ws.send_json(
            {
                "event": "sentence_done",
                "idx": idx,
                "samples": int(len(audio)),
                "synth_ms": synth_ms,
            }
        )

    async def receive_producer() -> None:
        nonlocal sentence_idx_total
        end_received = False
        try:
            while not end_received:
                try:
                    msg = await ws.receive_json()
                except WebSocketDisconnect:
                    # Client gone; signal consumer to drain + exit
                    return
                if not isinstance(msg, dict):
                    continue
                chunk = msg.get("text") or ""
                if chunk:
                    for sentence in buffer.feed(chunk):
                        await sentence_queue.put((sentence_idx_total, sentence))
                        sentence_idx_total += 1
                if msg.get("end"):
                    end_received = True
                    tail = buffer.flush()
                    if tail:
                        await sentence_queue.put((sentence_idx_total, tail))
                        sentence_idx_total += 1
        except Exception as exc:
            error_state["producer"] = repr(exc)
            logger.exception("ws producer failure for voice=%r", voice_id)
        finally:
            # Always tell the consumer "no more" so it can exit cleanly.
            await sentence_queue.put(None)

    async def synth_consumer() -> None:
        while True:
            item = await sentence_queue.get()
            if item is None:
                return
            idx, sentence = item
            try:
                await _synth_and_send(sentence, idx)
            except Exception as exc:
                error_state["consumer"] = repr(exc)
                logger.exception("ws consumer failure for voice=%r", voice_id)
                return

    try:
        # Producer + consumer run concurrently. The producer hands sentences
        # to the consumer via the queue and pushes ``None`` when done, so
        # gather() naturally completes once both halves finish.
        producer_task = asyncio.create_task(receive_producer())
        consumer_task = asyncio.create_task(synth_consumer())
        await asyncio.gather(producer_task, consumer_task)
        if error_state:
            detail = error_state.get("consumer") or error_state.get("producer") or "unknown"
            await ws.send_json({"event": "error", "detail": detail})
            await ws.close(code=1011)
            return
        await ws.send_json({"event": "complete", "sentences_total": sentence_idx_total})
    except Exception as exc:  # belt-and-suspenders — task-level errors already trapped above
        logger.exception("ws_tts_stream outer failure for voice=%r", voice_id)
        try:
            await ws.send_json({"event": "error", "detail": str(exc)})
        except Exception:
            pass
        await ws.close(code=1011)
        return
    await ws.close()
