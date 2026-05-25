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

## P1 — Subprocess-isolated backend pattern (architectural)

**Priority.** P1 — unblocks at least two backend candidates we can't ship without it (Chatterbox, Piper).

**Effort.** ~1 day pending design choices. The core abstraction is one new backend base class + a venv-provisioning step + an IPC protocol (stdin/stdout JSON or a per-backend HTTP shim).

**Worth it when.** Now-ish, given:
- **Chatterbox-tts 0.1.7** has exact pins on `torch==2.6.0` + `transformers==5.2.0` + `diffusers==0.29.0` + `safetensors==0.5.3` + `gradio==6.8.0`. None of these are compatible with voice-forge's main venv (which holds F5 / Dia / XTTS / Kokoro all happily). Smoke-tested 2026-05-25 in an isolated `$CLAUDE_JOB_DIR` venv; quality is good enough to want to ship. See [Chatterbox findings LEARNING](../engineering-journal/LEARNINGS.md).
- **Piper** is GPL-3 — voice-forge is Apache-2. Including Piper code in our codebase forces GPL on us; subprocess-only is the established workaround.
- **Any future backend** with similar packaging hygiene issues benefits from the same pattern.

**Context.** Two viable approaches:
1. **Per-backend venv + JSON-over-stdin/stdout IPC.** voice-forge spawns a subprocess running a small server-like script in the backend's isolated venv. Requests/responses are JSON (text + voice_id) → raw WAV bytes (or base64'd). Cold-load cost is per-process startup once; subsequent synths reuse the live subprocess.
2. **Per-backend venv + tiny HTTP shim.** Each isolated backend runs its own micro-server (FastAPI again, or just `http.server`), voice-forge proxies. More overhead per call but reuses our existing HTTP plumbing.

(1) is leaner for the cloning-backend use case where latency matters. (2) is more debuggable.

For both: voice-forge needs a way to provision the per-backend venv on first use (run `uv venv` + `uv pip install <pinned-deps>`). Could be a `voice-forge backend install <name>` admin command. Per-backend venv lives at `~/.voice-forge/venvs/<backend>/`.

**Refs.** [Chatterbox LEARNING](../engineering-journal/LEARNINGS.md), `tests/functional/output/v0.2-chatterbox-smoke-20260525/` (audition WAVs from the isolated test — ephemeral, may not survive job teardown).

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

## P2 — Chatterbox-Turbo backend integration (depends on subprocess pattern)

**Priority.** P2 — quality is good (single-step diffusion, clean Heid p1 — first cloning-class backend that doesn't break on her ref!) but cannot ship today.

**Effort.** ~2-3 hours once the subprocess-isolated backend pattern (P1 above) lands. The actual `ChatterboxTurboTTS` API is clean: `from_pretrained(device=...)` + `.generate(text, audio_prompt_path=...)`.

**Worth it when.** Subprocess pattern is ready AND we want a third identity-preserving cloning backend in the rotation (F5 is the leader; Chatterbox would be a backup with different failure modes).

**Context.** Smoke-tested 2026-05-25 in an isolated venv at `$CLAUDE_JOB_DIR/chatterbox-venv`. 9 WAVs produced (3 sisters × 3 prompts).

**Audition findings (audio quality):**
- p1 (short utterance) on all 3 sisters: clean. **Heid p1 → 1.12 s of clean audio** — first cloning-class backend besides Kokoro/F5/XTTS to handle her ref without the autoregressive 0.16-0.20 s collapse. Single-step diffusion architecture sidesteps the trigger.
- p2 (30 s introduction) on all 3: clean but **accent not preserved** on Saga + Hnoss. Same XTTS-style "pitch + gender adapt, accent lost" behavior. NOT identity-preserving cloning.
- p3 (80 s story) on all 3: **truncated at ~35-37 s** AND becomes gibberish past the cap. Likely needs `max_new_tokens` (or chatterbox's equivalent) tuned per voice — see per-voice tunables QUEUED entry.

**Audition findings (deployment-fitness):**
- `chatterbox-tts==0.1.7` has **5 exact-version pins** on heavy ML deps: `torch==2.6.0`, `transformers==5.2.0`, `diffusers==0.29.0`, `safetensors==0.5.3`, `gradio==6.8.0`. The transformers pin alone is incompatible with every other v0.2 backend.
- Runtime crash on construct: `perth.PerthImplicitWatermarker()` returned None. Required a no-op stub monkeypatch before model load. (Resemble's Perth watermarker library — same one we already disabled in NeuTTS for streaming click artifacts.)
- M2 Ultra MPS RTF: 1.13-2.40 warm, 7.17 cold. Slower than F5, faster than XTTS-CPU.

**To do at integration time:**
1. Provision a per-backend venv with chatterbox's exact-pinned deps.
2. Subprocess IPC: voice-forge → chatterbox-venv subprocess (text + ref_audio_path in, WAV bytes out).
3. Per-voice sampling params for the long-form fix (whatever chatterbox's `max_tokens`-equivalent is).
4. Document the Perth watermarker stub requirement.

**Generalizable rule (captured in LEARNINGS).** Backends with exact-version pins on shared transitive deps need subprocess isolation; treat the pins as a fitness signal even before testing audio.

**Refs.** `$CLAUDE_JOB_DIR/run_chatterbox_smoke.py` (the throwaway smoke script — may be gone after job teardown), [Subprocess pattern P1](#p1--subprocess-isolated-backend-pattern-architectural), [Chatterbox audio findings LEARNING](../engineering-journal/LEARNINGS.md).

---

## P3 — Fish Audio S2 Pro backend (research license + multi-step inference)

**Priority.** P3 — likely doesn't change the standings vs F5; high integration cost.

**Effort.** ~3-4 hours including model download (~10 GB), checkpoint disambiguation (S2-Pro vs openaudio-s1-mini), api_server provisioning, smoke synth.

**Worth it when.** Need 80+ language multilingual coverage AND/OR want to test their inline emotion-tag system (`[whisper]`, `[excited]`, `[angry]`, plus 15K+ free-form descriptors). Not worth it just to test "another cloning backend" — F5 is the answer there.

**License.** **Fish Audio Research License** — research/non-commercial only. Commercial use requires paid license from business@fish.audio. Same shape as XTTS-v2's CPML; same `COQUI_TOS_AGREED`-style env-var gate would apply (`FISH_AUDIO_RESEARCH_LICENSE_AGREED=1` or similar). Plus an attribution requirement: "Built with Fish Audio" must appear on any product using it.

**Install picture (verified 2026-05-25):**
- No real PyPI package (`fish-speech==0.1.0` is a placeholder, no metadata). Real install path: `git clone github.com/fishaudio/fish-speech + uv pip install -e .`
- Pinned deps that conflict with main voice-forge venv: `torch==2.8.0` (exact), `transformers<=4.57.3`, `pydantic==2.9.2` (exact), `einx==0.2.2` (exact), `datasets==2.18.0` (exact), `modelscope==1.17.1` (exact). **Cannot coexist** with our main venv — needs the subprocess-isolated backend pattern (QUEUED P1).
- System dep: `pyaudio` requires `brew install portaudio` on macOS.
- Verified install works in isolated venv at `$CLAUDE_JOB_DIR/fishaudio-venv` (Python 3.12 + torch 2.8 + transformers 4.57.3 + pydantic 2.9.2 + MPS available + `fish_speech` module imports cleanly).

**Architecture (worth knowing before integration):**
- **No simple Python API.** Inference is a 3-step CLI pipeline: encode-ref → generate-tokens → decode-audio, each a separate script under `fish_speech/models/dac/inference.py` etc.
- Their `tools/api_server.py` is a FastAPI server — easiest integration is to run that as a subprocess and HTTP it (like Piper's intended pattern).
- 4B-parameter Dual-AR (slow 4B + fast 400M). Their benchmark: RTF 0.195 on H200. Apple Silicon RTF unknown — likely 1-3x on MPS given model size.
- 80+ languages, native multi-speaker via `<|speaker:i|>` tokens, 15K+ inline emotion tags.

**Likely cloning-fidelity bucket (predicted, not verified).** Architecturally decoder-only transformer like XTTS + Chatterbox; the pattern across our four ear-tested decoder-only backends has been "no accent preservation." Would expect Fish Audio to land in the same pitch/gender-adapter bucket. NOT predicted to displace F5 for the identity-preserving cloning use case.

**Refs.** `https://github.com/fishaudio/fish-speech` (LICENSE = Fish Audio Research License, codebase Apache-2-shaped but with the research-only constraint on weights too), `https://huggingface.co/fishaudio/s2-pro` (4B model), `https://speech.fish.audio/` (docs). PRIOR_ART.md updated 2026-05-25 with the license correction (was wrongly marked "Apache 2.0" in the original survey).

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

## P2 — Wire voice-forge streaming into hermes-agent Discord adapter (consumer-side work)

**Priority.** P2 — table stakes for the hermes integration to actually deliver the streaming win we shipped.

**Effort.** Two changes in `infiquetra/home-lab` (hermes-agent code, not voice-forge):

1. **Stream-input Discord adapter** (~half day for pipe variant; ~1-2 days for custom `AudioSource`). Replace `discord.py::FFmpegPCMAudio(mp3_path)` with either:
   - `FFmpegPCMAudio(pipe=True, source=<pcm-fed-pipe>)` — voice-forge WS → buffer → pipe → FFmpeg PCM→Opus → Discord
   - Custom `discord.AudioSource` subclass that yields Opus frames directly from voice-forge's WS frames (bypasses FFmpeg)
2. **Forward LLM token stream to voice-forge WS** (~half day). Currently hermes-agent's TTS adapter waits for the full LLM reply, then POSTs to `/v1/audio/speech` with `stream: false`. Switch to opening a WS connection at LLM-stream start, pushing each token chunk as a `{"text": "..."}` frame. SentenceBuffer drains complete sentences as they form on the voice-forge side.

**Worth it when.** Whenever hermes-agent voice latency becomes a felt problem in production — current path is ~60-120 s on long replies; after both changes, ~3-5 s to first word.

**Context.** Detailed audit + mechanism in [LEARNINGS 2026-05-25 § "Streaming wins are only as good as the weakest link"](LEARNINGS.md). The voice-forge side is done — both streaming surfaces shipped + verified live (commits `5c144c8`, `694b0fe`, `eab204c`). The remaining work is entirely on the consumer side. Effort estimate assumes hermes-agent's TTS tool + Discord adapter are accessible; if either is more entangled than the audit suggests, scope grows.

---

## P2 — WebSocket bidirectional streaming (`WS /tts/stream`) — layer 2 of streaming

**Priority.** P2 — adds value for chat / real-time use cases.

**Effort.** ~4-6 hours.

**Worth it when.** v0.2.0 milestone OR a real-time use case needs progressive synthesis with text-arriving-in-chunks (live transcription → live synthesis pipelines).

**Context.** Layer 1 (sentence-chunked HTTP `StreamingResponse`) shipped in commit `5c144c8` and proved its win on F5 long-form (10.6× first-audio improvement on a ~995-char narrative — see `LEARNINGS.md` 2026-05-25). Layer 2 is the bidirectional WebSocket: text *arrives* in chunks (live transcription, LLM token-stream), synth begins as soon as the first sentence boundary is buffered, audio streams back. FastAPI has WebSocket built-in. Wyoming protocol is the obvious reference shape.

---

## P2 — Lift torch 2.8 pin in F5 extra when upstream resolves the torchcodec ABI gap

**Priority.** P2 — tracking item, not urgent.

**Effort.** ~30 min (bump pin, re-run audition, verify F5 still works).

**Worth it when.** A torch 2.9.x release (or a torchcodec 0.14+) ships that exports / no-longer-references `_aoti_torch_aten_subtract_Tensor`. Watch torchcodec's GitHub Releases page; the compatibility table at https://github.com/pytorch/torchcodec is the authoritative source.

**Context.** `pyproject.toml`'s `f5` extra currently pins `torch>=2.8,<2.9 + torchaudio>=2.8,<2.9 + torchcodec>=0.7,<0.8` because torch 2.9.x + torchcodec 0.13.0 ships a binary mismatch on macOS arm64 (see `LEARNINGS.md` 2026-05-25 "Torch 2.9.x + torchcodec 0.13.0 ABI gap"). Pin is temporary — lift when upstream is honest.

---

## P2 — Wyoming protocol adapter (Home Assistant integration)

**Priority.** P2 — opens voice-forge to the Home Assistant ecosystem.

**Effort.** ~3-4 hours.

**Worth it when.** Home Assistant users want voice-forge as a TTS provider (replacing Piper-Wyoming for sister Asgard voices).

**Context.** Wyoming protocol spec at github.com/rhasspy/wyoming. JSONL header + PCM payload over TCP. Different from REST but additive — same backend, different surface. Voice-forge can expose BOTH.

---

## P3 — Pin HuggingFace model revisions across backends

**Priority.** P3 — supply-chain hardening; not urgent until we see a real signed-model story we want to participate in.

**Effort.** ~2 hours per backend (5 backends × ~10 min each to find the right commit + write the revision pin + verify it still works).

**Worth it when.** voice-forge runs on hosts where we can't audit the HF Hub state, OR an attacker-uploaded model becomes a real concern in a deploy context, OR HF rolls out reproducible-build attestations we want to anchor on.

**Context.** Bandit B615 flags any `from_pretrained(model_name)` call without a `revision=` kwarg, because unpinned downloads silently follow whatever HEAD the model's repo points at. Currently suppressed inline (`# nosec B615`) on `dia.py:146-147`; F5 / XTTS / Kokoro / NeuTTS use the lib's internal HF download which doesn't trigger bandit at our `-ll` level but has the same risk shape. Right fix: each backend's `load()` accepts an optional `revision: str | None = "<known-good-commit-sha>"` config field; default to a pinned SHA, allow override for testing newer revisions. Validation: pin to current SHA + verify model loads identically.

**Priority.** P3 — blocks flipping streaming-default to true.

**Effort.** ~2-4 hours.

**Worth it when.** Streaming latency benefits become important enough to investigate.

**Context.** Home-lab LEARNINGS 2026-05-24 "NeuTTS streaming drops 15-21%". Need to instrument `_infer_stream_ggml` to log every emitted token + stop-token detection. Compare batch and stream token streams for identical input.

---

## P3 — OpenAI-API-compatible authentication (Bearer / api_key) — pending a token-issuance story

**Priority.** P3 — implementation is the easy part; figuring out where tokens come from is the gating decision.

**Effort.** Auth wiring itself: ~½ day (REST + WS first-frame token + tests + docs). Token-issuance story: separate decision, unbounded.

**Worth it when.** Multi-tenant / network-exposed deployment needs — combined with answering the issuance question.

**Context.** Considered for v0.3 (2026-05-25) and explicitly deferred. The auth-implementation problem is straightforward — FastAPI dependency for REST, first-frame token field for WS, env-or-file token store. What's missing is the surrounding story:

- **Where do tokens come from?** Issuance: hand-generated UUIDs? Per-user via a CLI command? OAuth flow against some IdP?
- **Who issues them?** voice-forge itself, or an external identity service?
- **What does a token bind to?** A person, an agent, a voice subset, an org?
- **Rotation?** Manual, time-based, on-event?
- **Revocation?** Pull from store, broadcast invalidation?

Until that decision is made, shipping the auth surface is half a feature — it would force users to invent tokens out of thin air. v0.3 ships localhost-only. Revisit when (a) we have a real network-exposure case AND (b) someone has thought through the issuance story for the deployment context.

Plan when re-engaging: support both `Authorization: Bearer <token>` and OpenAI-SDK's `api_key` header. WS auth via first-frame token field. Token store is FS-backed file `~/.voice-forge/auth.txt` or env var `VOICE_FORGE_AUTH_TOKENS` (comma-separated).

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
