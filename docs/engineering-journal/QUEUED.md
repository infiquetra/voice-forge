# Queued Work — voice-forge

> **Future-work items by priority with explicit "worth it when" triggers.** When a promising idea surfaces but we don't build it right now, it goes here.
>
> Format:
>
> ```markdown
> ## P0/P1/P2/P3/Maybe — Short title
>
> **Priority.** P0 (must-ship-before-X) / P1 (urgent) / P2 (important) / P3 (nice-to-have) / Maybe.
> **Effort.** Rough estimate (hours / half-day / day / week).
> **Worth it when.** Specific trigger that would make this pressing.
> **Context.** What surfaced this; cross-references.
> ```
>
> When the work is done → move to `ARCHIVE.md` as SHIPPED with date + commit.
> When consciously rejected → move to `ARCHIVE.md` as REJECTED with reason.

---

## P2 — Per-voice tunable sampling params (speed, nfe_step, repeat_penalty, temperature, …)

**Priority.** P2 — surfaced by F5 audition where the default `speed=1.0` produced noticeably slower-than-NeuTTS audio that some listeners found unnatural.

**Effort.** ~half-day. Schema + plumbing through the Protocol + per-voice metadata.json updates + CLI surface.

**Worth it when.** Now-ish for F5 (`speed`, `nfe_step`, `cfg_strength`, `seed`); also already needed for NeuTTS (`repeat_penalty`, `temperature`) and Kokoro (`speed`). Adding XTTS next will pile on more knobs (`temperature`, `top_k`, `top_p`, `length_penalty`). Without per-voice overrides, we end up with global defaults that work for some voices and break others — the v0.2 F5 audition already showed Heid drifts at default settings while Saga + Hnoss hold.

**Context.** Three layers to design:
1. **Per-voice metadata.json schema.** Add an optional `sampling: {key: value, ...}` block. Backends read what they recognize, ignore the rest. Backwards-compatible (missing key = backend default).
2. **Protocol surface.** Either: (a) add an optional `sampling_overrides` arg to `synthesize()` / `synthesize_stream()`; or (b) backends pull from `VoiceRef.metadata.get("sampling", {})` inside their own implementations. (b) is non-breaking and easier to roll out.
3. **CLI ergonomics.** `voice-forge voice add ... --sampling speed=1.1 --sampling nfe_step=24` writes into metadata.json. `voice-forge voice tune <id> --sampling key=val` for post-registration adjustment.

Ideal end state: when you audition a sister and it sounds wrong, you tweak her metadata.json (or run `voice tune`) and re-audition without changing global backend defaults. This is what the user surfaced as "ideally on a per voice basis" in the v0.2 F5 audition feedback.

**Open question for design time.** Do we expose ALL backend-native sampling params, or curate a smaller subset that's stable across backends? Curated wins for UX (`speed` works everywhere); native wins for power-users. Best answer is probably both: curated names with backend-specific extras under a namespaced key.

---

## P2 — Kitten backend (smallest model, ONNX, CPU-only)

**Priority.** P2 — lightweight option for resource-constrained hosts.

**Effort.** ~2-3 hours.

**Worth it when.** v0.1.0 ships + we want a sub-100MB backend option (Pi, low-end Mac).

**Context.** KittenML/KittenTTS in [PRIOR_ART.md](../PRIOR_ART.md). Three variants: nano (15M), micro (40M), mini (80M). ONNX inference. Hermes-agent already has a KittenTTS provider — borrow the integration pattern from there.

---

## P2 — F5-TTS backend (Apache-2, diffusion-based)

**Priority.** P2 — higher-quality voice cloning option.

**Effort.** ~4-5 hours. Diffusion-based models have more complex inference loops.

**Worth it when.** NeuTTS's quality ceiling becomes binding (long-narrative incoherence, accent fidelity).

**Context.** Tracked in [ROADMAP.md](../ROADMAP.md). Requires GPU for real-time RTF (CPU is too slow for conversational use). Defer until we have a dedicated GPU host OR users explicitly want it.

---

## P2 — XTTS-v2 backend (Coqui, MPL-2)

**Priority.** P2 — multilingual + quality cloning.

**Effort.** ~3-4 hours.

**Worth it when.** Multilingual use cases emerge.

**Context.** [PRIOR_ART.md § xtts-streaming-server](../PRIOR_ART.md). MPL-2 weakly copyleft (file-level) — safe to depend on. GPU recommended.

---

## P2 — Dia backend (first community service wrapper for Dia)

**Priority.** P2 — opportunity to be the first community Dia service wrapper.

**Effort.** ~6-8 hours. No prior service wrapper exists; we'd be solving concurrency, streaming, voice caching from scratch.

**Worth it when.** Multi-speaker dialogue use cases (interactive fiction, agent-to-agent conversations) drive the need.

**Context.** nari-labs/dia-1.6B in [PRIOR_ART.md](../PRIOR_ART.md). Speaker tags `[S1]`/`[S2]` for multi-speaker. Apache 2.0. Requires 10GB VRAM — GPU host needed.

---

## P2 — Chatterbox-Turbo backend (sub-200ms latency)

**Priority.** P2 — when first-byte latency dominates UX.

**Effort.** ~3-4 hours.

**Worth it when.** Voice-call / real-time use cases where waiting 3-5s for first audio is visibly slow.

**Context.** Resemble AI. 350M params, single diffusion step, MIT license. Voice cloning + emotion control.

---

## P2 — MeloTTS backend (multilingual + CPU-friendly)

**Priority.** P2 — multilingual without GPU requirement.

**Effort.** ~3 hours.

**Worth it when.** Multilingual + low-resource deployment combo matters (Pi-class hardware with multilingual personas).

**Context.** MyShell.ai, 6+ languages with mixed-language utterance support, MIT.

---

## P2 — Piper backend (subprocess wrapper)

**Priority.** P2 — defensive fallback for "always works" scenarios.

**Effort.** ~2 hours. Subprocess-call only (don't include code; Piper is GPL-3).

**Worth it when.** voice-forge's primary backends fail; need an "always responds with something" backstop.

**Context.** rhasspy/piper. 30+ languages. GPL-3 (kept at arms-length via subprocess call). Already deployed in infiquetra/home-lab as the original Asgard baseline TTS.

---

## P2 — WebSocket bidirectional streaming (`WS /tts/stream`)

**Priority.** P2 — adds value for chat / real-time use cases.

**Effort.** ~4-6 hours.

**Worth it when.** v0.2.0 milestone OR a real-time use case needs progressive synthesis with text-arriving-in-chunks (live transcription → live synthesis pipelines).

**Context.** Wyoming protocol demonstrates the value of bidirectional streaming (lower perceived latency for incremental input). FastAPI has WebSocket built-in.

---

## P2 — Wyoming protocol adapter (Home Assistant integration)

**Priority.** P2 — opens voice-forge to the Home Assistant ecosystem.

**Effort.** ~3-4 hours.

**Worth it when.** Home Assistant users want voice-forge as a TTS provider (replacing Piper-Wyoming for sister Asgard voices).

**Context.** Wyoming protocol spec at github.com/rhasspy/wyoming. JSONL header + PCM payload over TCP. Different from REST but additive — same backend, different surface. Voice-forge can expose BOTH.

---

## P3 — NeuTTS streaming content-loss investigation

**Priority.** P3 — blocks flipping streaming-default to true.

**Effort.** ~2-4 hours.

**Worth it when.** Streaming latency benefits become important enough to investigate.

**Context.** Home-lab LEARNINGS 2026-05-24 "NeuTTS streaming drops 15-21%". Need to instrument `_infer_stream_ggml` to log every emitted token + stop-token detection. Compare batch and stream token streams for identical input.

---

## P3 — OpenAI-API-compatible authentication (Bearer / api_key)

**Priority.** P3 — required when we expose voice-forge externally.

**Effort.** ~2-3 hours.

**Worth it when.** Multi-tenant / network-exposed deployment needs.

**Context.** v0 is localhost-only. When we deploy to a network-accessible host, need bearer-token auth at minimum. Plan: support both `Authorization: Bearer <token>` and OpenAI-SDK's `api_key` header.

---

## P3 — Helm chart for Kubernetes deploy

**Priority.** P3 — distributed deployment story.

**Effort.** ~1 day.

**Worth it when.** Multi-host / multi-tenant deployment scale matters.

**Context.** voice-forge is stateless except for FS registry. Helm chart for stateless backend + persistent volume for registry.

---

## P3 — Kokoro voice-mixing tensor blending (full impl of the `name(weight)+name(weight)` syntax)

**Priority.** P3 — the syntax surface ships in v0.2; only the multi-voice blending degraded to a fallback.

**Effort.** ~2-3 hours pending upstream API discovery.

**Worth it when.** Someone wants to actually interpolate Kokoro voices and the current "highest-weight fallback" isn't enough.

**Context.** The parser (`src/voice_forge/backends/_mixing.py`) and the `_resolve_voice` plumbing ship in v0.2. Multi-voice mixes currently log a degradation warning and return the highest-weight voice name. Real blending needs:
- Discover the upstream `KPipeline` API for accessing per-voice embedding tensors (`pipeline.voices`? `pipeline.model.voices`?), OR pin the HF-cache file-path layout for the per-voice `.pt` files.
- `torch.load(voice_pt_path, weights_only=True)` each named voice's tensor, weighted-average them.
- Pass the resulting tensor as `voice=blended_tensor` to `pipeline(...)`.

See [LEARNINGS 2026-05-24 § Kokoro voice-mixing tensor blending](../engineering-journal/LEARNINGS.md).

---

## P3 — Bulk ElevenLabs Voice Lab import

**Priority.** P3 — productivity feature.

**Effort.** ~2 hours.

**Worth it when.** Someone has 20+ voices to migrate from ElevenLabs at once.

**Context.** Currently `voice-forge voice from-elevenlabs` is one-at-a-time. Bulk import: `voice-forge voice import-elevenlabs --all` (lists user's ElevenLabs workspace, pulls each).

---

## P3 — Speaker diarization for multi-speaker ref audio

**Priority.** P3 — opens the door for "I have a podcast clip, give me each speaker as a separate voice"

**Effort.** ~3-4 hours pending choice of diarization model.

**Worth it when.** Voice cloning UX matters for podcast/interview-sourced refs.

**Context.** pyannote.audio diarizes; we'd split per-speaker audio into per-voice refs.

---

## P3 — CLI TUI for browsing voices

**Priority.** P3 — quality-of-life.

**Effort.** ~1 day.

**Worth it when.** voice library grows beyond ~20 voices and grep is annoying.

**Context.** Textual / Rich-based TUI. List voices, audition (synth + play), edit metadata. Inspired by lazygit / k9s pattern.

---

## P3 — Per-voice sampling-param overrides

**Priority.** P3 — fine-tuning lever.

**Effort.** ~2 hours.

**Worth it when.** A specific voice needs different temperature / top_k / repeat_penalty than the backend default.

**Context.** Store overrides in `metadata.json` under a `sampling` key. Backend reads + applies before each synth call.
