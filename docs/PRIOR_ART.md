# Prior Art — Self-Hosted TTS Services

> Comparative study of the active self-hosted TTS landscape as of 2026-05-24. Inputs that shaped voice-forge's architectural decisions. Maintain this doc as new backends are added.

## License compatibility quick reference

| Project | License | Compatible with voice-forge (Apache-2)? | Notes |
|---|---|---|---|
| Coqui-TTS | MPL-2.0 | ✓ weakly | File-level copyleft; safe to depend on, can't directly include source |
| **OpenedAI-Speech** | **AGPL-3.0** | ⚠ copyleft poison | Including code forces voice-forge to AGPL. AVOID direct code borrow; OK to study patterns. |
| xtts-streaming-server | MPL-2.0 | ✓ weakly | Same as Coqui |
| Kokoro-FastAPI | Apache 2.0 | ✓ clean | Direct borrow OK with attribution |
| Wyoming protocol | MIT | ✓ clean | Protocol spec; trivial to implement compatibly |
| Dia (nari-labs) | Apache 2.0 | ✓ clean | Model only — service wrapper is a greenfield |
| Kitten TTS | Apache 2.0 | ✓ clean | Direct borrow OK |
| NeuTTS Air | Apache 2.0 | ✓ clean | Our v0 backend; license verified 2026-05-24 |
| Piper | GPL-3.0 | ⚠ strong copyleft | OK to call as a subprocess; including code forces GPL |
| MeloTTS | MIT | ✓ clean | OK |
| Chatterbox | MIT | ✓ clean | OK |
| Fish Audio S2 Pro | Apache 2.0 | ✓ clean | OK |
| VibeVoice (Microsoft) | Research-stage | ⚠ unclear | Need to verify before depending |

## Project-by-project review

### Coqui-TTS (`coqui-ai/TTS`)

**Status:** Mature, production-grade, ~4,600 commits, MPL-2.0. Project officially discontinued late 2024 but actively forked (e.g., `idiap/coqui-ai-TTS`).

**Architecture in one sentence.** Modular DL toolkit with pluggable models (Tacotron2, Glow-TTS, VITS, XTTS) + vocoders (HiFiGAN, MelGAN) + speaker encoders, deployable via CLI, Python API, or Flask server.

**Backend abstraction.** Strong: `BaseTrainerModel` ABC (`TTS/model.py`) with `init_from_config()`, `inference()`, `load_checkpoint()` enforced. Models register via `.models.json`. **This is the cleanest backend pattern we'll see**.

**API surface.** Flask `/api/tts` (GET/POST) returns WAV. MaryTTS compatibility (`/locales`, `/voices`, `/process`). No native streaming — clients get complete WAVs. Thread-locked concurrency.

**What to borrow.** ABC-based backend interface (direct inspiration for `TTSBackend` Protocol). Model registry via JSON. Speaker encoder pattern for voice cloning.

**What to do differently.** Native streaming (chunked HTTP or WebSocket). Replace thread-lock with async. Per-request model selection (Coqui locks one model per server).

---

### OpenedAI-Speech (`matatonic/openedai-speech`) — ARCHIVED + AGPL-3.0

**Status:** **ARCHIVED Jan 2026.** Last release Aug 2024. Maintainer marked it "mostly obsolete". License **AGPL-3.0** — viral copyleft.

**Architecture in one sentence.** OpenAI-API-compatible (`/v1/audio/speech`) microservice wrapping Piper (CPU) + XTTS v2 (GPU), Docker-based, voice registry via YAML.

**Worth studying for.** OpenAI API compatibility pattern + voice metadata via `config/voice_to_speaker.yaml`. Dual-engine conditional routing.

**Why we'll AVOID direct code borrow.** AGPL-3.0 contamination risk for an Apache-2 project. Patterns/APIs are fine to mirror in clean-room fashion; source code is off-limits.

**What to borrow (clean-room).** OpenAI `/v1/audio/speech` endpoint shape. YAML voice registry pattern. Dockerfile variant strategy (CPU/CUDA-11/CUDA-12).

---

### xtts-streaming-server (`coqui-ai/xtts-streaming-server`)

**Status:** Demo-quality, MPL-2.0. ~50 commits, 15 open issues. Maintainer says "doesn't support concurrent requests".

**What to borrow.** FastAPI `StreamingResponse` + generator pattern for chunked WAV streaming. `/clone_speaker` endpoint (upload audio → speaker embedding). Multi-Dockerfile (CUDA 12.1, 11.8, CPU).

**What to do differently.** Persistent voice registry (XTTS-streaming-server is ephemeral). Production-grade async concurrency. Model abstraction beyond hard-coded XTTS.

---

### Kokoro-FastAPI (`remsky/Kokoro-FastAPI`) — currently most-aligned reference

**Status:** Active, Apache 2.0, 4.9k stars, v0.3.0. CPU + NVIDIA CUDA + AMD ROCm support via startup scripts.

**Architecture in one sentence.** Containerized FastAPI wrapper around Kokoro-82M with OpenAI-compatible REST + fine-grained voice-mixing.

**API.** REST-only. Primary: `/v1/audio/speech` (mirrors OpenAI). Additional: `/v1/audio/voices`, `/dev/captioned_speech` (word timestamps!), `/dev/phonemize`. Performance: 35-100× realtime on GPU, ~300ms first-token latency, ~3500ms on CPU.

**Voice management.** 40+ pre-computed voice packs. Voices combinable via syntax: `af_bella+af_sky` (mix), `af_bella(2)+af_sky(1)` (weighted). No runtime voice registration — voices are baked into the model.

**What to borrow.** OpenAI-compatible endpoint shape. Chunked HTTP streaming pattern. Voice-mixing syntax (`name(weight)+name(weight)`) is elegant; voice-forge should expose similar for backends that support it. Multi-hardware startup scripts.

**What to do differently.** Dynamic voice registration (Kokoro locks you in to bundled voices). Multi-backend support (Kokoro-FastAPI is one-model-only). Wyoming endpoint for HA users.

---

### Wyoming protocol (`rhasspy/wyoming`)

**Status:** Active, MIT, Open Home Foundation standard. v1.9.0.

**Wire format.** JSON header line + optional binary PCM payload. Bidirectional streaming via `synthesize-chunk` / `audio-chunk` events. TCP-based (default port 10200). Lower latency than HTTP chunking because no HTTP framing overhead.

**Why it matters.** Lingua franca for Home Assistant ecosystem. If voice-forge wants HA users, exposing a Wyoming endpoint alongside REST is the path.

**What to borrow.** `info`/describe pattern for capability advertisement. Voice metadata (`name`, `language`, `speaker`) is minimal and portable.

**What to do differently.** REST is primary surface (broader reach); Wyoming is an opt-in adapter, not the default. Wyoming uses raw PCM only — voice-forge should support MP3/Opus/WAV negotiation in its REST API.

---

### Dia 1.6B (`nari-labs/dia`)

**Status:** Active model, Apache 2.0, 19k stars. **NO service wrapper exists.** This is a meaningful gap.

**Architecture in one sentence.** 1.6B-parameter SoundStorm-based dialogue model generating multi-speaker audio from tagged transcripts (`[S1]`, `[S2]`) with voice cloning via audio prompts.

**API surface.** Python API only: `Dia.from_pretrained(...).generate(text)` returns 44.1kHz PCM array. Gradio demo for interactive use.

**Why interesting for voice-forge.** Dialogue-first design (multi-speaker via speaker tags). Voice cloning via audio prompt is more flexible than fixed packs. **Hardware: ~10GB VRAM mandatory.**

**Service gap.** Building voice-forge's Dia backend would be the **first community Dia TTS service wrapper**. Real opportunity. Need to solve: concurrency (model isn't thread-safe), streaming (Dia generates whole audio at once), voice caching, speaker-tag parsing.

**What to borrow.** Speaker-tag semantics (`[S1]`, `[S2]`) for multi-speaker dialogue. Audio-prompt voice cloning UX (more flexible than ref-WAV-only).

**Caveat for v0.** Dia requires GPU. Our M4 Pro can't run it via MPS easily. Dia stays as a "future GPU host" backend, not v0.

---

### Kitten TTS (`KittenML/KittenTTS`)

**Status:** Active developer preview (v0.8.1, Feb 2026), Apache 2.0, 14k stars.

**Architecture.** Lightweight CPU-optimized ONNX inference. Three variants: nano (15M, 25MB), micro (40M, 40MB), mini (80M, 80MB). 24kHz mono output. Int8 quantization available.

**API.** Python-native library only (no service wrapper in upstream):
```python
tts = KittenTTS(model_name)
tts.generate(text, voice_id, speed=1.0)
```
Eight built-in voice presets, indexed by voice_id (not ref WAV).

**Why interesting for voice-forge.** Preset-voice pattern (like Kokoro) — different shape from NeuTTS's `(codes, ref_text)` tuple. Validates the `VoiceRef` union dataclass approach for the backend Protocol. Hermes-agent has a `_generate_kittentts` integration already (look at `tools/tts_tool.py` for the pattern when porting).

**What to borrow.** ONNX-as-an-optional-backend pattern (lighter than GGUF on disk). Text preprocessing with span tracking (useful for ref-trimming by sentence boundary).

## Net-new candidates surfaced from BentoML + Inworld surveys

These weren't in the original Phase B candidate list but appear worth tracking for ROADMAP.md:

1. **VibeVoice (Microsoft)** — Long-form expressive TTS, up to 90 min coherent multi-speaker audio with consistent voice identity. Low-frame-rate tokenizers (7.5 Hz) + next-token diffusion. Streaming variant. **Directly addresses our NeuTTS-Air "long narrative gibberish" problem.** License is research-stage; verify before depending. Find: search `microsoft/VibeVoice` on GitHub.

2. **Fish Audio S2 Pro** — Decoder-only transformer, 80+ languages, voice cloning. Dual-AR (4B slow + 400M fast). SGLang-based streaming. Apache 2.0. Find: `fish-audio/fish-audio`.

3. **Chatterbox-Turbo (Resemble AI)** — 350M params, single-step diffusion, sub-200ms latency. Emotion exaggeration control. Voice cloning. MIT. Smallest + fastest of the new options.

4. **MeloTTS (MyShell.ai)** — Multilingual, 6+ languages with mixed-language utterance support. CPU-friendly (runs on CPU at full inference). MIT. Find: `myshell-ai/meloTTS`.

5. **Piper (rhasspy)** — Already familiar (we use it in home-lab as Piper baseline). 30+ languages, GPL-3.0, small models, existing Wyoming integration. Includable as a backend by SUBPROCESS-CALL (not code-include) so GPL doesn't contaminate voice-forge.

## Decisions for voice-forge informed by this survey

1. **Backend abstraction = Protocol/ABC** with `VoiceRef` union accepting `ref_audio_path | preset_id | encoded_codes` — handles NeuTTS (codes+ref_text), Kokoro (preset_id), XTTS/F5/Dia (ref_audio_path), Kitten (preset_id) cleanly. ✓ Already locked in the plan.

2. **REST first, Wyoming later** — Kokoro-FastAPI's OpenAI-compatible REST is the most-adopted shape. Wyoming is for HA users; opt-in adapter in v0.2.

3. **OpenAI-API-compatible /v1/audio/speech endpoint** — Kokoro + OpenedAI-Speech both validated this is the ecosystem-friendly choice. Implement clean-room (avoid AGPL contamination from OpenedAI's code).

4. **FastAPI + StreamingResponse for chunked transfer** — XTTS-streaming-server's pattern is the simplest working example. Async/await throughout to avoid Coqui's thread-lock pitfall.

5. **YAML voice registry on FS** — OpenedAI's `voice_to_speaker.yaml` pattern. Each voice has metadata: `backend`, `model`, `ref_audio_path | preset_id`, language, description.

6. **Voice-mixing syntax (deferred to v0.2+)** — Kokoro's `name(weight)+name(weight)` is elegant but only meaningful for preset-voice backends. v0 ships single-voice synth.

7. **Bidirectional streaming (deferred to v0.2+)** — Wyoming demonstrates the value. v0 uses one-way HTTP chunked transfer.

8. **No code borrow from AGPL projects (OpenedAI-Speech specifically)** — patterns and API shapes are inspiration; source code is off-limits. Clean-room only.

## Recommended backend roadmap (for voice-forge ROADMAP.md)

| Backend | v0 | v0.2 | v0.3+ | Rationale |
|---|---|---|---|---|
| NeuTTS Air | ✓ | | | Today's working code; instant-cloning ref-WAV pattern |
| Kokoro | | ✓ | | Lightweight CPU/GPU, preset voices, OpenAI-compatible already |
| Kitten | | ✓ | | CPU-only, smallest model, ONNX |
| XTTS-v2 | | | ✓ | Quality voice cloning, multilingual; needs GPU |
| F5-TTS | | | ✓ | Quality cloning; diffusion-based |
| Dia | | | ✓ | Dialogue-first; **community-first wrapper opportunity**; needs GPU |
| Piper | | | ✓ | Subprocess call (GPL-3 safe), 30+ languages, smallest disk footprint |
| MeloTTS | | | ✓ | Multilingual CPU-friendly, MIT |
| VibeVoice | | | ?? | Promising for long-form; license check needed |
| Fish Audio S2 Pro | | | ?? | Multilingual, Apache-2; check serving complexity |
| Chatterbox | | | ?? | Sub-200ms latency target; check VRAM needs |

## What we deliberately did NOT borrow from prior art

1. **OpenAI-Speech's single-process serialization** — copies a known anti-pattern (Coqui has same issue). voice-forge is async/concurrent from day one.

2. **Coqui's runtime model lock (one-model-per-server)** — limits multi-backend story. voice-forge supports per-voice backend selection via metadata.

3. **Kokoro's hard-coded voice packs** — forces every new voice through repackaging. voice-forge supports runtime voice registration (upload WAV → register → use).

4. **Wyoming's PCM-only audio format** — limits codec choice. voice-forge negotiates MP3 / Opus / WAV / PCM via request format.

5. **xtts-streaming-server's ephemeral voice embeddings** — every clone is lost on restart. voice-forge persists voices in FS registry with metadata.

## Companion reading

- Plan: `~/.claude/plans/i-am-under-the-merry-finch.md` (Phase B drove this doc)
- Home-lab narrative: `infiquetra/home-lab/docs/engineering-journal/narratives/2026-05-24-voice-forge-spin-out.md`
- Hermes-agent's existing TTS provider patterns: `~/.hermes/hermes-agent/tools/tts_tool.py` (NeuTTS + KittenTTS + Piper + Edge + OpenAI + xAI + Mistral + ElevenLabs adapters live here)
