# Decisions — voice-forge

> **ADR-style records of architectural / prompt-design / process choices.** When you commit a chosen path over alternatives — pick A over B, flip a flag, change a threshold — capture rationale + tradeoff + revisit-when condition + commit hash.
>
> The point is to make **revisit conditions explicit** so a future contributor reading "why did we pick X?" gets the answer cold, including when it would be right to reconsider.
>
> **Append new entries to the top.** Format:
>
> ```markdown
> ## YYYY-MM-DD
>
> ### Short title (commit hash)
>
> **Decision.** What we picked.
> **Rejected alternatives.** What we considered and didn't pick.
> **Rationale.** Why this won.
> **Revisit when.** Condition that would change the calculus.
> ```
>
> When new evidence invalidates a decision, **update inline AND move the pre-correction version to `ARCHIVE.md` as SUPERSEDED**.

---

## 2026-06-14

### voice-forge is a public-OSS local voice-forging studio — not personal infra, not a one-model server (STRATEGY.md)

**Decision.** Two linked commitments, recorded while writing the root `STRATEGY.md`:

1. **Direction = public open-source product**, not personal infrastructure. voice-forge is built for the world's self-hosted voice-agent builders; the Asgard sister-voices fleet is the dogfood / reference deployment, not the customer. Onboarding, install reliability across hosts, and outside-contribution ergonomics become first-class concerns.

2. **Identity = a voice-forging studio backed by a serving engine**, not a serving engine alone. The product owns the whole **design → bind → serve** lifecycle: forge a voice (design-from-description on local models, or clone-from-reference), audition + tune it across model families, bind it to an agent persona, and serve it over the OpenAI-compatible API. The human-facing Forge interface (`/lab → /forge`) is a defining surface, co-equal with the API — framed as "a better ElevenLabs Voice Design, local and agent-aware."

**Rejected alternatives.**

- **Personal infra, public-ready (forcing-function only).** The de-facto status today: one consumer (home-lab Hermes agent), personas excluded from the wheel, `/lab` as a private workbench. Rejected as the *recorded* direction — the user chose to point it outward. If outside adoption never materializes, this is the fallback to revisit.
- **Serving engine only** — the original framing ("pluggable TTS service for agent voices"). Rejected as too narrow: it cedes the most distinctive half (local voice *design*) to ElevenLabs and reduces voice-forge to one commoditized serving server among many (Kokoro-FastAPI, xtts-streaming-server). The forge is the differentiator.
- **Cloud voice-design tool (ElevenLabs-style SaaS).** Rejected — self-hosted, own-your-voices, own-your-hardware is the whole point; a hosted offering is explicitly out (STRATEGY § Not working on).

**Rationale.**

- The name is *voice-**forge***; forging voices — not just serving them — is the direction the codebase has been drifting toward (the Voice Design pipeline, the queued `/forge` web-UI redesign P1, the Qwen3-TTS-VoiceDesign local-design provider #60).
- The serving side is increasingly commoditized; the local design+bind+serve lifecycle on your own models is not offered by anything in the prior-art survey.
- Per-voice backend selection — the core technical finding — only delivers value if forging a voice and binding it to its best backend is a first-class workflow, which makes the studio strategically load-bearing rather than a side feature.

**Revisit when.**

- 12+ months pass with no outside adoption signal (external issues/PRs ~zero, no third-party deployments we hear about) → revisit the public-product direction; consider reverting to "personal infra, public-ready."
- A local voice-design model good enough to displace ElevenLabs Voice Design fails to materialize (Qwen3-TTS-VoiceDesign #60 and successors underperform on phonetic-imperative prompts) → revisit how central the *design* half can be versus clone-only.
- Maintainer capacity can't sustain a human-facing UI surface to product quality → re-scope the Forge from "defining surface" back to "internal workbench."

**Refs.** Root `STRATEGY.md` (2026-06-14). [QUEUED P1 "The Forge: full web-UI redesign"](QUEUED.md), [#60 "Qwen3-TTS-VoiceDesign provider"](QUEUED.md), [#59 "generic mlx_audio backend"](QUEUED.md). [PRIOR_ART.md](../PRIOR_ART.md) — no surveyed tool offers local design+bind+serve.

---

## 2026-05-26

### F5 nfe_step default flipped from 32 → 16 (commit pending)

**Decision.** F5's `DEFAULT_NFE_STEP` is now **16**, not 32. Voices without an explicit `metadata.sampling.nfe_step` override get 16-step diffusion synthesis. The 32-step path is still reachable via `voice tune <id> --sampling nfe_step=32` for an explicit quality preset.

The `*-fast` voices that were registered as nfe_step=16 variants (`saga-comms-f5-fast`, `heid-research-f5-fast`, `hnoss-books-f5-fast`) are deleted from the audition registry — redundant now that 16 is the parent default.

**Rejected alternatives.**

- **Keep 32 as default; expose 16 only as opt-in.** Was the original recommendation in [DECISIONS 2026-05-25 § F5-TTS is the default backend](DECISIONS.md). The hesitation was unproven quality cost. Quality has now been validated on the 11-sentence Saga narrative as audibly indistinguishable. The user has explicitly endorsed flipping the default. Sticking with 32 means every default-setup voice eats 2× the synth wall-time for no audible payoff.
- **Make the default conditional on streaming-vs-batch mode** (e.g., `nfe_step=16` for `stream=true`, `32` for `stream=false`). Splits the abstraction; introduces a quality-vs-mode coupling that's harder to reason about. Single value across both paths is simpler + the right call given the equivalence finding.

**Rationale.**

- 11-sentence stress test in the live WS demo (2026-05-25): listener could not distinguish the two settings.
- Wall-time savings on F5 are substantial. p3 narrative (~995 chars / 11 sentences): batch first-audio drops from ~62 s (nfe=32) to ~30 s (nfe=16); WS first-audio drops from ~6 s to ~3 s.
- "Pay the latency tax by default, opt into the quality cost" is the wrong direction for streaming-default voice-forge. Better: default to the streaming-friendly value, document the quality-preset path for callers who specifically care.

**Revisit when.**

- F5 upstream ships a distilled / consistency-trained variant where the quality/step curve flattens enough that the default could go lower (8 or 12). Re-run the equivalence test against the new variant.
- A listener with golden ears reports an audible degradation on real content we haven't tested. Capture the test case + walk the value back up to 24 or 32 for that voice via the per-voice override.

**Refs.** Commit pending (Phase X of `.claude/plans/2026-05-25-voice-lab-tuning-workstation.md`). Supersedes the "16 is the streaming preset" framing in [DECISIONS 2026-05-25 § F5-TTS is the default backend](DECISIONS.md). [LEARNINGS 2026-05-25 § F5 nfe_step=16](LEARNINGS.md) is the empirical foundation.

---

## 2026-05-25

### F5-TTS is the default backend (commit pending — see git log for hash)

**Decision.** F5-TTS becomes the default backend across voice-forge:

- `nfe_step=32` (F5 default) is the **quality preset** — used for batch synth via `POST /v1/audio/speech` and for voices the user explicitly wants to maximize timbre fidelity on.
- `nfe_step=16` is the **streaming preset** — used for voices that drive layer-1 (HTTP chunked) and layer-2 (WS) streaming surfaces. Verified on a 995-char / 11-sentence Saga narrative as audibly indistinguishable from 32-step on the Mac Studio dev host ([LEARNINGS § F5 nfe_step=16](LEARNINGS.md)).

Concrete code defaults flipped from `"neutts"` to `"f5"` in `server.py` (`FromElevenLabsRequest`, `POST /voices/{id}` form default), `cli.py` (`voice add`, `voice from-elevenlabs`), and `registry/__init__.py` (legacy-metadata fallback).

**Rejected alternatives.**

- **Keep NeuTTS Air as the default.** Was the v0.1 baseline because it shipped first and was already running in production on the Asgard daemon. Loses on three measurable axes: long-form coherence (30 s cliff, documented), short-utterance reliability (`heid-research × "Can you hear me?"` collapsed to 0.16 s of audio under autoregressive sampling), and resource cost (~5.6 GB resident vs F5's ~1.5 GB).
- **Kokoro as the default.** Light (~1.4 GB), fast (RTF 0.07 CPU), Apache-2 — but **no cloning**. Defaults need to serve the agent-voice use case where cloning is the point; Kokoro is the right pick *for non-cloning voices*, not the right default.
- **XTTS-v2.** Multilingual + clean — but cloning is pitch+gender-adapter only, no accent preservation ([LEARNINGS § cloning-fidelity spectrum](LEARNINGS.md)). CPML weights are also non-commercial; user has to accept that explicitly via `COQUI_TOS_AGREED=1`. Wrong default for a permissively-licensed library.
- **Dia-1.6B.** Apache-2 + multi-speaker — but wrong gender on Heid in the audition, and default `max_new_tokens=3072` truncates long-form to ~18-21 s.
- **Multiple defaults (per use case).** Considered: "default to NeuTTS for short cloning, F5 for long-form." Rejected as user-hostile — defaults should be a single answer.

**Rationale.**

- **F5 is the only backend that's identity-preserving AND coherent past 30 s.** That's the agent-voice use case voice-forge exists to serve.
- **Cost of F5 as default is low.** ~1.5 GB resident (under one third of NeuTTS) and ~37 s cold-load. Mac mini M4 Pro production host (24 GB) accommodates F5 + Kokoro + NeuTTS all loaded simultaneously.
- **The 32/16 step split is the right knob.** F5's diffusion-step count is a clean compute/quality lever; dropping to 16 halves synth time with no audible quality loss on the 11-sentence stress test. This means the same backend serves *both* high-quality batch and low-latency streaming use cases without a second model to maintain.
- **Streaming-first matters for the hermes-agent integration.** The downstream consumer is an LLM-driven agent that needs first-audio in the 2-5 second range, not in the 60+ second range. F5 with nfe_step=16 is the only backend in the matrix that hits this AND preserves identity.

**Revisit when.**

- A backend ships that improves on F5 in measurable ways: lower latency at equivalent identity preservation, better long-form coherence, or a license that's cleaner than F5's MIT-wrapper-over-Apache-2-weights split (already pretty clean).
- F5 upstream drops a step-distilled or consistency-distilled variant that lets us go to `nfe_step<16` without quality loss. Would let us close the gap with Kokoro on first-audio.
- A real production load test demonstrates the F5 ~1.5 GB resident set is unmanageable on the deploy host. Current evidence says it's fine on 24 GB.

**Refs.** [LEARNINGS 2026-05-25 § F5 nfe_step=16](LEARNINGS.md), [BACKENDS.md § At a glance](../BACKENDS.md), QUEUED → #20 (F5 accent retention tuning), #21 (WS pipelining), #16 (Chatterbox deferred).

---

## 2026-05-24

### Apache 2.0 license (initial commit)

**Decision.** Public Apache-2.0 for voice-forge code. Same license as NeuTTS Air (the v0 backend dependency).

**Rejected alternatives.**
- MIT: lacks patent grant; for an ML project building on speech-token / audio-codec patents, contributor patent grant is meaningful protection.
- BSD 3-Clause: same gap as MIT.
- MPL-2.0 (Coqui's choice): file-level copyleft adds friction for closed-source users; ecosystem standard is Apache for Python ML.
- GPL-3.0 (Piper's choice): strong copyleft kills commercial adoption.
- AGPL-3.0 (OpenedAI-Speech's choice): SaaS clause; many companies blanket-ban; OpenedAI is also now archived.
- Custom license: adoption tanks if people have to read it.

**Rationale.** Apache 2.0 is the de facto standard for Python ML projects (NeuTTS, HuggingFace transformers, TensorFlow, FastAPI ecosystem). Aligning license tier with deps removes user friction. Patent grant matters here. Permissive enough to support enterprise adoption. Future dual-licensing remains an option if we ever want a commercial tier.

**Revisit when.** If voice-forge ever wants to force commercial users into a "buy a license OR open-source" choice (Redis/MongoDB-style business model). Default position: no.

**Refs.** [docs/PRIOR_ART.md § License compatibility quick reference](../PRIOR_ART.md). Home-lab DECISIONS 2026-05-24 "Spin TTS out of home-lab into infiquetra/voice-forge (public, Apache-2)".

### Q8 GGUF default for NeuTTS backend; BF16 deferred

**Decision.** When the NeuTTS backend ships (Phase D), the default model is `neuphonic/neutts-air-q8-gguf`. BF16 is opt-in via config.

**Rejected alternatives.**
- BF16 full precision: half the click rate but 4× slower (RTF 1.76 vs 0.30 on M4 Pro CPU). Same long-narrative quality limit. Slow enough to be unusable for conversational use.
- Q4: fastest (RTF 0.27) but voice quality cost is audible.

**Rationale.** Q8 balances voice quality and synth speed. BF16's click-reduction is real but irrelevant given (a) the 4× speed cost and (b) the long-narrative degradation affects BF16 equally (model-capacity limit, not precision limit).

**Revisit when.** A dedicated TTS host with GPU (Mac Studio, Linux box with NVIDIA) makes BF16 RTF acceptable, OR if a backend swap (F5/XTTS) renders this question moot.

**Refs.** Home-lab LEARNINGS 2026-05-24 "NeuTTS-Air degrades into incoherent phonemes". Same DECISIONS in home-lab DECISIONS.md.

### Batch mode default in voice-forge client; streaming opt-in

**Decision.** voice-forge's HTTP client (and CLI) default to **batch synthesis**. Streaming is opt-in via `stream: true` request field or env var.

**Rejected alternatives.**
- Streaming default (latency win): confirmed 15-21% content loss on long inputs in home-lab measurements. Too much risk for default behavior.
- Length-based auto-switch: cliff is fuzzy and would confuse debugging.

**Rationale.** Predictable batch that produces all content reliably > sometimes-faster streaming that drops content. Streaming stays as opt-in for experiments. v0.2 may flip this back once the content-loss is investigated.

**Revisit when.** [QUEUED: "NeuTTS streaming content-loss investigation"](QUEUED.md) is resolved and the gap is closed.

**Refs.** Home-lab LEARNINGS 2026-05-24 "NeuTTS streaming drops 15-21%". [PRIOR_ART.md](../PRIOR_ART.md).

### Pluggable backend architecture: Protocol + VoiceRef union

**Decision.** Backend abstraction is a `TTSBackend` Protocol (not ABC) with a `VoiceRef` union dataclass (fields: `ref_audio_path | preset_id | encoded_codes | ref_text | metadata`). Each backend reads only what it needs.

**Rejected alternatives.**
- Abstract Base Class (ABC) — works but forces inheritance; less plugin-friendly for third-party backends in separate packages.
- Tagged-union types via `Literal` discriminators — more boilerplate without measurable benefit.
- Separate Protocol per backend family — adds complexity; current design handles NeuTTS / F5 / XTTS / Kokoro / Kitten / Dia uniformly.

**Rationale.** Protocol-based design lets backends live in third-party packages without depending on voice-forge directly. `VoiceRef` union handles real variance seen in the wild (NeuTTS uses codes+ref_text; XTTS/F5 use ref_audio_path; Kokoro/Kitten use preset_id; Dia uses ref_audio_path as audio-prompt). Validated against Phase B prior-art research.

**Revisit when.** If a backend's API genuinely doesn't fit the Protocol (e.g., a streaming-only model that can't do batch), expand the Protocol with optional methods. The Protocol shape can grow without breaking existing backends.

**Refs.** [docs/ARCHITECTURE.md § Core abstractions](../ARCHITECTURE.md). [docs/PRIOR_ART.md § What we deliberately did NOT borrow](../PRIOR_ART.md).

### REST + chunked HTTP transfer (WebSocket / Wyoming deferred to v0.2)

**Decision.** v0 surface is REST with `POST /v1/audio/speech` (OpenAI-compatible). Streaming via chunked HTTP transfer (`Transfer-Encoding: chunked`) when `stream: true`. WebSocket bidirectional streaming and Wyoming protocol adapter are tracked for v0.2.

**Rejected alternatives.**
- gRPC: lower latency but adds toolchain complexity; not standard for this use case.
- WebSocket-first: bidirectional adds value for chat use cases but doubles the API surface in v0.
- Wyoming-first: locks us into the Home Assistant ecosystem rather than open ecosystem.
- Unix-socket-only: ties us to single-host deploys; HTTP unlocks remote.

**Rationale.** HTTP/REST is the lingua franca for service integration. Sub-2ms HTTP overhead is irrelevant when synthesis takes seconds. OpenAI-compatible endpoint shape lets clients use the OpenAI SDK out-of-the-box (matches what Kokoro-FastAPI and OpenedAI-Speech demonstrated works in practice).

**Revisit when.** v0.2 — add WebSocket for chat use cases + Wyoming for Home Assistant integration. Both are additive (don't break REST).

**Refs.** [docs/ARCHITECTURE.md](../ARCHITECTURE.md). [docs/PRIOR_ART.md § Decisions for voice-forge informed by this survey](../PRIOR_ART.md).
