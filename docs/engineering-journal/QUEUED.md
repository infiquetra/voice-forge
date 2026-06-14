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

## P2 — One-tap "distinct accent?" toggle on the clone flow

**Priority.** P2 — the clone-create path currently defaults `accent_distinct=true` (route to an LLM-backbone backend when installed) because diffusion can't recover a lost accent. That's the safe default, but it over-routes neutral-accent clones to a heavier backbone.

**Effort.** Half-day (touches forge-empty-hero's clone block + threading the flag through forge-clone → _onClone → infer-backend).

**Worth it when.** Users complain that neutral clones land on a heavy backbone unnecessarily, OR the cold-start UX gets a polish pass. The designed behavior (KTD4) was an explicit one-tap ask; the v1 default is a stand-in.

**Context.** Capstone review (2026-06-14) found U6 was unreachable (clone never sent the flag). Fixed by defaulting to true (commit `efdd518`); the proper UX is the one-tap affordance in the clone block so the user states whether the source has a distinct accent. See [LEARNINGS 2026-06-14](LEARNINGS.md).

---

## P3 — Decode silence-collapse peak from design-candidate data: URIs

**Priority.** P3 — cosmetic robustness on the design path.

**Effort.** Couple hours (decode the MP3 data: URI → peak in forge-contact-sheet `_prep`, or have the server compute + return a `silent` flag on each `DesignCandidate`).

**Worth it when.** Designed previews start coming back silence-collapsed often enough that the contact-sheet's pre-greying matters for them. Today the auto silence-collapse only fires on the WS/pcm path; design candidates carry only a data: URI (no pcm), so a collapsed designed take renders as healthy.

**Context.** Capstone review (2026-06-14) P3. Documented inline in forge-app `_toCandidates`.

---

## P2 — Fine-grained component updates (don't rebuild the fleet on every focus)

**Priority.** P2 — correctness is fine today; this is a scale + UX-polish refinement.

**Effort.** Half-day.

**Worth it when.** The fleet routinely exceeds ~30 voices (the maintainer's Asgard registry is already 45) and selection/synth feels janky, OR the "focus a different card stops the previously-playing take" behavior becomes annoying in real use.

**Context.** The Forge's vanilla base class (`base.js`) replaces the whole `#root` `innerHTML` on any observed-store change (no virtual DOM / fine-grained reactivity — the deliberate no-build tradeoff). So `forge-app` observing `focused` rebuilds **every** `<forge-voice-card>` (each its own shadow DOM) on every selection, and a card observing `focused` re-renders itself — tearing down any `<forge-waveform>` playing inside it when you focus away. The 2026-06-14 self-destruct bug ([LEARNINGS](LEARNINGS.md)) was the acute case (fixed by not writing `forging` on playback); this is the residual structural cost. Options: (a) targeted host-attribute updates for `aria-selected` instead of a full re-render; (b) a `bind()`-only refresh path that patches attributes without replacing children; (c) keep the playing chip alive across re-renders by reusing the element. Don't add a framework — that breaks the no-build rule (R23).

---

## P3 — MeloTTS install blocked on upstream packaging quality (arm64 macOS)

**Priority.** P3 — gated by upstream. The voice-forge side is shipped + ready; what's blocked is the actual provisioning command.

**Effort.** Zero on our side until upstream is fixable. When/if upstream lands a clean wheel for arm64 macOS + modern Python, the existing `voice-forge backend install melotts` should "just work" — no code changes needed.

**Worth it when.** myshell-ai/MeloTTS publishes either (a) a fixed PyPI sdist, (b) modern arm64 wheels for its transformers + tokenizers transitive closure, or (c) loosens the `transformers==4.27.4` pin so a recent wheel-covered version can satisfy.

**Context.** Discovered 2026-05-25 by running the real install. Three layered defects (see [LEARNINGS § "Upstream packaging defects in TTS backend ecosystem"](LEARNINGS.md)):

1. MeloTTS==0.1.1's PyPI sdist is broken (missing src/requirements.txt). Bypassed by installing from git.
2. Transitive dep `fugashi` requires system MeCab. Bypassed by `brew install mecab`.
3. Transitive dep `tokenizers==0.13.3` lacks macOS arm64 wheels — requires Rust toolchain to build from source.

The backend module (`src/voice_forge/backends/melotts.py`), CLI integration, and KNOWN_TUNABLES schema are all shipped. `/v1/backends` advertises melotts; attempting to load() raises SubprocessBackendNotInstalled with the install-command hint.

---

## P3 — Cap voice_id cardinality on /metrics

**Priority.** P3 — only matters when voice-forge runs a multi-tenant deploy with hundreds+ of voice_ids and a Prometheus scraper.

**Effort.** ~2 hours. Two reasonable approaches: (a) hash voice_id to a fixed-size set of label buckets ("voice_0".."voice_31"); (b) keep top-N most-recently-used voice_ids labeled, lump the rest into an "other" bucket. (b) is friendlier for debugging.

**Worth it when.** A Prometheus TSDB starts complaining about high-cardinality series, OR a deploy registers >100 voices.

**Context.** v0.3 metrics surface (commit pending) labels `voice_forge_synth_seconds`, `voice_forge_synth_requests_total`, and `voice_forge_ws_sentences_total` by `voice_id`. Each unique voice_id creates a new time series; at hundreds-of-voices scale this blows up storage + scrape cost. v0.2.0 Asgard fleet is ~10 voices so we're fine today. Doc cross-ref in `src/voice_forge/metrics.py` module docstring.

---

## ~~P1 — Subprocess-isolated backend pattern (architectural)~~ SHIPPED 2026-05-25

> Moved to ARCHIVE.md as SHIPPED. Pattern lives at
> `src/voice_forge/backends/_subprocess.py` + `subprocess_shim.py`.
> Piper, Chatterbox, MeloTTS backends sit on this. See LEARNINGS 2026-05-25
> § "Subprocess-isolated backends with HTTP-shim IPC".

## P1 — (placeholder; previously: subprocess pattern, now shipped)

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

---

## P3 — Investigate NeuTTS streaming content-loss (15-21% drop vs batch)

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

---

## P1 — The Forge: full web-UI redesign (rename /lab → /forge)

**Priority.** P1 — `/lab` got us to a working voice-tuning + audition surface, but it's an accumulation of patches, not a design. Every workflow we run currently (Voice Design → audition → ref-clip capture → backend registration → tuning → scorecard → handoff to production) lives across CLI, file edits, and the lab page in fragmented ways. Worth doing right once we have a couple more weeks of usage data.

**Effort.** Day-1 design + 2-3 days build + 1 day polish. UI-shaped work — best done after the v0.3 audition + persona workflow stabilizes so we know what to design FOR.

**Worth it when.**
- Voice Design audition becomes a routine workflow (Mimir lands, future personas, refresh cycles)
- We have 2+ users (not just the maintainer) and the duplicated-section / output-log-buried-at-bottom UX bites
- The secrets module ships (this lets the Forge handle credential config UI)

**Brainstorm — six pillars for the redesign:**

1. **Rename.** `/lab` → `/forge`. "Lab" reads like a sandbox; "forge" reads like the place voices get made. Service name stays voice-forge; the web surface adopts the name. Endpoint at `/forge` (alias `/lab` for back-compat one release).

2. **UX recomposition, not just restyling.** Current page is well-built per-section but the sections are stacked with no consideration for the **actual user flow**. Specific failure: clicking a voice speak button means the audio + timing output should be **visible without scrolling**, but the output log sits at the bottom of a 700-line scroll. Output-log + speak-controls should share a viewport. Likely needs a 2-column or tabbed layout, not the current accordion-down-the-page model.

3. **Configuration panel for secrets + LLM credentials.** Now that voice_forge.secrets ships (vault-encrypted credential store), the Forge needs a UI to manage entries — add/edit/show-with-mask/rotate. Same panel handles: ElevenLabs API key (for Voice Design + regen), OpenAI / Anthropic keys (for LLM-assisted prompt generation, see #4), service-side bearer tokens (deferred from v0.3 but landing eventually). One settings tab, structured form, never echoes raw values to DOM.

4. **External-LLM-via-API path for prompt generation, not embedded LLM.** Even with OAuth/API-key config in the Forge, **the Forge itself should not be an LLM client**. Instead: define a thin contract (`POST /v1/prompts/voice-design` body: `{persona: "mimir-engineer", soul_md: "...", existing_spec: {...}}`) that the Forge can call against any external tool that speaks it — Claude Code via redis-bridge, Codex via stdin, Anthropic API directly, etc. The Forge sends context, gets back a structured Voice Design spec proposal, displays diff vs current, user accepts. This keeps the Forge dependency-light and lets people use whatever LLM tool they already have configured.

5. **Dedicated audition workflow tab.** The current "lab" mashes together: persona × backend coverage matrix, knob tuning, scorecard editing, preset browser, reference playback. The audition lifecycle deserves its own first-class section: (a) draft a new persona's Voice Design spec (with optional LLM-assist from #4), (b) run audition → preview 3 → pick → persist, (c) regen ref WAV from the new voice_id, (d) auto-register into voice-forge backends, (e) test clone via every applicable backend, (f) refine the spec if results are bad, (g) plug into production. The full Voice Design → cloning → production path lives in one tab.

6. **"Scan the workflows we actually execute" as the design step.** Don't redesign from scratch. Concretely: enumerate every shell command, every CLI invocation, every web-form click, every text edit we've made in the last 2 weeks to get Asgard configured. That list IS the workflow surface the Forge needs to support. Then group, prioritize, sequence. The current `/lab` was designed before we knew what the workflows looked like; the v2 should be designed after.

**Out of scope for this entry, but adjacent:**
- Streaming-quality A/B comparison UI (already partially in `/lab`)
- Per-voice metrics dashboards (folds into the "test clone via every backend" step above; needs `/metrics` data piped through)
- Multi-tenant Forge (separate concern; not v0.3)

**Refs.** Current page at `src/voice_forge/static/lab.html` (~770 LOC vanilla JS, becoming hard to extend). The user's stated frustrations 2026-05-26 — output log placement, no consideration of usability between sections. The completed `/v1/backends`, `/v1/scorecard`, `/v1/personas/prompts`, `/v1/voices/{id}/reference`, `/v1/presets/<backend>/sample`, `/v1/tts/stream` endpoints are good — UI redesign doesn't need new server work, just better composition.

---

## P2 — Document ElevenLabs 500-char description cap + update `prompt_builder` (#56)

**Priority.** P2 — silent truncation today produces voices that are missing the back half of their phonetic spec without warning. Cheap, high-confidence fix.

**Effort.** ~30 min. One constant change + one note in the module docstring + a sentence in `docs/voice-design-guide.md`.

**Worth it when.** Now — before the next persona is auditioned through ElevenLabs Voice Design. The current 1000-char value in `prompt_builder.py:86` is wrong and any future design built against it gets silently truncated server-side at ~500 chars.

**Context.** Discovered 2026-05-26 during Mimir tuning: ElevenLabs UI accepts up to 1000-char descriptions but persists ~500 chars to the saved voice. Mimir's stored description is exactly 496 chars — sitting at the cap. Voice-forge's `PROMPT_CHAR_LIMIT = 1000` (with `PROMPT_SAFETY_MARGIN`) produces prompts that are silently chopped server-side after the 500-char point. The user discovered this by ear: a description that scored well in interactive testing rendered audibly worse once saved.

**Changes.**
- `src/voice_forge/voice_design/prompt_builder.py:86` — `PROMPT_CHAR_LIMIT = 500` (was 1000). Keep `PROMPT_SAFETY_MARGIN = 20` → effective cap 480.
- Module docstring rule §5 — replace "Prompt cap is ~1000 chars" with the truncation finding + safety margin reasoning.
- `docs/voice-design-guide.md` — add the cap warning in the prompt-design section.

**Refs.** [LEARNINGS § "ElevenLabs Voice Design pipeline quirks discovered through Mimir + Freya tuning"](LEARNINGS.md) item 3. Commit `0b51de3` (output_format bugfix + library client).

---

## P2 — Re-design Eir voice with explicit phonetic guidance (#58)

**Priority.** P2 — Eir is the last Asgard holdout. Of the 4 voices that needed Higgs over F5, three (Mimir / Freya / Trjegul) now preserve accent through Higgs cloning; Eir does not. Phonetic-imperative description rebuild is the next lever.

**Effort.** ~1 hour: rewrite description in the Freya-pattern phonetic-imperative form → 3-preview audition through ElevenLabs Voice Design → pick + persist → regen `personas/asgard/eir-wellness/ref.wav` → re-run Higgs synth → ear-test.

**Worth it when.** Now — the rebuild pattern is hot. The phonetic-imperative form ("rolled R sounds, softened consonants, th drifts toward d") fixed Freya in one pass after the categorical-label form ("Heavy Norwegian accent") failed across multiple iterations. Eir's current description is categorical-label-shaped; rebuild it in imperative form.

**Context.** Eir's failure mode (per LEARNINGS): the source ElevenLabs voice itself has weaker accent characteristics in the recorded audio than the other 4 voices. Fixing ref.txt audio/text mismatch (commit `7b3bef3`) did not bring accent back through Higgs — the dominant signal is the source recording, not ref_text quality. Logical next step: rebuild the source recording from a stronger description.

**Changes.**
- `personas/asgard/eir-wellness/voice_design.yaml` (or wherever the spec lives) — rewrite description to use phonetic imperatives. Reference Freya v2's description structure as the template.
- Audition via `voice-forge-secrets`-backed ElevenLabs key + `scripts/voice_design.py audition eir-wellness --previews 3`.
- Persist winning preview → `personas/asgard/eir-wellness/ref.wav` overwrite (back up first).
- Re-run the 5-voice Higgs matrix (`~/.claude/jobs/.../higgs_final_matrix.py` pattern) including Eir; confirm accent preservation by ear.

**Refs.** [LEARNINGS § "Phonetic-imperative voice descriptions beat categorical accent labels in ElevenLabs Voice Design"](LEARNINGS.md). [LEARNINGS § "Fixing ref.txt audio/text mismatch doesn't recover accent if source recording is weak"](LEARNINGS.md). Commit `7b3bef3` (Eir ref.txt fix). Freya v1/v2 entries in `personas/asgard/`.

---

## P2 — Refactor MLX TTS backends to a single generic `mlx_audio` backend (#59)

**Priority.** P2 — pre-emptive cleanup before we add a second MLX-backed model. Adding Qwen3-TTS-VoiceDesign (#60) as a new `qwen3_tts_mlx.py` would duplicate 90% of `higgs_mlx.py`'s code; better to refactor once.

**Effort.** ~half-day. Pull `higgs_mlx.py`'s threading/streaming machinery into a generic `mlx_audio.py` backend that takes `mlx_audio_model_path` as a config field. Higgs becomes `mlx_audio_model_path="mlx-community/higgs-audio-v2-3B-mlx-q6"`; future Qwen3 becomes `mlx_audio_model_path="mlx-community/Qwen3-TTS-12Hz-1.7B-VoiceDesign-bf16"`.

**Worth it when.** Before #60 (Qwen3-TTS-VoiceDesign provider) lands. If we add Qwen3 first as a separate backend module, we accrue 600+ lines of near-duplicated code; if we refactor first, Qwen3 is a fleet.yaml line + a config dict.

**Context.** `mlx-audio` (Apache-2, `Blaizzy/mlx-audio` on PyPI) is a unified runtime: same `load_model + generate_audio` API for every TTS model in the mlx-community HuggingFace org. The model-specific differences live in the model's MLX-quantized weights, not in the loading code.

**Design.**
- New module: `src/voice_forge/backends/mlx_audio.py` (~400 LOC, mostly relocated from `higgs_mlx.py`).
- Config schema: `{"model_path": str, "device": str, "max_workers": int}`.
- Per-model quirks (e.g. Higgs needs `audio_processing/` post-install clone) move to `_<model>_post_install.py` modules selected at install time by model_path.
- Keep `higgs_mlx` as an alias for the duration of v0.2.x backwards compat — emit deprecation warning pointing at `mlx_audio` + `model_path=mlx-community/higgs-audio-v2-3B-mlx-q6`.

**Risk.** The ThreadPoolExecutor / MLX-thread-local-stream binding (the production fix that kept higgs-mlx alive inside FastAPI) must be re-validated under the generic shape. Re-run the 10-call silence-check (`~/.claude/jobs/1d06b8bd/higgs_mlx_silence_check.py` adapted) against the refactored backend before declaring done.

**Refs.** [LEARNINGS § "mlx-community on HuggingFace is the free-port repository for Apple Silicon ML"](LEARNINGS.md). Commit `c8f4d90` (current higgs-mlx). Upstream API: `mlx_audio.tts.utils.load_model`.

---

## P2 — Add Qwen3-TTS-VoiceDesign as a voice_design provider (#60)

**Priority.** P2 — local-open-source Voice Design analog to ElevenLabs. Cuts a paid-API dependency, quadruples the description char cap (2048 vs ElevenLabs's silent 500), keeps descriptions on-device.

**Effort.** ~1 day. Depends on #59 (generic `mlx_audio` backend) landing first; otherwise duplicates Higgs-MLX scaffolding.

**Worth it when.** After #59 lands AND either (a) ElevenLabs billing becomes a real cost concern, OR (b) a new persona needs a >500-char phonetic description, OR (c) we want to demonstrate end-to-end fully-local voice design + cloning + render on Apple Silicon. Privacy story improves immediately.

**Context.** `mlx-community/Qwen3-TTS-12Hz-1.7B-VoiceDesign-bf16` — Apache-2, Qwen3-1.7B backbone, supports BOTH voice cloning (`ref_audio` + `ref_text`) and voice design (`instruct` parameter). Description language: Chinese OR English. Synthesis language: any supported (decoupled). 2048-char description cap.

**Design.**
- New module: `src/voice_forge/voice_design/qwen3_tts.py` mirroring `voice_design/elevenlabs.py` shape (audition + persist + library-browse stubs where applicable).
- Provider abstraction: `VoiceDesignProvider` Protocol in `voice_design/__init__.py` — `audition(description, previews=3) -> list[Preview]`, `persist(preview) -> voice_id`. Both ElevenLabs and Qwen3 implement it.
- CLI: `voice-forge-design audition --provider qwen3 --persona mimir` (default provider stays elevenlabs for v0.2.x; flip default in v0.3).
- Reuse the generic mlx_audio backend from #59 for the actual model load + synth call.

**Open questions.**
- Does the `mlx-audio` port expose `generate_voice_design()` separately from `generate_audio()`? If not, the `instruct` parameter has to thread through `generate_audio`'s kwargs — verify by reading the mlx-audio source before designing the provider API.
- Quality vs ElevenLabs on Norwegian phonetic-imperative prompts is unverified. First audition: re-design Mimir from his current description via Qwen3 → compare by ear.

**Refs.** [LEARNINGS § "Qwen3-TTS-VoiceDesign is the local-open-source Voice Design analog to ElevenLabs"](LEARNINGS.md). Upstream model card: `https://huggingface.co/mlx-community/Qwen3-TTS-12Hz-1.7B-VoiceDesign-bf16`. Depends on #59.

---

## P1 — higgs-mlx: server-side retry-on-silence guard (#61)

**Priority.** P1 — gates higgs-mlx adoption as the default Asgard backend. Today, half of Mimir's higgs-mlx calls return silence. The transformers `higgs` backend remains production until this lands.

**Effort.** ~2-3 hours. Wrap `higgs_mlx.synthesize()` with a retry-on-silence loop. Reuse the verification harness at `~/.claude/jobs/1d06b8bd/higgs_mlx_silence_check.py` (or relocate to `tests/functional/higgs_mlx_silence_check.py`) for the success-criteria check.

**Worth it when.** Now-ish. higgs-mlx delivers ~9× speedup over the transformers `higgs` backend (0.27-0.35× RTF vs 2.45-3× RTF on M2 Ultra) for mainstream-distribution voices, but the bimodal silence-collapse failure on distribution-edge voices (Mimir, likely Freya / Trjegul by extension) makes it unsafe as default without retry. The retry math is favorable: 50% per-call → 12.5% per-utterance after 3 retries → ~6% after 4 → ~3% after 5.

**Context.** Verified 2026-05-26 with a 10-call cold sweep on Mimir's reference: exactly 5/10 returned silence (peak < 0.05, RMS < 0.005); the other 5 returned full-amplitude clean speech (peak 0.47-0.77, RMS 0.03-0.06). No intermediate outcomes — bimodal. Mechanism (per LEARNINGS): the autoregressive decoder picks an audio-token trajectory near generation start; for distribution-edge voices the trajectory is a near-coin-toss between valid-speech and silence-basin trajectories. The full-precision transformers `higgs` backend doesn't exhibit this — the sharpness of its next-token distribution at the distribution edge biases away from the silence basin.

**Design.**
```python
def synthesize(self, text: str, ref: VoiceRef) -> np.ndarray:
    max_retries = self._config.get("max_silence_retries", 3)
    silence_peak_threshold = 0.05
    for attempt in range(max_retries + 1):
        pcm = self._synth_once(text, ref)
        peak = float(np.max(np.abs(pcm))) if pcm.size else 0.0
        if peak >= silence_peak_threshold:
            return pcm
        # else: silence detected, retry; emit a metric
        _METRICS["higgs_mlx_silence_retries"].labels(voice_id=ref.voice_id).inc()
    # Exhausted retries — return last attempt + log loudly.
    log.warning("higgs-mlx exhausted %d silence retries for voice %r; returning silent PCM", max_retries, ref.voice_id)
    return pcm
```

Streaming variant (#21-style sentence pipelining) needs the same guard at sentence granularity, not utterance.

**Acceptance criteria.**
- 10-call sweep on Mimir post-retry: silence rate < 5%.
- Worst-case latency on a silence-prone voice: documented as `(max_retries + 1) × RTF × audio_length`.
- New Prometheus metric `higgs_mlx_silence_retries_total{voice_id=...}` so operators see the cost.
- Once acceptance met, flip `higgs-mlx` to default for Mimir / Freya / Trjegul in the persona fleet.

**Refs.** [LEARNINGS § "higgs-mlx 50% silence-collapse on distribution-edge voices — bimodal failure mode"](LEARNINGS.md). Verification script: `~/.claude/jobs/1d06b8bd/higgs_mlx_silence_check.py` (relocate before job teardown). Commit `c8f4d90` (higgs-mlx backend), commit `90f0067` (LEARNINGS entry verifying 50% rate).
