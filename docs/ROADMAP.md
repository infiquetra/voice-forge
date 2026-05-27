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

## v0.2.0 — pluggable proof (SHIPPED 2026-05-25)

**Goal:** Validate the pluggable-backend abstraction by adding a second backend without touching the dispatch code, plus ship PyPI distribution and an audio audition harness for the Asgard fleet.

**Core v0.2 plan (all shipped):**

- [x] Backend dispatch refactor — drop the hard-coded `if name == "neutts"` branches; registry-driven via `load_backend_module()` (commit `ed0a7ba`)
- [x] **Kokoro backend** (hexgrad/kokoro, Apache-2, PyTorch+MPS — validates preset-voice arm of `VoiceRef`) (commit `679e23b`)
- [x] Voice-mixing syntax (Kokoro-style `name(weight)+name(weight)`) — parser shipped (commit `679e23b`); full tensor blending stays queued
- [x] NeuTTS backend body test coverage via `sys.modules` injection (commit `ed0a7ba`)
- [x] PyPI publishing pipeline (OIDC trusted publishing; dist name `voice-forge-tts`) (commit `4eb02c4`)
- [x] Cleanup tail: version harmonization, dist rename, /tmp upload leak fix, Whisper threadpool wrap, `_porting/` relocation, journal hygiene (commit `cd00cbd`)
- [x] Asgard audition harness (`scripts/sync_fleet_from_home_lab.py` + `scripts/asgard_audition.py`) (commit `4eb02c4`)

**Pulled forward into v0.2 (originally v0.3):**

- [x] **F5-TTS backend** (commit `60db36a`) — became the **default backend** (DECISIONS 2026-05-25)
- [x] **XTTS-v2 backend** (commit `d7610f5`) — license-gated via `COQUI_TOS_AGREED=1`
- [x] **Dia-1.6B backend** (commit `2a0a846`) — ships with documented caveats

**Bonus work that landed in v0.2:**

- [x] Per-voice sampling-param overrides (`nfe_step`, `cfg_strength`, `temperature`, `top_p`, `top_k`, `repeat_penalty`, etc.) wired across F5, Dia, Kokoro, XTTS (commits `499564e`, `a2e045e`)
- [x] **HTTP layer-1 chunked streaming** with sentence-boundary chunker (commit `5c144c8`) — 10× first-audio win on F5 long-form
- [x] **WebSocket layer-2 streaming** (`WS /v1/tts/stream`) for LLM-driven pipelines (commit `694b0fe`)
- [x] **Live in-browser demo** at `GET /demo` with Web Audio API playback (commit `2c2ea10`)
- [x] F5 streaming preset (`nfe_step=16`) verified audibly equivalent to 32-step on 11-sentence stress test (commit `eab204c`, LEARNINGS 2026-05-25)
- [x] F5 default backend lock-in across CLI / REST / registry defaults (commit `eab204c`)
- [x] torch 2.8 / torchaudio 2.8 / torchcodec 0.7 pin in the `[f5]` extra to work around the torch 2.9 + torchcodec 0.13 ABI gap (LEARNINGS 2026-05-25)

**Deferred to later versions:**
- Kitten backend (ONNX, CPU-only) → v0.3+
- Wyoming protocol adapter (Home Assistant integration) → v0.3+
- Proper `speed` field plumbing through `TTSBackend` Protocol → v0.3
- Voice-mixing tensor blending → v0.3+

## v0.3.0 — production hardening (mostly SHIPPED 2026-05-25)

**Goal:** Make voice-forge safe to expose beyond `127.0.0.1` and easy for outside users to deploy.

- [x] **Quickstart tutorial** — `docs/QUICKSTART.md` (commit `74a4a9b`)
- [x] **Pre-commit hooks + bandit** — ruff/black/mypy/bandit in CI + locally (commit `98bb395`)
- [x] **Observability — Prometheus `/metrics`** — six core metrics (synth_seconds histogram, synth_requests_total, backend_loaded, voices_registered, active_ws_connections, ws_sentences_total) (commit `22432bd`)
- [x] **Subprocess-isolated backend pattern** — HTTP-shim IPC; per-backend venvs at `~/.voice-forge/backends/<name>/.venv/` (commit pending)
- [x] **Piper backend** — GPL-3 isolated via subprocess pattern (commit pending)
- [x] **Chatterbox-Turbo backend** — hostile-pin isolated via subprocess pattern (commit pending)
- [x] **MeloTTS backend** — MIT multilingual presets, subprocess-isolated (commit pending)
- [x] **Demo UX rebuild** — persona + model split dropdowns + conditional per-backend knob panel (commit `9a0c544`)
- [x] **`voice-forge backend install <name>` CLI** — provisions per-backend venvs (commit pending)
- [ ] **Bearer-token auth** — DEFERRED 2026-05-25 pending a token-issuance story; see [QUEUED](engineering-journal/QUEUED.md) § "OpenAI-API-compatible authentication"
- [x] **WS layer-2 pipelining** — asyncio producer/consumer split so receive task pulls text while consumer is mid-synth (commit pending; see LEARNINGS 2026-05-25 § "WS layer-2 pipelining")
- [ ] **F5 accent retention tuning** — `cfg_strength` per-voice experimentation (task #20)
- [ ] **Wyoming protocol adapter** (Home Assistant integration)
- [ ] **Hermes-agent integration** to actually consume streaming end-to-end — task #23, work is in `infiquetra/home-lab`, not voice-forge

## v0.4.0 — distributed + multi-tenant

**Goal:** Make voice-forge deployable beyond a single machine.

- [ ] S3-compatible voice registry backend (in addition to FS)
- [ ] SQLite voice registry for richer queries
- [ ] Per-tenant rate limiting + voice namespacing
- [ ] Helm chart for Kubernetes deploy
- [ ] Distributed inference: voice-forge router + worker fleet

## Future / Maybe

- [ ] **MeloTTS backend** (multilingual, CPU-friendly, MIT)
- [ ] **Chatterbox-Turbo backend** (sub-200ms latency, MIT) — task #16, deferred behind subprocess-isolated pattern (#15)
- [ ] **Fish Audio S2 Pro backend** (80+ languages, voice cloning) — task #17, deferred — research-license + hostile deps
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
