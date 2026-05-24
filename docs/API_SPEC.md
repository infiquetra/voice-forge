# API Specification — voice-forge v0

> REST + OpenAPI. v0 endpoints below. WebSocket + Wyoming are tracked separately in [ROADMAP.md](ROADMAP.md).

## Base URL

`http://<host>:<port>/` — default `127.0.0.1:9876` (localhost-only in v0; auth comes when we expose externally).

## Endpoints

### `POST /v1/audio/speech` — Synthesize

OpenAI-compatible. Mirrors `openai.audio.speech.create()`.

**Request body** (JSON):
```json
{
  "model": "voice-forge",            // accepted for OpenAI-SDK compat; mostly informational
  "input": "Hello world.",            // text to synthesize
  "voice": "saga-comms",              // voice_id from registry
  "response_format": "wav",           // wav | mp3 | opus | pcm
  "speed": 1.0,                        // playback speed (clamped 0.25..4.0)
  "stream": false                      // false = full WAV body; true = chunked transfer
}
```

**Response 200**:
- Content-Type: `audio/wav` (or `audio/mpeg`, `audio/opus`, `audio/pcm`)
- Body: audio bytes (chunked transfer if `stream: true`)
- Headers: `X-Voice-Forge-Backend: neutts`, `X-Voice-Forge-Synth-Sec: 3.21`, `X-Voice-Forge-Audio-Sec: 9.50`, `X-Voice-Forge-Rtf: 0.34`

**Response 404**: voice not in registry
**Response 502**: backend failure (model crashed, ref audio missing, etc.)

### `GET /v1/audio/voices` — List voices

OpenAI-compatible listing endpoint.

**Response**:
```json
{
  "data": [
    {
      "id": "saga-comms",
      "backend": "neutts",
      "language": "en",
      "description": "Saga (history-keeper, dry-witted)",
      "metadata": {...}
    },
    ...
  ]
}
```

### `POST /voices/{voice_id}` — Register voice

**Form-data**:
- `ref_audio`: WAV file (3-15 seconds clean speech)
- `ref_text` (optional): matching transcript; if absent, voice-forge Whisper-transcribes
- `backend`: which backend handles this voice (default: server's `default_backend`)
- `metadata`: JSON blob (description, language, etc.)

**Response 201**: voice added to registry
**Response 409**: voice_id already exists (use PUT to replace)

### `POST /voices/from-elevenlabs` — Pull from ElevenLabs Voice Lab

**Request body** (JSON):
```json
{
  "voice_id": "saga-comms",                            // target ID in voice-forge registry
  "elevenlabs_voice_id": "c7qAAWgc7aGYHCLDzd8Y",       // source voice in ElevenLabs
  "elevenlabs_api_key": "sk_...",                       // ElevenLabs auth (or set env ELEVENLABS_API_KEY)
  "auto_trim": true,                                    // Whisper-trim to clean sentence boundary
  "language": "en"                                      // forced Whisper language (skips auto-detect)
}
```

**Response 201**:
```json
{
  "voice_id": "saga-comms",
  "ref_audio_path": "~/.voice-forge/voices/saga-comms/ref.wav",
  "ref_text": "...",
  "duration_sec": 9.20,
  "source": "elevenlabs:c7qAAWgc7aGYHCLDzd8Y"
}
```

### `DELETE /voices/{voice_id}` — Remove

### `GET /voices/{voice_id}` — Get metadata

### `GET /health` — Service health

```json
{
  "ok": true,
  "version": "0.1.0",
  "backends_loaded": ["neutts"],
  "voices_count": 9,
  "uptime_sec": 1234
}
```

## Streaming format (chunked HTTP)

When `stream: true`, the response uses `Transfer-Encoding: chunked` and writes audio bytes progressively as they're synthesized. Format depends on `response_format`:

- `wav`: WAV header (with placeholder data size = 0xFFFFFFFF), then PCM samples. Most decoders handle the bogus size correctly.
- `mp3`: MP3 frames as they're encoded.
- `opus`: Opus frames.
- `pcm`: raw 24kHz mono int16, no header.

Client picks based on the player it's feeding (`ffmpeg`, browser `<audio>`, Discord `FFmpegPCMAudio`, etc.).

## Error responses

```json
{
  "error": {
    "code": "voice_not_found",
    "message": "voice 'saga-comms' not in registry",
    "request_id": "req_..."
  }
}
```

Codes:
- `voice_not_found` (404)
- `backend_unavailable` (503)
- `synthesis_failed` (502)
- `invalid_request` (400)
- `rate_limited` (429) — future, when auth exists

## OpenAPI schema

Auto-generated at `/openapi.json` (FastAPI's built-in). Browse at `/docs` (Swagger UI) or `/redoc` (ReDoc) when the server is running.

## Authentication (future, v0.2+)

v0 is **localhost-only, no auth**. When we expose externally, plan is:
- Bearer token in `Authorization` header
- Tokens managed by simple FS-backed token store (or via env vars)
- Optional: OpenAI-API-compatible "api_key" header for SDK drop-in
