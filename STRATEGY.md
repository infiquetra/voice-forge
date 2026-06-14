---
name: voice-forge
last_updated: 2026-06-14
---

# voice-forge Strategy

## Target problem

Builders giving their AI agents a voice hit two gaps, and no tool closes both. **Designing** the voice: the best way to conjure one from a description — ElevenLabs Voice Design — is cloud-only, paid, proprietary, and stops at "here's a voice," with your voices living on someone else's servers. **Serving** it: no single open TTS model preserves a cloned voice's identity, accent, and long-form coherence at conversational latency — the model families trade off, and existing self-hosted tools each wrap exactly one. So there's no local, end-to-end way to forge a distinct agent voice and serve it well.

## Our approach

voice-forge is a local **voice-forging studio** backed by a swappable TTS engine, owning the whole **design → bind → serve** lifecycle: forge a voice — design it from a text description on a local model, or clone it from a reference clip — audition it across model families, tune it, bind it to an agent persona in a persistent registry, then serve it over an OpenAI-compatible API. We bet on owning that full lifecycle on local models plus a clean backend Protocol, rather than being *either* a cloud design tool (ElevenLabs) *or* a one-model serving server (Kokoro-FastAPI) — so the same tool conjures the voice and serves it, per-voice backend selection is first-class, and a new model is an additive plugin.

## Who it's for

**Primary:** Voice-agent builders running self-hosted infra — they hire voice-forge to *forge* the voices their agents use (design-from-description or clone-from-clip), audition and tune them locally, bind each to an agent persona, and serve them — without sending anything to a cloud service like ElevenLabs. Their job: own the voices my agents speak with, end to end, on infrastructure I control.

**Secondary (agent-as-customer):** The conversational agent at runtime — it calls `POST /v1/audio/speech` (or the WebSocket) to speak its bound persona voice with first audio in seconds, not after the full reply is composed. Its job: turn this text into *my* voice, streaming, now.

## Key metrics

- **Fleet fidelity coverage** - fraction of registered voices whose bound backend passes its identity/accent audition. The direct read on forge output and the per-voice-selection bet; regresses if a default change flattens accents. Measured in the audition scorecard (`voice_scorecard.json`).
- **Local-design share** - fraction of voices forged through voice-forge's own local design/clone path versus those still requiring an ElevenLabs round-trip. Reads whether "a *local* ElevenLabs alternative" is real yet; sits near zero until the local design provider lands and stays low if it underperforms. Measured from voice registry provenance.
- **First-audio latency (p50/p95)** - seconds to the first audio chunk on the streaming surface, per backend. The conversational-latency leg of the problem; regresses on a slow backend or default. Measured via Prometheus `voice_forge_synth_seconds` + WS metrics.
- **Degenerate-output rate** - fraction of synth calls returning silence-collapse or truncation across the fleet. A real, measured failure mode (higgs-mlx ~50% on edge voices); must trend toward zero. Measured by the server-side silence/truncation guard metric.
- **External engagement** - non-maintainer issues/PRs opened per month and distinct outside deployments we hear about. The lagging read on the public-product bet; goes to zero if nobody adopts. Measured on GitHub + PyPI.

## Tracks

### The Forge — voice design, audition & persona binding

The human-facing studio and the workflow under it: design-from-description via local providers (and ElevenLabs while it's the best), clone-from-reference via Voice Lab, audition and tune across backends, bind a voice to a persona, and the `/lab → /forge` web interface that makes it one loop.

_Why it serves the approach:_ this is the design half of design→bind→serve and the product's most distinctive surface — per-voice selection only pays off if forging a voice and binding it to its best backend is a fast, first-class loop rather than a multi-tool slog.

### Backend coverage & cloning fidelity

The catalog of model-family backends, a CI gate that every advertised backend installs and smoke-synths cleanly on the supported (OS, arch, Python) matrix, and the audition machinery that decides which voice binds to which.

_Why it serves the approach:_ breadth across diffusion and LLM-backbone families is what makes mixing-by-voice possible at all — and "advertised but broken" backends quietly break the promise.

### Streaming & latency

The real-time path: HTTP chunked layer-1, WebSocket layer-2 pipelining, diffusion-step tuning, and Apple-Silicon / MLX throughput.

_Why it serves the approach:_ it owns the conversational-latency leg — the difference between voice-forge being usable in a live agent turn versus only in batch.

### Service hardening & deployability

The auth/token story, multi-tenant registry backends (S3 / SQLite), install reliability across hosts, observability, and onboarding docs.

_Why it serves the approach:_ a public product needs one stable surface outside builders can deploy, secure, and trust — not just one that works on the maintainer's Mac.

## Not working on

- **STT / speech-to-text** - sibling concern, lives in `infiquetra/voice-listen`, not here.
- **Training or fine-tuning our own TTS models** - we integrate, select, and drive existing models (including their voice-design modes); we don't train one.
- **Bundling personas/voices** - ships with an empty registry; the Asgard fleet is the reference deployment and stays out of the wheel. Users forge their own.
- **A hosted / SaaS offering** - self-hosted on infra-you-control, own-your-voices, is the whole point.
- **Backends we can't permissively redistribute or that are deliberately withdrawn** - VibeVoice (pulled cloning weights) rejected; research-license models (Fish Audio) stay at subprocess arm's length.

## Marketing

**One-liner:** A local, self-hosted alternative to ElevenLabs Voice Design — forge agent voices from a description or a reference clip on your own models, bind them to personas, and serve them over an OpenAI-compatible API.

**Key message:** ElevenLabs designs voices but keeps them in the cloud and stops at the voice file; the self-hosted servers serve voices but each wraps one model and can't design anything. voice-forge is the local studio that does both — forge a voice across model families, bind it to an agent, serve it streaming on your own hardware. Apache-2, OpenAI-compatible, your voices never leave your infra.
