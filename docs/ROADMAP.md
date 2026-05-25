# Roadmap

> Where voice-forge is heading. See `engineering-journal/QUEUED.md` for items in active consideration.

## v0.1.0 — NeuTTS-only with pluggable backend architecture (SHIPPED 2026-05-24)

**Goal:** Ship the engine + one working backend, with the abstractions in place to add others.

**Shipped (commit `1e9c583`):**
- [x] Repo scaffolded (Phase C of [home-lab plan](https://github.com/namredips/home-lab/blob/main/.claude/plans/))
- [x] `TTSBackend` Protocol + `VoiceRef` union dataclass
- [x] NeuTTS backend (port of working v6 daemon from home-lab)
- [x] FastAPI server: `POST /v1/audio/speech`, `GET /v1/audio/voices`, `GET /health`, `POST /voices/{id}`, `POST /voices/from-elevenlabs`
- [x] CLI: `voice-forge serve`, `voice-forge synth`, `voice-forge voices`, `voice-forge voice add`, `voice-forge voice from-elevenlabs`
- [x] Voice Lab puller (ElevenLabs preview → ref WAV)
- [x] Ref trimmer (Whisper-based sentence-boundary cut)
- [x] Tests: unit + integration
- [x] Docker image (single-stage build for CPU)
- [x] CI: lint, format, type-check, tests on push

## v0.2.0 — pluggable proof (in progress)

**Goal:** Validate the pluggable-backend abstraction by adding a second backend without touching the dispatch code, plus ship PyPI distribution and an audio audition harness for the Asgard fleet. See [`.claude/plans/lets-take-a-look-optimized-koala.md`](../.claude/plans/lets-take-a-look-optimized-koala.md) for the locked plan.

- [ ] Backend dispatch refactor — drop the hard-coded `if name == "neutts"` branches; registry-driven via `load_backend_module()`
- [ ] **Kokoro backend** (hexgrad/kokoro, Apache-2, PyTorch+MPS — validates preset-voice arm of `VoiceRef`)
- [ ] Voice-mixing syntax (Kokoro-style `name(weight)+name(weight)`) — parser ships; full tensor blending may slip to v0.2.x
- [ ] NeuTTS backend body test coverage via `sys.modules` injection
- [ ] PyPI publishing pipeline (OIDC trusted publishing; dist name `voice-forge-tts`)
- [ ] Cleanup tail: version harmonization, dist rename, /tmp upload leak fix, Whisper threadpool wrap, `_porting/` relocation, journal hygiene
- [ ] Asgard audition harness (`scripts/sync_fleet_from_home_lab.py` + `scripts/asgard_audition.py` producing 27 audible WAVs + HTML index)

**Deferred to v0.2.x:**
- Kitten backend (ONNX, CPU-only)
- WebSocket bidirectional streaming
- Wyoming protocol adapter (Home Assistant integration)
- Proper `speed` field plumbing through TTSBackend Protocol

## v0.3.0 — quality + breadth

**Goal:** Add the heavier-but-higher-quality backends + long-form options.

- [x] **F5-TTS backend** (MIT wrapper / Apache-2 model, diffusion-based, voice cloning — pulled forward into v0.2 to test the pluggable abstraction with a third paradigm; no 30s cliff)
- [x] **XTTS-v2 backend** (MPL-2 lib / CPML weights, multilingual + voice cloning — pulled forward into v0.2; identity-cloning verdict: pitch/gender adapter only, not accent-preserving)
- [ ] **Dia backend** (first community wrapper; multi-speaker via [S1]/[S2] tags; needs Apple Silicon MPS validation)
- [ ] **VibeVoice backend** (if licensing checks out — directly addresses long-form narrative quality)
- [ ] **Piper backend** (subprocess-call wrapper; GPL-3 safe; 30+ languages)
- [ ] Per-voice sampling-param overrides (speed, nfe_step, cfg_strength, temperature, top_k, repeat_penalty) — see [QUEUED P2](engineering-journal/QUEUED.md)
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
