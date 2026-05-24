# voice-forge

**Pluggable TTS service for agent voices** — a self-hosted text-to-speech engine with cloning, voice library management, and a REST API.

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Status: v0 / pre-release](https://img.shields.io/badge/status-v0%2Fpre--release-orange.svg)](docs/ROADMAP.md)

## What it is

voice-forge is the engine layer for "give your agent a voice". It does four things:

1. **Synthesis** — text → audio via pluggable TTS backends (NeuTTS in v0; F5-TTS, XTTS-v2, Kokoro, Dia, Kitten planned)
2. **Cloning** — record a voice once via ref audio, replay it on any text
3. **Voice Lab** — pull voices from ElevenLabs, trim references to clean sentence boundaries, manage a local voice library
4. **Service surface** — OpenAI-API-compatible REST endpoint + CLI for direct text→WAV testing without needing a chat platform

## Why it exists

If you're building voice agents, you want:
- Local TTS so accent / persona character stays consistent
- Easy backend swapping when a new TTS model lands
- A test loop that doesn't require booting Discord / your chat platform
- One canonical voice library across all the agents you run

The existing self-hosted TTS landscape (see [docs/PRIOR_ART.md](docs/PRIOR_ART.md)) has the pieces scattered across different projects. voice-forge stitches them together.

## Quick start (when v0.1.0 ships)

```bash
# Install
uv pip install voice-forge

# Run the server
voice-forge serve --host 127.0.0.1 --port 9876

# Synth directly (no server)
voice-forge synth example "Hello from voice-forge." /tmp/hello.wav

# Pull a voice from ElevenLabs and add to local library
export ELEVENLABS_API_KEY=...
voice-forge voice from-elevenlabs <voice_id>

# Use via HTTP (OpenAI-compatible)
curl http://127.0.0.1:9876/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{"model": "voice-forge", "input": "Hello.", "voice": "example", "response_format": "wav"}' \
  --output speech.wav
```

## Status

**v0 pre-release.** Not on PyPI yet. Working code lives on the `main` branch; tag `v0.1.0` will be the first release.

- Backend: NeuTTS Air (Apache-2, working today)
- Other backends: see [ROADMAP.md](docs/ROADMAP.md)
- API: REST (chunked transfer for streaming). WebSocket + Wyoming opt-in adapters planned for v0.2.

## Architecture

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Short version:

```
HTTP client → FastAPI server → Backend Protocol → [NeuTTS | F5 | XTTS | Kokoro | Dia | Kitten]
                            → Voice Registry (FS-backed) → ~/.voice-forge/voices/<voice_id>/
                            → Voice Lab (ElevenLabs pull, ref trim, Whisper transcribe)
```

Backend abstraction is a `TTSBackend` Protocol with a `VoiceRef` union type that handles the variance between "voice = ref audio" (NeuTTS/F5/XTTS), "voice = preset ID" (Kokoro/Kitten), and "voice = encoded codes" (NeuTTS-pre-encoded).

## License

[Apache 2.0](LICENSE). Including a patent grant from contributors. Compatible with all the major Python ML ecosystem libraries this depends on (NeuTTS Apache-2, llama-cpp-python MIT, faster-whisper MIT, FastAPI MIT).

## Sibling repos

- [`infiquetra/voice-listen`](https://github.com/infiquetra/voice-listen) — sibling STT service (planned)

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Highlights:
- Add a new backend: implement `TTSBackend` Protocol, drop it under `src/voice_forge/backends/`, register in metadata
- Bug reports / feature requests: GitHub Issues
- Engineering journal: see [`docs/engineering-journal/`](docs/engineering-journal/) for the LEARNINGS / DECISIONS / QUEUED / ARCHIVE pattern we use

## Related

- [`infiquetra/home-lab`](https://github.com/namredips/home-lab) — the deployment that consumes voice-forge for the Asgard sister-voices fleet
- [Neuphonic/NeuTTS Air](https://github.com/neuphonic/neutts) — the underlying TTS model used by the v0 backend
