# voice-forge

**Pluggable TTS service for agent voices** — a self-hosted text-to-speech engine with cloning, voice library management, and a REST API.

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![PyPI](https://img.shields.io/badge/PyPI-voice--forge--tts-blue.svg)](https://pypi.org/project/voice-forge-tts/)
[![Status: v0.3](https://img.shields.io/badge/status-v0.3-orange.svg)](docs/ROADMAP.md)

> **PyPI distribution name:** `voice-forge-tts` (the bare `voice-forge` name on PyPI was taken before v0.1.0 published — see [docs/engineering-journal/ARCHIVE.md](docs/engineering-journal/ARCHIVE.md)). The Python import path stays `voice_forge`.

## What it is

voice-forge is the engine layer for "give your agent a voice". It does four things:

1. **Synthesis** — text → audio via pluggable TTS backends. **F5-TTS is the default** (identity-preserving cloning, long-form coherence). Also shipped: Kokoro (preset voices), NeuTTS (short-form cloning), XTTS-v2 (multilingual, license-gated), Dia-1.6B (multi-speaker).
2. **Cloning** — record a voice once via ref audio, replay it on any text
3. **The Forge** — design, clone, audition, tune, bind, and serve voices from the `/forge/` web studio; `/lab` remains the power-user workstation
4. **Service surface** — OpenAI-API-compatible REST + WebSocket layer-2 streaming for LLM-driven pipelines + CLI for direct text→WAV testing

## Why it exists

If you're building voice agents, you want:
- Local TTS so accent / persona character stays consistent
- Easy backend swapping when a new TTS model lands
- A test loop that doesn't require booting Discord / your chat platform
- One canonical voice library across all the agents you run

The existing self-hosted TTS landscape (see [docs/PRIOR_ART.md](docs/PRIOR_ART.md)) has the pieces scattered across different projects. voice-forge stitches them together.

## Quick start

```bash
# Install with the backends you want (extras are additive). F5 is the default:
uv pip install "voice-forge-tts[f5,voice-lab]"                  # F5 (recommended default)
uv pip install "voice-forge-tts[kokoro,voice-lab]"              # Kokoro preset voices
uv pip install "voice-forge-tts[neutts,voice-lab]"              # NeuTTS short-form cloning
uv pip install "voice-forge-tts[f5,kokoro,neutts,voice-lab]"    # all three identity backends
uv pip install "voice-forge-tts[all]"                           # everything incl. XTTS, Dia

# Kokoro requires espeak-ng on the host:
brew install espeak-ng        # macOS
# OR
apt-get install espeak-ng     # Linux

# Run the server (default backend = f5)
voice-forge serve --host 127.0.0.1 --port 9876

# Open The Forge (the browser front door)
open http://127.0.0.1:9876/forge/

# Synth directly (no server) — uses the default F5 backend
voice-forge synth example "Hello from voice-forge." /tmp/hello.wav

# Register a Kokoro preset voice
voice-forge voice add kokoro-bella --backend kokoro --preset af_bella

# Register an F5 clone from a ref WAV
voice-forge voice add saga /path/to/saga-ref.wav --ref-text "matching transcript"

# Tune a voice for streaming (16-step F5 is the streaming preset)
voice-forge voice tune saga --sampling nfe_step=16

# Pull a voice from ElevenLabs and add to local library
export ELEVENLABS_API_KEY=...
voice-forge voice from-elevenlabs my-voice --elevenlabs-voice-id <id>

# Use via HTTP (OpenAI-compatible REST)
curl http://127.0.0.1:9876/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{"model": "voice-forge", "input": "Hello.", "voice": "saga", "response_format": "wav", "stream": true}' \
  --output speech.wav

# Or use the WebSocket for token-streamed pipelines (LLM → voice-forge → audio)
# See docs/API_SPEC.md § "WS /v1/tts/stream" for the wire protocol.
```

**New here?** → [`docs/QUICKSTART.md`](docs/QUICKSTART.md) — five minutes from `pip install` to hearing a voice.

## Status

**v0.3.0 — SHIPPED 2026-08-25.**

- **The Forge:** `/` redirects to `/forge/`, a no-build web-component studio for design-from-description, clone-from-reference, audition, tuning, persona binding, and serving. The existing `/lab` workstation remains available.
- **Backends shipped:** F5-TTS (default, identity-preserving, MIT/Apache-2), Kokoro-82M (preset voices, Apache-2), NeuTTS Air (short-form cloning, Apache-2), XTTS-v2 (multilingual, MPL-2/CPML license-gated), Dia-1.6B (multi-speaker, Apache-2)
- **APIs:** OpenAI-compatible REST (`POST /v1/audio/speech` with `stream=false` for batch + `stream=true` for HTTP chunked layer-1 streaming) + WebSocket layer-2 streaming (`WS /v1/tts/stream`) for LLM-driven pipelines + browser-accessible live demo at `GET /demo`
- **Per-voice tuning:** sampling parameters (`nfe_step`, `cfg_strength`, `temperature`, `top_p`, etc.) overridable per voice via `voice-forge voice tune <id> --sampling KEY=VALUE`
- **Default for streaming:** F5 with `nfe_step=16` — verified audibly equivalent to 32-step on an 11-sentence stress test (see [LEARNINGS](docs/engineering-journal/LEARNINGS.md))
- **Release notes:** [`docs/engineering-journal/ARCHIVE.md`](docs/engineering-journal/ARCHIVE.md) is the changelog
- **What's next:** see [`docs/ROADMAP.md`](docs/ROADMAP.md) and [`docs/engineering-journal/QUEUED.md`](docs/engineering-journal/QUEUED.md)

## Contributing

```bash
# Set up dev env
uv venv && source .venv/bin/activate
uv pip install -e ".[dev,f5,kokoro,voice-lab]"

# Install pre-commit hooks (one-time)
pre-commit install

# Run the full gate suite locally — same checks CI runs
pre-commit run --all-files     # ruff + black + mypy + bandit + standard hygiene
pytest tests/ -v               # 198+ tests
```

CI runs the same gates on every PR; locally-passing pre-commit is the contract.

## Context for new contributors

If you're starting fresh on this repo, the engineering journal at [`docs/engineering-journal/`](docs/engineering-journal/) is the read-this-first place. It contains:

- [`narratives/2026-05-24-pre-history.md`](docs/engineering-journal/narratives/2026-05-24-pre-history.md) — what we learned from the NeuTTS daemon prototype that motivated this repo
- [`narratives/2026-05-24-voice-forge-spin-out.md`](docs/engineering-journal/narratives/2026-05-24-voice-forge-spin-out.md) — why we spun out from `infiquetra/home-lab` instead of building in-place
- [`LEARNINGS.md`](docs/engineering-journal/LEARNINGS.md) — 8 empirical findings (Q4+CPU faster than MPS, Perth watermarker artifacts, NeuTTS streaming content-loss, MP3 default bitrate gotcha, etc.) with mechanisms + fixes + generalizable rules
- [`DECISIONS.md`](docs/engineering-journal/DECISIONS.md) — 5 locked architectural choices (Apache-2, Q8 default, batch default, Protocol abstraction, REST surface) with rejected alternatives + revisit-when conditions
- [`QUEUED.md`](docs/engineering-journal/QUEUED.md) — ~20 prioritized future work items: backends (F5, XTTS, Kokoro, Dia, Kitten, MeloTTS, VibeVoice, Chatterbox, Piper), WebSocket / Wyoming, PyPI publishing, auth, etc.
- [`docs/PRIOR_ART.md`](docs/PRIOR_ART.md) — comparative study of 12 prior projects (Coqui, OpenedAI-Speech, xtts-streaming-server, Kokoro-FastAPI, Wyoming, Dia, Kitten + BentoML/Inworld surveys) with license compatibility matrix
- [`docs/BACKENDS.md`](docs/BACKENDS.md) — per-backend reference: license, voice paradigm, RTF, resident-memory cost, deployment-host capacity table, "pick this backend when..." decision guide

Together these answer "why is voice-forge designed the way it is" + "what's the next work to do" without requiring you to read the `infiquetra/home-lab` repo where this prototype originated.

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
