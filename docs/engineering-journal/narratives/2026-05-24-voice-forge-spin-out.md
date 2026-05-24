# voice-forge — origin story narrative

**Date:** 2026-05-24
**Status:** Repo scaffolded (Phase C of home-lab plan). Phase D fills out v0.1.0 implementation.
**Companion narrative:** `infiquetra/home-lab/docs/engineering-journal/narratives/2026-05-24-voice-forge-spin-out.md` (the home-lab side of the same decision)
**Plan:** `~/.claude/plans/i-am-under-the-merry-finch.md` (in the home-lab user's plans dir)

## Why this repo exists

voice-forge spun out of a NeuTTS daemon prototype built inside `infiquetra/home-lab`. The prototype's job was to give the Asgard sister-agents (Saga, Freya, Beyla, Gersemi, etc.) a local TTS option that preserved their ElevenLabs Voice Lab voices.

Six daemon versions in, we'd discovered:

1. Each TTS model has its own sampling-knob fingerprint (NeuTTS needs `repeat_penalty=1.05` to stop stuttering; needed `n_ctx=8192` to not truncate; needed the Perth watermarker disabled for clean streaming)
2. The model-quality fix for long-narrative content isn't tuning — it's a different backend (F5-TTS, XTTS-v2, Kokoro, Dia, VibeVoice all candidates)
3. The right architecture has a clean abstraction between "the engine" and "the deployment"
4. Test loops that go through Discord wasted hours; text→WAV via direct daemon call is the right testing primitive

These four findings made the case for spinning the engine out of home-lab into its own repo. home-lab becomes a CONSUMER — its ansible role installs voice-forge from a git tag, configures the persona voices in voice-forge's voice registry, and runs the service as a launchd daemon on the Mac mini. voice-forge itself is engine-only: no Asgard-specific knowledge, no Mac-mini assumptions.

## Design principles locked in v0

1. **TTS quality must be testable WITHOUT going through Discord.** voice-forge ships a CLI + REST API specifically so quality iteration doesn't require the full chat-platform round-trip. The "text in, WAV out, audition, iterate" loop is the design center.

2. **Pluggable backend architecture from day one.** NeuTTS Air is the v0 backend, but the `TTSBackend` Protocol + `VoiceRef` union dataclass are engineered to handle the variance across the prior-art landscape (preset-voice models like Kokoro/Kitten, ref-audio-cloning models like XTTS/F5/Dia, mixed-mode models like NeuTTS itself). See [`docs/PRIOR_ART.md`](../PRIOR_ART.md).

3. **OpenAI-compatible REST surface.** Kokoro-FastAPI and OpenedAI-Speech both implement `POST /v1/audio/speech` — that's the ecosystem-friendly choice. Drop-in for the OpenAI Python SDK. WebSocket and Wyoming adapters are opt-in additions in v0.2+.

4. **Public Apache-2.** Forces clean abstractions. Lets others contribute backends. Matches the ML ecosystem default (NeuTTS, HuggingFace, FastAPI). Patent grant matters for an ML project building on speech-token / audio-codec patents.

5. **Engineering journal scaffolded from day one.** Same pattern as `infiquetra/home-lab`: LEARNINGS / DECISIONS / QUEUED / ARCHIVE / narratives. Externalize work memory; never silently delete history. See [`docs/engineering-journal/README.md`](../engineering-journal/README.md).

## What's NOT in voice-forge (intentionally)

- **STT** — speech-to-text is a sibling concern. Will live in `infiquetra/voice-listen` (planned). Same singleton-daemon shape, different domain.
- **Asgard-specific configs** — persona names, sister voices, hermes-agent integration patches all stay in home-lab. voice-forge knows about "voices" and "backends" only, not about Saga or Freya.
- **The persona ref WAV files** — they live in home-lab because they're deployment-specific to the Asgard cast. voice-forge ships with NeuTTS's bundled `jo.wav` as a public-domain example ref for tests + quick-start.
- **Hermes-agent integration code** — the home-lab ansible role manages a thin HTTP-client shim that translates hermes-agent's subprocess interface into voice-forge REST calls. voice-forge doesn't know hermes-agent exists.

## What inherited from the home-lab investigation

See [`docs/engineering-journal/LEARNINGS.md`](../LEARNINGS.md) for the cross-reference. Eight findings from 2026-05-24 in home-lab inform voice-forge's defaults:

- Q8 GGUF default for NeuTTS (BF16 is 4× slower)
- Batch mode default (streaming has 15-21% content loss — opt-in only)
- Perth watermarker disabled (per-chunk artifact)
- ffmpeg MP3 at 192k explicit (default is 32k!)
- Whisper STT forces `language="en"` (avoids accent-misdetect)
- NeuTTS-Air degrades on >30s narrative (training-distribution limit — voice-forge's pluggable architecture is the workaround)

## Phase C scaffolding (this commit + previous)

Two commits land the v0 scaffolding:

1. `Initial scaffolding: docs, structure, license, CI` — README, LICENSE (Apache-2), pyproject.toml (uv-based), CONTRIBUTING, docs/ (ARCHITECTURE, API_SPEC, PRIOR_ART, ROADMAP, VOICE_LAB), src/voice_forge/ skeleton (backends/, voice_lab/, registry/, server, cli with TODO Phase D stubs), tests/ skeleton, .github/workflows/ci.yml, docker/ scaffold.

2. `docs(engineering-journal): scaffold LEARNINGS / DECISIONS / QUEUED / ARCHIVE + spin-out narrative` (this commit) — fills in the engineering-journal pattern from day one. LEARNINGS cross-references home-lab's findings. DECISIONS lists the five locked-in choices (license, model default, batch default, pluggable backends, REST surface). QUEUED has ~20 P1/P2/P3 items covering future backends + features. ARCHIVE is empty (no shipped items yet).

## What's next

Phase D (estimated 4-6 hours per the home-lab plan): port the working v6 NeuTTS daemon code into `src/voice_forge/backends/neutts.py`, fill out `server.py` endpoints + `cli.py` commands + Voice Lab utilities + registry implementation. Add real unit + integration tests. Tag `v0.1.0` when complete.

Phase E (later): home-lab's ansible role gets rewritten to install voice-forge from the `v0.1.0` git tag and configure the 9 Asgard persona voices in the registry.

Phase G (later): dual-port cutover from the ad-hoc daemon to voice-forge in the home-lab fleet, with shim symlink as the cutover switch and rollback path.

## Cross-references

- Home-lab side: `infiquetra/home-lab/docs/engineering-journal/narratives/2026-05-24-voice-forge-spin-out.md` (the prototype-to-spinout story)
- Home-lab plan: `~/.claude/plans/i-am-under-the-merry-finch.md` (full Phase A-H plan)
- Prior art: [`docs/PRIOR_ART.md`](../../PRIOR_ART.md) (comparative study of 12 prior projects)
- Architecture: [`docs/ARCHITECTURE.md`](../../ARCHITECTURE.md)
- Roadmap: [`docs/ROADMAP.md`](../../ROADMAP.md)
