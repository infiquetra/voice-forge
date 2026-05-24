# Architecture

## Overview

```
HTTP client (hermes-agent shim, curl, OpenAI SDK, etc.)
         │
         │  POST /v1/audio/speech  {voice_id, input, response_format, stream}
         ▼
┌─────────────────────────────────────────────────────────────┐
│  FastAPI app  (src/voice_forge/server.py)                   │
│  - Validates request schema (pydantic)                       │
│  - Looks up voice from Registry                              │
│  - Dispatches to the voice's configured backend              │
│  - Streams response (chunked HTTP) or returns full WAV       │
└─────────────────┬───────────────────────────────────────────┘
                  │
        ┌─────────┴──────────┐
        ▼                    ▼
┌──────────────┐      ┌──────────────────────────────────────┐
│ Registry     │      │ Backend Protocol                      │
│ (FS-backed)  │      │ (src/voice_forge/backends/__init__.py)│
│              │      │                                       │
│ ~/.voice-    │      │  class TTSBackend(Protocol):          │
│  forge/      │      │      name: str                        │
│  voices/     │      │      def load(...)                    │
│  <voice_id>/ │      │      def encode_reference(...)         │
│   ref.wav    │      │      def synthesize(text, ref)        │
│   ref.txt    │      │      def synthesize_stream(text, ref) │
│   metadata   │      │      def health()                     │
│   .json      │      │                                       │
└──────────────┘      └──────────────┬───────────────────────┘
                                     │
              ┌──────────────────────┼──────────────────────┐
              ▼                      ▼                      ▼
        ┌──────────┐          ┌──────────┐         ┌──────────┐
        │ NeuTTS   │          │ Kokoro   │         │ XTTS-v2  │
        │ backend  │          │ backend  │         │ backend  │
        │ (v0)     │          │ (v0.2)   │         │ (v0.3+)  │
        └──────────┘          └──────────┘         └──────────┘

Side-channel: Voice Lab
┌──────────────────────────────────────────────────────────────┐
│  POST /voices/from-elevenlabs   {voice_id, api_key}          │
│  POST /voices/{id}/trim         (Whisper-based ref trim)     │
│  ─────────────────────────────                                │
│  voice_lab.elevenlabs.pull_preview(voice_id) → WAV           │
│  voice_lab.trim_to_sentence_boundary(wav) → trimmed WAV      │
│  Writes resulting ref into Registry                          │
└──────────────────────────────────────────────────────────────┘
```

## Core abstractions

### `TTSBackend` Protocol

The contract any backend must implement. The Protocol approach (vs ABC) means backends can be plain classes without inheritance — they just need to expose the right methods.

```python
from typing import Protocol, Iterator
import numpy as np

class TTSBackend(Protocol):
    name: str  # canonical short name e.g. "neutts", "kokoro"

    def load(self, config: dict) -> None:
        """One-time load of model weights + warm-up."""

    def encode_reference(self, ref_audio_path: str) -> ReferenceCodes | None:
        """For cloning backends: encode ref WAV to model-native codes.
        Return None for preset-voice backends (Kokoro, Kitten) that don't use ref audio."""

    def synthesize(self, text: str, ref: VoiceRef) -> np.ndarray:
        """Batch synth: return full PCM (float32 [-1, 1], 24kHz mono by convention)."""

    def synthesize_stream(self, text: str, ref: VoiceRef) -> Iterator[np.ndarray]:
        """Streaming synth: yield PCM chunks as they're produced.
        Backends without native streaming yield in one chunk (degrades to batch)."""

    def health(self) -> dict:
        """Return diagnostics (model loaded? hardware? warm?)."""
```

### `VoiceRef` union dataclass

The three voice-cloning paradigms in the wild:

```python
@dataclass
class VoiceRef:
    backend: str                       # which backend handles this voice
    ref_audio_path: str | None = None  # XTTS, F5, NeuTTS (raw ref WAV)
    ref_text: str | None = None        # NeuTTS (transcript matching ref audio)
    preset_id: str | None = None       # Kokoro, Kitten (named voice in model)
    encoded_codes: list | None = None  # NeuTTS pre-encoded (optimization)
    metadata: dict = field(default_factory=dict)  # description, language, etc.
```

A backend pulls what it needs:
- NeuTTS: `(encoded_codes or encode_reference(ref_audio_path), ref_text)`
- XTTS: `ref_audio_path`
- F5: `ref_audio_path`
- Kokoro: `preset_id`
- Kitten: `preset_id`
- Dia: `ref_audio_path` (audio prompt for speaker conditioning)

### `Registry`

FS-backed voice library. Each voice lives at `~/.voice-forge/voices/<voice_id>/`:

```
~/.voice-forge/voices/saga-comms/
├── ref.wav              # the reference audio
├── ref.txt              # matching transcript (for backends that need it)
└── metadata.json        # {"backend": "neutts", "model": "neuphonic/neutts-air-q8-gguf",
                         #  "language": "en", "description": "...", "elevenlabs_voice_id": "..."}
```

Operations:
- `Registry.list() -> list[VoiceRef]`
- `Registry.get(voice_id) -> VoiceRef`
- `Registry.register(voice_id, ref_audio_path, metadata) -> VoiceRef`
- `Registry.delete(voice_id) -> None`

Backed by simple FS reads + writes. No DB in v0. Future: SQLite for richer querying, S3-compatible for distributed deployments.

### `Voice Lab`

Convenience utilities for the "how do I get a clean ref WAV" workflow:

- `voice_lab.elevenlabs.pull_preview(voice_id, api_key) -> Path` — download the ElevenLabs Voice Lab preview MP3
- `voice_lab.trim_to_sentence_boundary(wav_path, max_seconds=14) -> Path` — Whisper-transcribe, find the last complete-sentence boundary, trim
- `voice_lab.whisper_transcribe(wav_path, language="en") -> str` — get matching ref_text for cloning backends

These can be called from the HTTP server (`POST /voices/from-elevenlabs`) OR the CLI (`voice-forge voice from-elevenlabs <id>`).

## Why a Protocol (not ABC)

- Backends can live in third-party packages without depending on voice-forge directly. Anyone with `class MyBackend: name = "..."; def synthesize(...)` etc. satisfies the Protocol.
- Tests can use lightweight fakes without inheriting from a base class.
- Mirrors the "duck-typing-with-static-checking" style of modern Python (3.8+).

ABC is fine too; Protocol is preferred here for plugin-style extensibility.

## Why no DB in v0

- File-system registry is human-readable and grep-able
- Easy to version-control your voice library (it's just files)
- Works with rsync / scp / etc. for cross-host deployment
- SQLite or richer storage can come later when query patterns demand it

## Why FastAPI

- Async/await throughout (vs Flask's thread-locked default)
- Built-in pydantic validation matches our typed Python style
- OpenAPI schema auto-generation for /v1/audio/speech etc.
- `StreamingResponse` is a clean primitive for chunked transfer (validated by xtts-streaming-server)
- Industry-standard for Python ML APIs (matches HuggingFace InferenceClient, OpenAI Python SDK shape)

## Why HTTP/REST (not Wyoming or sockets)

See [PRIOR_ART.md](PRIOR_ART.md) for the full reasoning. Short version:

- REST is the lingua franca for service integration
- ~1-2ms HTTP overhead is irrelevant when synthesis takes seconds
- Lets us deploy to remote hosts in the future
- Wyoming (Home Assistant's protocol) is opt-in via adapter in v0.2+

## Concurrency model

- FastAPI app is async; uvicorn worker pool
- Backends are typically NOT thread-safe (especially Llama-cpp / PyTorch models)
- Per-backend lock (`asyncio.Lock`) serializes inference on the same backend instance
- Different backends can run in parallel (Kokoro and NeuTTS can synth simultaneously)
- For high-throughput needs, run multiple voice-forge instances behind a load balancer (stateless except for FS registry)

## Streaming model (v0)

Chunked HTTP transfer. The server's `synthesize_stream()` generator yields PCM chunks; FastAPI's `StreamingResponse` writes them as the WAV/MP3 body grows. Client (curl, FFmpeg, etc.) reads them progressively.

For backends without native streaming, `synthesize_stream` falls back to a single chunk (degrades to batch).

WebSocket + Wyoming bidirectional streaming are tracked in v0.2 (see [ROADMAP.md](ROADMAP.md)).

## Deployment shapes

- **Local dev**: `voice-forge serve --host 127.0.0.1 --port 9876` from a venv
- **Docker (Mac mini / Linux)**: see [`docker/Dockerfile`](../docker/Dockerfile) — single-container deploy
- **Ansible-managed (home-lab pattern)**: `ansible/roles/hermes_neutts_daemon/` in [infiquetra/home-lab](https://github.com/namredips/home-lab) installs voice-forge via `uv pip install voice-forge==<tag>`, configures persona voices, runs as launchd service on Mac mini
- **k8s (future)**: helm chart in v0.3+ if multi-tenant deployment matters

## Future directions

See [ROADMAP.md](ROADMAP.md) for the full backend + feature roadmap.
