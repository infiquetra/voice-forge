# Roadmap

> Where voice-forge is heading. See `engineering-journal/QUEUED.md` for items in active consideration.

## v0.1.0 — current target (NeuTTS-only with pluggable backend architecture)

**Goal:** Ship the engine + one working backend, with the abstractions in place to add others.

**Includes:**
- [x] Repo scaffolded (Phase C of [home-lab plan](https://github.com/namredips/home-lab/blob/main/.claude/plans/) — DONE)
- [ ] `TTSBackend` Protocol + `VoiceRef` union dataclass (Phase D)
- [ ] NeuTTS backend (port of working v6 daemon from home-lab) (Phase D)
- [ ] FastAPI server: `POST /v1/audio/speech`, `GET /v1/audio/voices`, `GET /health`, `POST /voices/{id}`, `POST /voices/from-elevenlabs` (Phase D)
- [ ] CLI: `voice-forge serve`, `voice-forge synth`, `voice-forge voices`, `voice-forge voice add`, `voice-forge voice from-elevenlabs` (Phase D)
- [ ] Voice Lab puller (ElevenLabs preview → ref WAV) (Phase D)
- [ ] Ref trimmer (Whisper-based sentence-boundary cut) (Phase D)
- [ ] Tests: unit + integration (Phase D)
- [ ] Docker image (multi-stage build for CPU) (Phase D)
- [ ] CI: lint, format, type-check, tests on push (Phase C/D)

## v0.2.0 — pluggable proof

**Goal:** Add a second backend to prove the abstraction works, plus add streaming/WS surface.

- [ ] **Kokoro backend** (validates preset-voice arm of `VoiceRef`; CPU-friendly)
- [ ] **Kitten backend** (smallest model, ONNX, CPU-only)
- [ ] WebSocket bidirectional streaming endpoint (`WS /tts/stream`)
- [ ] PyPI publishing pipeline (release tags → built wheels → PyPI)
- [ ] Voice-mixing syntax (Kokoro-style `name(weight)+name(weight)`) where backend supports it
- [ ] Wyoming protocol adapter (Home Assistant integration; opt-in)

## v0.3.0 — quality + breadth

**Goal:** Add the heavier-but-higher-quality backends + long-form options.

- [ ] **F5-TTS backend** (Apache-2, diffusion-based, voice cloning)
- [ ] **XTTS-v2 backend** (Coqui, MPL-2, multilingual + voice cloning)
- [ ] **Dia backend** (first community wrapper; multi-speaker via [S1]/[S2] tags; requires GPU)
- [ ] **VibeVoice backend** (if licensing checks out — directly addresses long-form narrative quality)
- [ ] **Piper backend** (subprocess-call wrapper; GPL-3 safe; 30+ languages)
- [ ] Per-voice sampling-param overrides (temperature, top_k, repeat_penalty)
- [ ] OpenAI-API-compatible "api_key" header for SDK drop-in

## v0.4.0 — distributed + multi-tenant

**Goal:** Make voice-forge deployable beyond a single machine.

- [ ] S3-compatible voice registry backend (in addition to FS)
- [ ] SQLite voice registry for richer queries
- [ ] Auth: bearer tokens, per-tenant rate limiting
- [ ] Helm chart for Kubernetes deploy
- [ ] Distributed inference: voice-forge router + worker fleet

## Future / Maybe

- [ ] **MeloTTS backend** (multilingual, CPU-friendly, MIT)
- [ ] **Chatterbox-Turbo backend** (sub-200ms latency, MIT)
- [ ] **Fish Audio S2 Pro backend** (80+ languages, voice cloning)
- [ ] ElevenLabs proxy backend (cloud passthrough for fallback)
- [ ] OpenAI-TTS-proxy backend (use OpenAI's gpt-4o-mini-tts as a backend)
- [ ] Voice Lab: bulk pull from ElevenLabs (whole workspace)
- [ ] Voice Lab: voice DESIGN (generate new voices from text descriptions; ElevenLabs-style)
- [ ] Speaker diarization for multi-speaker reference audio splitting
- [ ] CLI UI for browsing voices (TUI à la lazygit)
- [ ] gRPC alternative to REST for low-latency local IPC
- [ ] Phoneme-level synthesis control (SSML-like markup)
- [ ] Word-level timestamps in response (for live-captioning use cases)

## Sibling repo

`infiquetra/voice-listen` — STT service sibling. Same pluggable architecture, different domain. Not in this repo's roadmap; tracked at home-lab QUEUED.md.

## How items move

- **New idea** → `docs/engineering-journal/QUEUED.md` first (Priority, Effort, Worth-it-when, Context)
- **Picked up** → tagged in this ROADMAP under a version
- **Shipped** → moved to `docs/engineering-journal/ARCHIVE.md` (SHIPPED + date + commit hash)
- **Rejected** → moved to ARCHIVE.md (REJECTED + reason)

If you have a backend or feature you want prioritized, open a GitHub Issue.
