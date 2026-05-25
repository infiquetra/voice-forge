# API Specification — voice-forge v0.2

> REST + WebSocket. FastAPI auto-generates an OpenAPI 3.1 spec for the REST surface at `GET /openapi.json`; this document is the human-facing companion plus the canonical contract for the WebSocket endpoint (OpenAPI 3.1 doesn't model WebSockets cleanly). Wyoming protocol adapter is queued — see [ROADMAP.md](ROADMAP.md).

## Base URL

`http://<host>:<port>/` — default `127.0.0.1:9876` (localhost-only in v0.2; bearer-token auth comes in v0.3 — see [ROADMAP.md](ROADMAP.md) and [QUEUED.md](engineering-journal/QUEUED.md) § "OpenAI-API-compatible auth").

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
- Body: audio bytes (chunked transfer if `stream: true` — see [Streaming format](#streaming-format-layer-1-chunked-http) below)
- Headers: `X-Voice-Forge-Backend: f5`, `X-Voice-Forge-Audio-Sec: 9.50`

**Response 404**: voice not in registry
**Response 502**: backend failure (model crashed, ref audio missing, etc.)

### `GET /v1/audio/voices` — List voices

OpenAI-compatible listing endpoint.

**Response**:
```json
{
  "data": [
    {
      "id": "saga",
      "backend": "f5",
      "language": "en",
      "description": "Saga (history-keeper, dry-witted)",
      "metadata": {"sampling": {"nfe_step": 16}}
    },
    ...
  ]
}
```

### `POST /voices/{voice_id}` — Register voice

**Form-data**:
- `ref_audio`: WAV file (3-15 seconds clean speech)
- `ref_text` (optional): matching transcript; if absent, voice-forge Whisper-transcribes
- `backend` (default: `f5`): which backend handles this voice
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

### `GET /metrics` — Prometheus scrape endpoint

Prometheus exposition format (`Content-Type: text/plain; version=0.0.4; charset=utf-8`). Auth-exempt — monitoring infrastructure scrapes without needing a token.

Core metrics emitted:

| Metric | Type | Labels | Meaning |
|---|---|---|---|
| `voice_forge_synth_seconds` | Histogram | `backend`, `voice_id`, `mode` (batch / stream) | Wall-clock seconds per synth call |
| `voice_forge_synth_requests_total` | Counter | `backend`, `voice_id`, `mode`, `status` (ok / fail) | Synth call count |
| `voice_forge_backend_loaded` | Gauge | `backend` | 1 if loaded in this process, 0 otherwise |
| `voice_forge_voices_registered` | Gauge | (none) | Total voices in the registry directory |
| `voice_forge_active_ws_connections` | Gauge | (none) | WebSocket clients currently connected |
| `voice_forge_ws_sentences_total` | Counter | `backend`, `voice_id` | Sentences synthesized through the WS layer-2 stream |

Cardinality note: `voice_id` is a label. For small deploys (≤100 voices) fine; for multi-tenant deploys with thousands of voice_ids this would explode Prometheus's TSDB. Cap is queued — see [QUEUED.md](engineering-journal/QUEUED.md).

### `GET /health` — Service health

```json
{
  "ok": true,
  "version": "0.2.0",
  "registry_dir": "/home/user/.voice-forge/voices",
  "voices_count": 9,
  "backends_available": ["f5", "kokoro", "neutts", "xtts", "dia"],
  "backends_loaded": ["f5"]
}
```

### `GET /demo` — Live in-browser streaming demo

Static HTML page (vanilla JS + Web Audio API) that opens a same-origin WebSocket to `/v1/tts/stream`. Voice picker auto-populates from `/v1/audio/voices`; the page lets you type or paste text, optionally trickle it at LLM-token cadence, and hear the streamed PCM live in your browser. See `src/voice_forge/static/live_demo.html` for the implementation.

## Streaming format — Layer-1 (chunked HTTP)

When `POST /v1/audio/speech` is called with `stream: true`, the response uses `Transfer-Encoding: chunked` and writes audio bytes progressively as they're synthesized. Server-side, the text is split on sentence boundaries (see `src/voice_forge/backends/_chunking.py`) and each chunk's PCM is yielded as soon as synth completes. Format depends on `response_format`:

- `wav`: WAV header (with placeholder data size = 0xFFFFFFFF), then int16 PCM samples appended as each sentence finishes. Most decoders handle the bogus size correctly.
- `pcm`: raw 24 kHz mono int16, no header.
- `mp3` / `opus`: encoded via FFmpeg subprocess — falls back to batch synth (not progressive) because the codecs need the full WAV to encode efficiently.

Client picks based on the player it's feeding (`ffmpeg`, browser `<audio>`, Discord `FFmpegPCMAudio`, etc.).

**First-audio latency** scales with the size of the first sentence, not the full text — see [LEARNINGS § "Sentence-chunked synthesize_stream gives 10× first-audio win on F5 long-form"](engineering-journal/LEARNINGS.md).

Per-voice override: `metadata.sampling.stream_chunk_chars` controls the chunker's max-chunk size. F5 default is 1000; HTTP layer-1 streaming use cases often want this set to 200 for finer-grained chunking.

## Streaming surface — Layer-2 (WebSocket)

### `WS /v1/tts/stream` — Bidirectional text-in / audio-out

Persistent WebSocket. Text streams in (token-by-token from an LLM, or all at once), audio streams out as the server's `SentenceBuffer` drains complete sentences. This is the surface to use when the upstream is itself a stream — the synth wins start at the *first sentence* boundary, not the full-text boundary.

#### Wire protocol

Client → server (all text frames, JSON):

```jsonc
// FIRST message — voice binding
{"voice": "saga"}

// Append text to the server-side buffer (zero or more times)
{"text": "Once upon "}
{"text": "a time, Loki "}
{"text": "stole the apples."}

// Final text + signal "no more coming"
{"text": " The end.", "end": true}

// OR signal end with no extra text
{"end": true}
```

Server → client (mix of JSON text frames + binary frames):

```jsonc
// Sent once, immediately after the {"voice": ...} handshake
{
  "event": "session",
  "voice": "saga",
  "backend": "f5",
  "sample_rate": 24000,
  "channels": 1,
  "format": "pcm_f32le"
}

// Per sentence the SentenceBuffer emits — sentence_start, then a single
// BINARY WS frame carrying the float32-LE PCM for that sentence,
// then sentence_done
{"event": "sentence_start", "idx": 0, "text": "Once upon a time, Loki stole the apples."}
<binary frame: float32-LE PCM at 24 kHz mono>
{"event": "sentence_done", "idx": 0, "samples": 87234, "synth_ms": 3128}

// On client {"end": true} after all sentences flushed
{"event": "complete", "sentences_total": 4}

// Error before close (close code 1008 for client errors, 1011 for server errors)
{"event": "error", "detail": "voice 'unknown' not in registry"}
```

#### Audio frame contract

- Type: binary WebSocket frame
- Layout: little-endian IEEE-754 float32 mono PCM
- Sample rate: `session.sample_rate` (24000 for all current backends)
- One binary frame per sentence (matches `sentence_done.samples`)
- Range: nominally `[-1.0, 1.0]`; consumer should clip / convert before playback

#### Sentence-boundary semantics

The server holds incoming text in a `SentenceBuffer` (see `src/voice_forge/sentence_buffer.py`) and emits a sentence when it sees `[.!?]+` followed by `\s+`. The trailing whitespace is the disambiguator that tells the buffer "the next sentence has started" — without it, `"Dr."` might still be an abbreviation. On `{"end": true}` any trailing non-empty buffer is flushed as one last sentence regardless of terminal punctuation.

#### Why use this instead of REST chunked streaming

REST chunked (`POST /v1/audio/speech` with `stream: true`) requires the caller to know the full text up front. WebSocket allows the caller to *stream text in* — useful when the upstream is an LLM (or live captioning, or any token-by-token producer). The total end-to-end latency drops from `LLM_full_time + first_chunk_synth` to `LLM_first_sentence_time + first_chunk_synth`.

See [DECISIONS 2026-05-25 § F5 default backend](engineering-journal/DECISIONS.md) for the streaming-preset (nfe_step=16) that pairs with this surface.

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

## Authentication (future, v0.3+)

v0.2 is **localhost-only, no auth**. When we expose externally (queued for v0.3), plan is:
- Bearer token in `Authorization: Bearer <token>` header for REST
- Same bearer token in the first WS `{"voice": "...", "token": "..."}` frame for layer-2 streaming
- Tokens managed by simple FS-backed token store (or via env vars)
- Optional: OpenAI-API-compatible `api_key` header for SDK drop-in compatibility
