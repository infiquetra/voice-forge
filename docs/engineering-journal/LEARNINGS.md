# Learnings — voice-forge

> **Empirical findings + mechanisms + fixes + validations.** When something turns out to be true that wasn't obvious — about a backend's behavior, a sampling-knob tradeoff, a deploy gotcha, a benchmark — it goes here. Include the **evidence** (commit / experiment / file:line) and the **mechanism** (why it's true), not just the observation.
>
> **Append new entries to the top.** Most-recent first.
>
> Format:
>
> ```markdown
> ## YYYY-MM-DD
>
> ### Short descriptive title
>
> **Context.** One paragraph framing the situation.
> **Evidence.** Specific commit / experiment / file:line.
> **Mechanism.** Why it happened (or why it's true) — root cause, not symptoms.
> **Fix (or queued).** Concrete action + commit hash, OR a QUEUED.md ref.
> **Validation (if applicable).** What later run proved the fix.
> **What surprised (optional).** The thing that wasn't in the original mental model.
> **Generalizable rule.** The lesson stripped of this specific incident.
> **Refs.** Cross-links to DECISIONS / QUEUED / narratives / other LEARNINGS.
> ```
>
> If a prior learning is invalidated by new evidence, **update inline AND move the pre-correction version to `ARCHIVE.md` as SUPERSEDED**. Never silently overwrite history.

---

## 2026-06-14 (The Forge — first browser run of the new studio)

### A no-build component studio built against an *assumed* API shape breaks the moment real data arrives — only serving it reveals it

**Context.** Built the 7 `<forge-*>` components + shell over several units, all guarded by `node --check` + pytest endpoint/registry tests, all green. The first time the page was actually served (`voice-forge serve` → `/forge` in a browser) two bugs surfaced that every prior test had missed, because both only manifest at runtime against the real server contract.

**Evidence.** Commit `39fa39f`, found via `mcp__Claude_Preview` driving `http://127.0.0.1:9876/forge/`. (1) `GET /v1/audio/voices` / `GET /v1/backends` return an OpenAI-style `{data:[…]}` envelope (server.py `VoicesList`/`BackendsList` at :206/:447; `VoiceInfo.id` at :198, `BackendInfo.{name,installed,is_default,tunables}` at :436) — the client assumed `{voices:[…]}` / `{backends:[…]}` and stored the raw envelope object as `store.voices`. With no backends installed the dev registry exposes `{data:[]}`, so the *empty* path looked fine; the fleet path was broken and unseen. (2) `forge-waveform._setPlaying` wrote `store.forging` on every play; the card and shell both `observe` `forging` and the vanilla base class replaces the whole `innerHTML` on any observed-key change → the playing `<forge-waveform>` was destroyed the instant it started.

**Mechanism.** Bug 1: tests asserted *my* shape, never the server's — a closed loop. The `{data:[]}` empty-registry response is shape-compatible with "no voices" under either assumption, so the empty-state tests passed and hid the divergence. Bug 2: full-`innerHTML`-on-change reactivity means **any** store key a component observes is a re-render trigger that tears down that component's entire subtree; a child writing a parent-observed key is a self-destruct. `store.forging` was overloaded as both "synthesis in flight" (wanted: skeleton face) and "a take is playing" (unwanted side effect).

**Fix.** Commit `39fa39f`. (1) One `asList()` normalizer in `base.js` at the `_load` boundary; consumers read a canonical bare array. (2) Playback is local (`refresh()` only, no store write); `forging` dropped from the shell's `observe`. Guards `test_load_normalizes_data_envelope` + `test_playback_does_not_trigger_global_rerender` lock both.

**Validation.** Live browser run: empty registry → cold-forge hero, clone-primary + describe-gated door (AE1); synthetic loaded fleet → forged + bound faces, a 440Hz take that **plays and stays mounted** (`sameElement:true, playing:true`), spec-editor knobs from the real tunables schema, serve console with the live call. Zero console errors.

**What surprised.** `node --check` + endpoint tests gave full green while the studio was unusable with real data. The empty-state passing is what made it *look* safe.

**Generalizable rule.** (a) Test the **server's** response shape, not the client's assumption — pin a contract test to the real payload, and never trust an empty/degenerate response to validate a populated path. (b) Under full-innerHTML reactivity, a component must **never write a store key an ancestor observes** while it owns live imperative state (audio, focus, scroll) — that state lives outside the render and a re-render destroys it. Don't overload one signal for two meanings.

**Refs.** [DECISIONS.md](DECISIONS.md) 2026-06-14 "The Forge v1"; work-session `docs/work-sessions/2026-06-14-the-forge.md`; QUEUED fine-grained-update refinement.

---

## 2026-05-26 (evening — TTS architecture audit)

### F5-TTS cannot preserve heavy non-default accents — architectural ceiling, not a tunable

**Context.** Audited the 9 Asgard sister voices through F5 cloning. Five (Beyla / Bygul / Gersemi / Heid / Saga) preserved their Nordic-English accents "close enough"; three (Freya / Eir / Trjegul) lost the accent entirely; Hnoss is a separate "wrong source accent" case. Added Mimir as a male-Nordic test voice (newly designed) — landed in the same failure pattern as the three sisters. Spent the session exhausting F5's knob + reference-content space trying to recover.

**Evidence.** Sweep matrices on Mimir, two-batch:

Batch 1 (vary cfg + speed): `cfg_strength ∈ {2.0, 3.0, 3.5, 4.0, 4.5}` × `speed ∈ {0.80, 0.85, 0.90}` × `nfe_step=32` (quality preset) — none recovered the accent. User-verified all listened-flat-American.

Batch 2 (phoneme-rich reference + phoneme-rich text):
- Trimmed Mimir's ref WAV to include `Yggdrasil` + heavy th/r content (forces non-default phoneme use).
- Target text added: *"The truth often lies beneath three breaths and a thoughtful pause. I think of the runes carved at Yggdrasil's root..."* — 7× `th`, 6× `r`, 1 Nordic-anchor word.
- `remove_silence=True` to clean inter-word artifacts.
- 5 variants (cfg ∈ {3.0, 3.5, 4.0}, speed ∈ {0.92, 0.95, 1.0}). User verdict: "all better sounding, none preserving accent."

Test text via Higgs (LLM-backbone, different architecture, same reference): user verdict for Mimir + 3 sisters: "Higgs is a win on accent" — 4-of-4 preserve accent the F5 was stripping.

**Mechanism.** F5-TTS uses a diffusion-based decoder conditioned on (a) the reference's mel spectrogram and (b) the target text's phoneme sequence. The phoneme stream defaults to standard-English realization of each grapheme. When the reference has a heavy non-default accent, the model has two competing signals: phonemes pointing toward American defaults, mel context pointing toward the reference. The architecture appears to weight the phoneme stream heavier than the mel context — likely because in training the mel context was MOSTLY aligned with the standard phoneme realization (training corpus is American/British-English-heavy). Result: F5 can clone *timbre + pitch* faithfully but the phonetic realization snaps back to the target text's language defaults regardless of accent in the reference.

This is consistent across the diffusion-based family — Chatterbox has the same failure mode (voice-forge LEARNINGS 2026-05-25 § chatterbox audition: "pitch+gender adapter only — does NOT preserve source accent"). XTTS-v2 is similar per user's prior testing of all backends.

The Llama-backbone family (NeuTTS, Orpheus, Higgs, CosyVoice) is different architecturally: an LLM generates audio tokens directly conditioned on a reference's audio-token sequence (in-context learning). No separate phoneme decoder; the LLM learns the reference's acoustic patterns including accent.

**Fix.** Hybrid per-voice backend selection:
- F5 for the 5 sister voices where it works (low first-audio latency, audio quality good)
- Higgs Audio V2 for the 4 problem voices (Mimir + Freya + Eir + Trjegul — though Eir still failing under Higgs as of session-end; queued for ElevenLabs re-design)
- voice-forge's existing per-voice backend selection (`saga-comms-f5` vs `saga-comms-higgs` etc.) is the right architectural framing.

**Validation.** 5-voice Higgs comparison sweep — user verdict 4/5 preserve accent: Mimir ✓ Trjegul ✓ Freya-v1 ✓ Freya-v2 ✓ Eir ✗ (separate failure mode — see entries below).

**What surprised.** I spent meaningful effort on the "phoneme-rich reference + phoneme-rich text" hypothesis — the published heuristic that F5 strips accent because the target text lacks accent-bearing phonetic markers, fixable by adding markers to both reference and target. The hypothesis is *technically correct* (more phonemes give the diffuser more constraint) but the magnitude of the effect on F5 specifically is too small to matter — the architectural ceiling dominates.

**Generalizable rule.** Diffusion-based TTS architectures with phoneme-aligned acoustic decoders have a structural ceiling on non-default accent preservation. No amount of cfg-strength / speed / phoneme-rich content tweaking moves that ceiling. The fix is different architecture (LLM-backbone autoregressive), not better knobs. When you've swept the relevant knob space and audio quality moves but the target trait doesn't, stop tuning and switch tools.

**Refs.** Commit `7b3bef3` (Higgs streaming output + per-voice backend split). [QUEUED #58 Re-design Eir with explicit phonetic guidance]. Supersedes earlier session hypotheses about "F5 with the right reference WILL preserve accent."

---

### LLM-backbone TTS architectures preserve non-default accents — Higgs Audio V2 validates the family

**Context.** Discovered via process of elimination after F5 + Chatterbox both failed on the same 4 voices, while NeuTTS (already in production for the daemon) preserved accent. Common variable: NeuTTS uses a Llama-3 1B backbone; F5 + Chatterbox use diffusion + VITS-derived architectures. Hypothesized the LLM-backbone family was the architectural fix.

**Evidence.** Integrated two new LLM-backbone backends + tested both:
- **Higgs Audio V2** (Boson AI, 3B Llama-3.2 backbone + audio extension, Apache-2): 4/5 voices preserve Nordic accent on first cold-test. User verdict for Mimir: "Higgs is a win on accent. Maybe a little tuning... it's not exact as the reference, but it's good enough. Frankly, it might be better." Validated subsequently on Trjegul + Freya-v1 + Freya-v2.
- **Orpheus TTS** (Canopy Labs, 3B Llama-3 finetune, Apache-2): integrated but voice cloning is unconfirmed — see "Orpheus cloning format undocumented" entry below.

For comparison, the diffusion family on the same Mimir reference:
- F5: strips accent on all knob configurations tested (10+ variants)
- Chatterbox: strips accent + adds timbre wobble

**Mechanism.** Llama-backbone TTS architectures predict audio tokens (e.g., SNAC codes for Orpheus, a multimodal audio codec for Higgs) directly from the LLM's next-token distribution, conditioned on the reference audio's tokenized form. There's no separate phoneme decoder to bias toward target-language defaults. In-context learning over the reference's audio token sequence makes the model produce target text in the reference's actual acoustic style — including accent.

Higgs's ChatML cloning prompt format makes this concrete:
```
system: voice-cloning instruction
user:   <ref_text>          ← what the reference SAYS
assistant: <ref_audio>      ← HOW the reference says it (as audio tokens)
user:   <target_text>       ← what to generate, in the SAME voice
```
The model is asked to continue the conversational pattern. The "voice" of the assistant turn is established by the reference audio tokens; the model generates the next assistant turn in that voice.

**Fix.** Higgs is voice-forge's production backend for the 4 voices F5 can't carry. Mimir + Freya v1 + Freya v2 + Trjegul confirmed; Eir queued for re-design. F5 stays default for the 5 sister voices it handles well (lower latency).

**What surprised.** That a 3B-param LLM-backbone TTS with verified-good architecture can be *2.45-3.0× slower than realtime* on M2 Ultra MPS while a much-smaller F5 diffusion model runs ~5× realtime. The autoregressive token-by-token generation pattern is fundamentally bandwidth-bound — no architectural escape via knob tuning. The honest answer for production-realtime LLM-backbone TTS on Apple Silicon is MLX (separate entry).

**Generalizable rule.** For "preserve non-default accent in clone" specifically — LLM-backbone architectures are the working family. Diffusion + VITS-derived architectures hit a structural ceiling. This generalizes beyond TTS: the same architectural distinction matters for any task where the target trait is high-dimensional in the reference but the model has strong defaults (Llama-backbone in-context-learning beats fixed-decoder bias-correction).

**Refs.** Commit `ead2b34` (Orpheus + Higgs backends). Commit `7b3bef3` (Higgs streaming win). [DECISIONS pending § per-voice backend selection].

---

### Higgs perf on Apple Silicon MPS — streaming output wins; torch.compile + quantization don't

**Context.** Higgs Audio V2 (transformers-based backend) lands at ~2.45-3.0× slower than realtime on M2 Ultra MPS — usable for design-time auditioning but slow for hermes-agent conversational use. Ran a comprehensive perf investigation across the four canonical optimization paths.

**Evidence.** Per-optimization measurements on Mimir's reference, same target text:

| Optimization | Warm RTF | Audio quality | Verdict |
|---|---:|---|---|
| **Baseline (control)** | 2.45× | peak 0.706 RMS 0.1040 (reference) | — |
| `torch.compile(mode="reduce-overhead", backend="inductor")` | 3.19× | audio different (RMS 0.0917, dur 29.6s vs 26.2s) | REJECTED — slower + quality regression |
| `optimum-quanto` int8 weights | 7.32× | audio different (RMS 0.1110) | REJECTED — 3× slower |
| fp16 instead of bf16 | 2.67× | audio different (RMS 0.1273) | REJECTED — slower + Llama overflow risk |
| **Streaming output** (chunks=10/25 frames) | 2.59× | bit-equivalent (1% RMS variance from chunk-boundary rounding) | KEPT — first-audio drops from ~65s → ~3s |

**Mechanism.**

`torch.compile`: Dynamo recompiles the model graph per-layer for `layer_idx == 0` specialization on each call. Partial eager fallback. Net: slower than uncompiled because compilation amortization never gets to pay off, and the partial-fallback path produces subtly different audio (different numeric paths in attention).

`optimum-quanto int8`: int8 has no fast MPS kernel as of torch 2.8 / quanto 0.2. The library's QLinear falls through to dequantize-then-matmul each forward step. Net: 3× slowdown on the bandwidth-bound steps.

`fp16` vs `bf16`: Llama-family attention computations include large magnitude differences inside the softmax exponent. fp16's smaller exponent range causes occasional overflow / underflow, producing slightly different attention weights, propagating to subtly different audio output. bf16 has the larger exponent range Llama was trained for. (Marginal performance difference is incidental.)

Streaming: model.generate() runs in a worker thread; an AsyncStreamer-style queue surfaces audio token frames as they're generated; the main thread decodes every N frames via SNAC and yields PCM chunks. Total wall-time is unchanged (the LLM still has to generate every token), but the first audible PCM is available after ~10 frames (0.4s of audio) instead of waiting for the full sequence. For sentence-pumped UX where the user hears sentence N while N+1 is generating, this is the actual win.

**Honest architectural truth.** Per-step generation is bandwidth-bound at ~100 ms/step on a 5.77B-param Llama-family model. No torch+MPS knob moves the bandwidth limit. Net throughput on this model on this hardware is ~10 tokens/second × ~12.5 audio tokens per audio frame at 25Hz codec rate = ~30 seconds of audio per minute of inference. The streaming output path is the workable solution for conversational UX; total throughput needs MLX to drop substantially.

**Fix.** Streaming output shipped in `src/voice_forge/backends/higgs.py` (commit `7b3bef3`). Compute optimizations all reverted out of the file. MLX port investigation moved up — `mlx-community/higgs-audio-v2-3B-mlx-q6` exists and is reported at 0.33× RTF on M5 Max.

**Generalizable rule.** For LLM-backbone TTS on Apple Silicon MPS via PyTorch: don't waste cycles on torch.compile / int8-quantization / dtype-tuning. They're broken-or-marginal on this stack. Streaming output is the high-leverage win. The total-throughput fix is MLX, not torch optimizations.

**Refs.** Commit `7b3bef3`. Subagent report in `/tmp/higgs-perf/` (measurements + audio A/B). [QUEUED #57 → completed: Higgs MLX backend]. [QUEUED #59 generic mlx_audio backend refactor].

---

### higgs-mlx silence-collapse on distribution-edge voices — bimodal, ~50% rate on Mimir, reproduced

**Context.** higgs-mlx integration completed; agent reported ~50% silence-collapse rate on Mimir's reference at both q6 and q8 quantizations, with bundled `en_woman` always succeeding. User reasonably questioned the claim since the sample they heard sounded fine. Ran an independent 10-call verification sweep before trusting the rate.

**Evidence.** 10 consecutive cold calls of higgs-mlx with Mimir's reference + same target text + fresh random seed each call (`/Users/jefcox/.claude/jobs/1d06b8bd/higgs_mlx_silence_check.py`):

```
ok:      5/10  (50%)
silence: 5/10  (50%)
per-call peak / RMS:
  call 1: peak 0.0801  RMS 0.00056   silence
  call 2: peak 0.6025  RMS 0.03982   ok
  call 3: peak 0.7707  RMS 0.06095   ok
  call 4: peak 0.4748  RMS 0.03071   ok
  call 5: peak 0.0825  RMS 0.00054   silence
  call 6: peak 0.0687  RMS 0.00052   silence
  call 7: peak 0.7053  RMS 0.05886   ok
  call 8: peak 0.0616  RMS 0.00051   silence
  call 9: peak 0.0820  RMS 0.00052   silence
  call 10: peak 0.7341 RMS 0.05638   ok
```

Outcomes are sharply bimodal:
- Good: peak 0.47–0.77, RMS 0.03–0.06 (normal speech levels)
- Silence: peak 0.06–0.08, RMS 0.0005 (sub-noise-floor; perceptually inaudible)

No intermediate-amplitude outputs in 10 calls.

**Mechanism.** A known TTS LM failure mode: the autoregressive decoder picks an audio-token trajectory near the start of generation that decodes through SNAC (or the underlying neural codec) to ~0 amplitude. The trajectory is locally-coherent (the LM thinks it's generating valid speech tokens) but the codec interprets those tokens as silence frames. Once the model is on a silence trajectory it stays on one — there's no recovery mid-utterance.

Why distribution-edge voices specifically: Mimir's reference is at the edge of the model's pretraining distribution (deep male baritone + heavy Nordic-English accent + low-frequency-dominated spectral profile). The audio token sequence corresponding to this voice is in a low-density region of the LM's distribution. Sampling from this region has higher variance — sometimes the next-token distribution gives valid speech, sometimes it gives the silence basin. The 50% rate is the model flipping a near-coin-toss between the two basins at each generation.

The bundled `en_woman` voice is at the center of the pretraining distribution; its audio token sequence is in a high-density region where the next-token distribution is sharply peaked on valid speech. No coin-flip.

Quantization makes this worse but isn't the cause — q6 and q8 both exhibit the failure at roughly the same rate. The full-precision transformers `higgs` backend does NOT exhibit this failure on the same reference. Speculation: full-precision keeps the next-token distribution sharper at the distribution edge, biasing strongly enough toward valid-speech tokens that the silence basin is unreachable.

**Fix (queued).** Server-side retry-on-silence guard in `higgs_mlx.synthesize()`: if `np.max(np.abs(pcm)) < 0.05` after generation, re-call up to N times (default 3). Bounded cost (~8s per retry on a ~25s utterance at 0.33× RTF). Math: 50% per-call → 0.5³ = 12.5% per-utterance after 3 retries → ~6% after a conservative 4 retries. [QUEUED #61.]

Until #61 ships, the transformers `higgs` backend remains the production path for the Asgard fleet. higgs-mlx is fine as default for mainstream-distribution voices.

**What surprised.** Bimodality — I expected a distribution of amplitudes with some near-zero outliers (model occasionally undercommitting). Instead it's binary: full speech OR pure silence, with no in-between in 10 trials. The model isn't "weakly generating"; it's correctly generating one of two distinct trajectories. That makes the retry guard cleaner to implement (no calibration of "how silent is too silent") and makes the math more predictable.

Also surprised that I almost shipped "trust the agent's claim" instead of verifying. The user pushed back on the 50% number ("Mimir sounded fine") and they were right to — what they HEARD was a "good" call I cherry-picked from the agent's saved test output. Without the verification sweep we'd have queued mitigations for a problem of unknown magnitude. Always reproduce a third-party measurement before adopting its conclusion.

**Generalizable rule.** When integrating a quantized model whose deployment scenarios sit at the edge of the training distribution (rare voices, rare languages, rare prompts), measure failure mode rates explicitly before declaring production-ready. Aggregate metrics (warm RTF, peak amplitude on success) hide tail behavior. Run N≥10 calls and report the rate at which the output fails to meet quality criteria, not just the per-call best-case latency. The bimodal failure mode here would NOT have been caught by a single sample-and-listen audit.

**Refs.** Commit `c8f4d90` (higgs-mlx backend). [QUEUED #61 retry-on-silence guard]. Verification script: `~/.claude/jobs/1d06b8bd/higgs_mlx_silence_check.py`.

---

### mlx-community on HuggingFace is the free-port repository for Apple Silicon ML

**Context.** Higgs perf investigation concluded "MLX port" was the necessary next step but estimated as 1-2 weeks of work. Before committing that, checked whether the community had already done it.

**Evidence.** `mlx-community/higgs-audio-v2-3B-mlx-q6` exists, Apache-2, 4.75 GB (6-bit quantized), reported 0.33× RTF on M5 Max. Loadable via the `mlx-audio` PyPI package (Apache-2, maintained by `Blaizzy/mlx-audio`):

```python
from mlx_audio.tts.utils import load_model
model = load_model("mlx-community/higgs-audio-v2-3B-mlx-q6")
```

Same `load_model + generate_audio` API works for every TTS model in mlx-community's catalog. Discovered additional pre-ports relevant to voice-forge: `mlx-community/Qwen3-TTS-12Hz-1.7B-VoiceDesign-bf16` (Qwen team's voice-design + cloning model), Kokoro-MLX variants, Supertonic-3, etc.

**Mechanism.** mlx-community is a HuggingFace organization populated by community contributors who port popular ML models to Apple's MLX framework + apply quantization. They're the analog to TheBloke (LLM quantizations) but specifically for MLX. The `mlx-audio` library is the unified runtime — same API for any TTS model in the catalog.

For voice-forge: ONE generic `mlx_audio` backend module supports ALL their TTS models via a model_path config parameter. New models become a `fleet.yaml` line change.

**Fix.** Higgs MLX integration in flight (task #57 dispatched to subagent — pending completion at session-end). Subsequent refactor to generic `mlx_audio` backend (task #59 queued).

**Generalizable rule.** Before porting an ML model to a new platform, check mlx-community (Apple Silicon), TheBloke (GGUF quantizations), and bartowski (mixed quantizations). The community has often done the work. Saves 1-2 weeks per model when pre-ports are available.

**Refs.** [QUEUED #57 Higgs MLX backend (in flight)] [QUEUED #59 generic mlx_audio backend refactor] [QUEUED #60 Qwen3-TTS-VoiceDesign provider].

---

### Qwen3-TTS-VoiceDesign is the local-open-source Voice Design analog to ElevenLabs

**Context.** voice-forge's `voice_design` module was ElevenLabs-only because no open model offered description-to-voice at production quality. Found Qwen3-TTS-VoiceDesign in mlx-community while investigating Higgs MLX.

**Evidence.** Apache-2, supports BOTH:
- Voice cloning (via `ref_audio` + `ref_text`)
- Voice design (via `instruct` parameter — natural language voice description)

Description language: Chinese OR English. Generated speech language: any supported language (decoupled from description language).

Description cap: **2048 chars** (vs ElevenLabs's silent 500-char persistence cap — 4× more room for detailed phonetic + persona instructions).

API (upstream Qwen Python package — mlx-audio port may or may not expose `generate_voice_design`; needs verification):
```python
wavs, sr = model.generate_voice_design(
    text="...",
    instruct="A native Norwegian speaker speaking English. Female...",
)
```

**Mechanism.** Qwen3-TTS-VoiceDesign uses the Qwen3-1.7B backbone trained on instruction-following voice generation. The `instruct` text conditions the voice characteristics; `text` is the content. Architecturally similar to ElevenLabs Voice Design (description → embedding → audio decoder) but locally runnable + uncapped on description length.

**Implications.** voice-forge's `voice_design` module no longer needs to depend on external API. End-to-end pipeline (design + clone + render) becomes fully local-capable on Apple Silicon. Privacy story improves (no descriptions leaving the host). Audition cost drops to ~$0 (vs ElevenLabs ~$0.05 per 3-preview audition). Description length cap quadruples, enabling much richer phonetic + persona specs.

**Fix.** [QUEUED #60 Add Qwen3-TTS-VoiceDesign as voice_design provider]. Depends on the generic mlx_audio backend landing first (#59) — same `load_model + generate_audio` API.

**Generalizable rule.** When evaluating "do we need to keep paying for service X?" — for voice generation specifically, check the latest open-source releases every ~6 months. The gap between ElevenLabs Voice Design (proprietary) and Qwen3-TTS-VoiceDesign (Apache-2, late 2025) shrank from "no comparable open model" to "open model with superior input constraints" in roughly a year.

**Refs.** [QUEUED #60].

---

### Phonetic-imperative voice descriptions beat categorical accent labels in ElevenLabs Voice Design

**Context.** Mimir voice 1 (formal voice_engineering structured spec: "Heavy Norwegian accent (Bokmål-rooted)") — no Nordic accent in the rendered TTS output despite the explicit accent label. Mimir voice 2 (user's hand-written description with explicit "th drifts toward d", "rolled R sounds", "softened consonants") — Nordic accent comes through clearly.

**Evidence.** Voice Design audition matrices and their renderings, user-verified by ear:

| Voice | Description style | Accent in TTS output |
|---|---|---|
| Mimir v1 (auto-built from structured spec) | "Heavy Norwegian accent (Bokmål-rooted — not Swedish, not Danish)" — categorical labels | No accent — sounds modern American |
| Mimir v2 (auto-built, "Heid-pattern remix") | Same category labels + "the kind a wise elder from the older world would speak" — character labels | No accent |
| Mimir v3 (user-hand-authored) | "rolled R sounds, softened consonants, th drifts toward d" — phonetic imperatives | Nordic accent preserved |
| Freya v1 (user hand-authored) | "Heavy Bokmål-rooted accent... rolled R, softened consonants, th drifts to d" + transliterated sample showing accent ("De truth lies beneath three breaths") | Nordic accent preserved |
| Freya v2 (user hand-authored, tighter) | Same phonetic instructions, no transliterated sample | Nordic accent preserved; Whisper transcribed "the" as "de" — audio physically carries the softening |

The phonetic imperatives are present-tense verbs ("rolled R sounds", "th drifts toward d") describing WHAT the voice does articulately, not abstract WHAT THE VOICE IS labels.

**Mechanism.** ElevenLabs Voice Design's description-conditioning model appears more sensitive to concrete phonetic instructions than to abstract category labels. The mechanism is consistent with how diffusion-text-conditioning models work generally: concrete operations are well-represented in training data ("rolled R" → specific spectral features), while categorical labels ("Norwegian accent") are weaker priors because the training distribution has many "Norwegian" labels mapped to varying phonetic realizations. The imperative form anchors specific behavior; the categorical form invites the model to pick from a distribution.

**Generalizable rule.** For ElevenLabs Voice Design specifically: write descriptions with phonetic imperatives ("softened consonants", "rolled R", "th drifts toward d") not categorical labels ("Heavy X accent"). Imperatives describe operations; labels invite distributional sampling. For local description-to-voice models (Qwen3-TTS-VoiceDesign) the same principle likely holds — verify when integrating.

**Refs.** Commit `7b3bef3` (Freya v1/v2 references). [QUEUED #58 Re-design Eir with phonetic imperatives].

---

### ElevenLabs Voice Design pipeline quirks discovered through Mimir + Freya tuning

A grab-bag of real undocumented behaviors that cost session time to surface. Treat this entry as a compendium for future ElevenLabs work.

**1. `output_format` is a QUERY parameter, not BODY.** The `/v1/text-to-speech/{voice_id}` endpoint silently ignores `output_format` in the body and returns the default `mp3_44100_128`. Code that treats the returned bytes as int16 PCM (because that's what was requested) produces pure noise. Fix in `voice_forge/voice_design/elevenlabs.py` commit `0b51de3`.

**2. Voice Design preview ≠ TTS render.** When ElevenLabs Voice Design persists a voice, the resulting voice_id stores a learned voice embedding. The PREVIEW audio (rendered at design-time with the full description text in the conditioning context) is NOT reproducible via subsequent `/v1/text-to-speech/{voice_id}` calls (which only have the embedding + target text, no description). Description-driven traits like accent strength can be present in the preview but absent in the TTS render. Implication: the preview MP3 stored with the voice IS the highest-fidelity representation available; TTS rendering of the same voice_id will be different (especially weaker on accent).

**3. Description input field caps at 1000 chars but persists ~500.** UI accepts up to 1000-char descriptions but silently truncates to ~500 chars on save. Mimir's stored description is exactly 496 chars — at the cap. Anything past that gets dropped. Voice-forge's `voice_design.prompt_builder` has been updated to cap at 480 chars (with 20-char safety margin). [QUEUED #56 captures the doc update.]

**4. No "remix from reference" endpoint.** Voice Design accepts only `voice_description` (text description). There's no documented endpoint for "design a new voice based on this existing reference WAV + this description-of-changes". The architectures that DO support that (Cartesia Sonic, Resemble AI Voice Adapt) are different vendors.

**5. Voice library accent taxonomy is small.** `accent=norwegian` returns 0 results in `/v1/shared-voices`. All Nordic-leaning voices in the library are labeled `swedish` (most), `german` (some Northern-European-flavored), or unlabeled. The free-text `description` field is more accurate than the `accent` enum for Scandinavian sub-accents.

**6. Voice Library entries are real recorded voice actors.** They get royalties through ElevenLabs's marketplace. Voice Design outputs are synthetic (no specific real person). The ethics distinction: cloning a Library voice = derivative of a contracted-and-paid voice actor; designing a Voice Design voice = synthetic, no underlying person.

**Refs.** Commit `0b51de3` (output_format bugfix + library client). [QUEUED #56 (500-char cap doc + code update)].

---

### Orpheus TTS cloning prompt format is undocumented upstream — community work pending

**Context.** Integrated Orpheus TTS (Canopy Labs, Llama-3 3B finetune, Apache-2) as a sibling LLM-backbone backend to Higgs. Initial cold-test on Mimir's reference produced clean audio that bore no resemblance to the source reference voice — sounded young and English, like a default preset voice.

**Evidence.** User verdict: "output is sounds ok, no accent and totally different 'sound'. Sounds young, not old... timber is off. Orpheus might as well have been a preset voice, it really bears no resemblance to the original."

Canopy Labs's own README lists "Fix voice cloning Colab notebook implementation" as an open checklist item. The PyPI `orpheus-speech` package's `generate_speech()` method accepts only preset voice names (`voice="tara"`, etc.) — no documented reference-audio cloning kwargs. The voice_id parameter takes a finite enum of pre-trained voices.

Our integration manually reconstructed a cloning prompt format from inference + the model's audio-token vocab layout:
```
[START_OF_HUMAN] ref_text [END_TEXT_IDS] ref_audio_tokens [START_OF_HUMAN] target_text [END_TEXT_IDS]
```

This is plausible based on how the model was trained, but **Canopy Labs has not published the actual training-time cloning conditioning format**.

**Mechanism.** Orpheus accepts the "malformed" cloning prompt as a Llama-style token sequence, generates a valid audio output, but the output isn't conditioned on the reference voice — the model falls back to its preset voice distribution because the reference tokens aren't where the model was trained to expect cloning conditioning. Net: cloning is fake; output is a preset voice with no resemblance to the supplied reference.

**Fix.** [QUEUED #54 Orpheus cloning prompt-format investigation]. Two paths: (a) wait for Canopy Labs to ship official cloning + copy their format; (b) experimental prompt-format sweep to find what actually conditions the model on the reference. Given Higgs works and has documented cloning, Orpheus is deprioritized.

**Generalizable rule.** When integrating an open-source ML model, check whether the capability you need is in the **documented + tested** path or the **inferred-from-code** path. The two often diverge — the documented path is what the model was actually trained on; the inferred path can technically run but doesn't activate the capability. Save time by checking the upstream README's open-issue checklist before integrating an unstable capability.

**Refs.** Commit `ead2b34` (Orpheus backend, marked best-effort). [QUEUED #54].

---

### Boson AI's higgs-audio package wheel silently drops two subpackages

**Context.** Integrating Higgs Audio V2 via `boson-multimodal @ git+https://github.com/boson-ai/higgs-audio.git`. Initial cold-test failed with `ModuleNotFoundError: No module named 'boson_multimodal.serve'` despite `boson-multimodal` being installed.

**Evidence.** Inspecting the installed wheel:
```
boson_multimodal/
├── __init__.py
├── constants.py
├── data_collator/
├── data_types.py
├── dataset/
└── model/
    └── higgs_audio/
```
The repo on GitHub has additional subdirectories (`serve/`, `audio_processing/`) that DON'T appear in the installed wheel. Both contain critical modules — `audio_processing/higgs_audio_tokenizer.py` is required for voice cloning.

**Mechanism.** The repo's `setup.py` uses setuptools' default `find_packages()`. `find_packages()` only includes directories that contain an `__init__.py` marker. The `serve/` and `audio_processing/` subdirectories in the upstream repo lack `__init__.py` files (likely intended as namespace packages or just oversight). `find_packages()` silently skips them. The wheel ships only the markered packages. Cloning code that depends on the dropped subpackages fails at import.

**Fix.** Added `src/voice_forge/backends/_higgs_post_install.py` — runs after `uv pip install` for the higgs venv. Detects the missing `audio_processing/` subtree via a smoking-gun file (`higgs_audio_tokenizer.py`), shallow-clones the upstream repo, copies the missing subdirectory tree into the venv's site-packages, synthesizes the `__init__.py` markers the upstream maintainer forgot. Idempotent — re-running is a no-op once the modules become importable.

Wired through a new `_BACKEND_POST_INSTALL` table in `cli.py`. Only `higgs` has an entry today; pattern is available for future backends with similar upstream defects. Commit `ead2b34`.

**What surprised.** That a production-published Python package can be missing modules from its own repository because `find_packages()` is silent about it. No warning, no error, just runtime ImportError when a downstream user touches the missing code. Worth filing upstream — not done yet.

**Generalizable rule.** When integrating a third-party Python package, verify the package layout matches the repo layout: compare `pip show -f <package>` output against the repo's directory tree. Discrepancies are real (silent setuptools drops, dynamic-import workarounds, etc.) and produce confusing ImportError downstream.

**Refs.** Commit `ead2b34`. Sibling LEARNING 2026-05-25 § "Upstream packaging defects in TTS backend ecosystem".

---

### Boson AI's 2026-04-04 config rewrite broke open-source classes — must pin HF revisions

**Context.** Following the higgs-audio packaging workaround, subsequent runs of the Higgs cold-test failed with config-loading errors despite the package now installing correctly.

**Evidence.** Boson AI committed `trfms-support` on 2026-04-04 to both their model + tokenizer HF repos (`bosonai/higgs-audio-v2-generation-3B-base` and `bosonai/higgs-audio-v2-tokenizer`). The commit rewrote the config schema from a flat structure to a transformers-native nested form with `acoustic_model_config` / `semantic_model_config` blocks. The open-source `HiggsAudioModel` and `HiggsAudioTokenizer` Python classes (shipped in the boson-multimodal package) still parse the OLD flat schema and raise on the new one.

**Mechanism.** Classic schema migration without synchronized client updates. The HF Hub repos got the new schema; the GitHub-tracked Python classes didn't. Anonymous downloads of the model from the default `main` branch pull the new schema; the open-source code can't parse it.

**Fix.** Pin both HF revisions to the last pre-rewrite commits:
- Model: `1084018` (pre-trfms-support)
- Tokenizer: `9d4988f` (pre-trfms-support)

These pins live in `src/voice_forge/backends/higgs.py` (the transformers-based backend). Upstream issue #176 tracks the unresolved schema-vs-code divergence — pins lift when they update the classes.

**Generalizable rule.** When integrating a HuggingFace-hosted model from a separately-maintained Python class (model_name_or_path in `from_pretrained`), pin the HF revision rather than tracking `main`. The Python class is versioned in your dependencies (your `pyproject.toml`); the HF repo is rolling. Schema drift on HF can break the Python class at any time. Bake the pin until upstream confirms compatibility.

**Refs.** Commit `ead2b34`. [Boson AI issue #176](https://github.com/boson-ai/higgs-audio/issues/176).

---

### Orpheus cloning is implementable on Apple Silicon without `vllm` — raw transformers + snac is the path

**Context.** Canopy Labs's `orpheus-speech` PyPI package depends on `vllm`. vllm is CUDA-only and doesn't install on Apple Silicon (no MPS support; refuses on arm64 macOS). Initial integration attempt failed at provisioning.

**Evidence.** `uv pip install voice-forge-tts[orpheus]` errored on vllm 0.4.2 → xformers transitive dep → no arm64 macOS wheel + no buildable source.

**Mechanism.** vllm is an inference-optimization library — bumps throughput via PagedAttention + custom CUDA kernels. It's an optimization layer over transformers, not a requirement of the Orpheus model itself. Orpheus is just a Llama-3-3B fine-tune with an audio-extended vocabulary; it can run on bare transformers + the SNAC audio codec.

**Fix.** Rewrote `_OrpheusInProcess` (child-side of the subprocess backend) to skip `orpheus-speech` entirely. Uses raw transformers + snac:
- `AutoModelForCausalLM.from_pretrained()` for the Llama backbone
- `AutoTokenizer.from_pretrained()` for text tokens
- `SNAC.from_pretrained("hubertsiuzdak/snac_24khz")` for audio codec decode
- Manual implementation of the cloning prompt sequence + SNAC interleave layout (audio tokens at offset 128266, 7-tokens-per-frame, 4096-entry codebooks)

`[orpheus]` pyproject extras updated to drop `orpheus-speech` and pull raw deps (`transformers`, `torch`, `snac`, `librosa`, `soundfile`, `accelerate`). Default model switched to `audo/orpheus-3b-0.1-ft` (ungated mirror of HF-gated `canopylabs/orpheus-3b-0.1-ft`). Commit `ead2b34`.

**Generalizable rule.** When an upstream PyPI package fails to install due to CUDA-only optimization deps (vllm, xformers, flash-attn), check whether the optimization is *integral* to the model or *additive*. For most Llama-family models, the optimization layer is additive — the model itself runs fine on raw transformers + MPS. Save 1-2 days of investigation by checking the model architecture before assuming you need to wait for vllm-MPS support.

**Refs.** Commit `ead2b34`.

---

### ref.txt alignment matters for cloning but isn't the dominant factor

**Context.** Eir's `ref.txt` said "5 hours 40", "4 beats", "2 week" — the WAV speaks them as words ("five hours forty", "four beats", "two week"). Suspected the text-audio mismatch was poisoning F5 + Higgs's phoneme alignment of the reference. Hypothesis: fixing the mismatch would restore Eir's accent in cloning.

**Evidence.**

Fixed `personas/asgard/eir-wellness/ref.txt` to spelled-out form matching Whisper-verified WAV content. Re-ran Higgs cloning on Eir with corrected ref.txt. Re-listened.

User verdict: "eir was the only one that still doesn't have nordic accent" — even AFTER the corrected ref.txt. The 4 other voices in the comparison sweep (Mimir, Trjegul, Freya-v1, Freya-v2) all preserved accent; Eir alone did not.

**Mechanism.** ref_text is used by both F5 (for phoneme alignment of the reference's mel) and Higgs (for the ChatML cloning prompt's "user turn" — what the reference SAYS). Mismatched ref_text genuinely degrades cloning quality because the model is told the reference says X but it actually says Y. However, the magnitude of the effect on accent specifically is small relative to the dominant signal — the *intrinsic accent strength of the source recording itself*. Eir's source ElevenLabs voice apparently has weaker accent characteristics in the recorded audio than the other 4 voices, regardless of ref_text quality.

**Fix.** Eir queued for re-design with the phonetic-imperative description pattern that fixed Freya v1/v2 (entry above).

**Generalizable rule.** When ref.txt drifts from ref.wav contents, fix it — it's a real bug. But don't expect fixing ref.txt to recover capabilities that the source voice itself doesn't carry. Reference-driven cloning is upstream-bounded: if accent X isn't acoustically present in the reference, no model can clone it into existence regardless of how cleanly the ref_text is aligned.

**Refs.** Commit `7b3bef3`. [QUEUED #58 Re-design Eir with phonetic imperatives].

---

### Per-voice backend selection is the production fleet pattern for heterogeneous voice profiles

**Context.** Started the session trying to fix all 4 problem voices (Freya / Eir / Trjegul / Mimir) under a single backend (F5). Exhausted F5's tunable space without success. Pivoted to "which backend works for which voice" — turned out F5 works for 5/9, Higgs for 4/9 (with Eir TBD), no single backend works for all.

**Evidence.** Empirical backend × voice matrix:

| Voice | F5 | Higgs |
|---|---|---|
| Beyla | ✓ accent preserved | (not tested) |
| Saga | ✓ accent preserved | (not tested) |
| Bygul | ✓ with cfg+speed tuning | (not tested) |
| Gersemi | ✓ accent preserved | (not tested) |
| Heid | ✓ accent preserved | (not tested) |
| Freya | ✗ strips accent | ✓ via v1/v2 designs |
| Eir | ✗ strips accent | ✗ (queued re-design) |
| Trjegul | ✗ strips accent | ✓ accent preserved |
| Hnoss | ✓ (but source has wrong accent — separate fix) | (not tested) |
| Mimir | ✗ strips accent | ✓ via v3 design |

**Mechanism.** Voices differ in source-recording characteristics (pitch, accent strength, vocal tract size, gender-driven formant profile). Different backend architectures handle these characteristics differently. F5 is good at mid-range female pitch + clear consonant articulation; Higgs is good at heavy non-default accents but slower. No single backend dominates across the voice characteristic space.

**Fix.** voice-forge's existing per-voice backend selection (`saga-comms-f5` vs `saga-comms-higgs` as separate registry entries; production hermes-agent routes to the chosen variant per persona) is the right architectural framing. Per-voice optimization beats whole-fleet optimization. Production fleet config (next commit) records per-voice backend assignments in `personas/asgard/fleet.yaml`.

**Generalizable rule.** When integrating multiple cloning backends + a heterogeneous voice fleet, don't optimize for "one backend that handles all voices." Optimize for "per-voice backend selection." The infrastructure cost (auto-coverage registration + fleet config) is small; the capability gain is large.

**Refs.** Auto-coverage in `src/voice_forge/persona_coverage.py`. Per-voice backend column in `personas/asgard/fleet.yaml` (commit pending).

---



**Context.** [LEARNINGS 2026-05-25 § F5 nfe_step=16](#f5-nfe_step16-is-audibly-equivalent-to-32-on-long-form-narrative-on-mac-studio) found that 16-step F5 synthesis was audibly indistinguishable from 32 on the 11-sentence Saga narrative. At that point we kept 32 as the F5 default and treated 16 as an opt-in "streaming preset" — out of conservatism, not data.

**Evidence.** Today the user explicitly endorsed flipping the default after re-listening to the long-form A/B. The empirical finding from 2026-05-25 stands: no audible difference on real long-form content. The conservatism has nothing left to protect.

**Mechanism.** Diffusion-step count maps roughly-linearly to wall-time per sentence. Halving steps halves the wall-time per synth call. On F5 long-form (~60 s narrative, 11 sentences), this is ~30 s saved vs the 32-step path. WS first-audio drops from ~6 s to ~3 s.

**Fix.** `DEFAULT_NFE_STEP` in `src/voice_forge/backends/f5.py` flipped from 32 → 16. `KNOWN_TUNABLES["nfe_step"]["default"]` matches. The previous `*-fast` voices in the audition registry are deleted (they were nfe_step=16 variants — redundant with the new parent default). DECISIONS 2026-05-26 records the flip with full rationale.

**What surprised.** Nothing new — this is just the consequence of trusting the 2026-05-25 finding. The thing that DID surprise me was how much friction "16 is the streaming preset, 32 is the default" caused in subsequent UX (the demo page picker showed `saga-comms-f5` + `saga-comms-f5-fast` as separate voices, the Lab plan needed to figure out how to collapse them, etc.). Carrying two voices for one persona-backend pairing where one is just "the default plus one knob override" was always going to be confusing. Better to bake the empirical default in.

**Generalizable rule.** When an A/B test resolves a tradeoff cleanly (no audible difference; significant wall-time win), don't ship both options as first-class voices and let users pick. Bake the winner in as the default. Carrying both creates a UX tax forever; collapsing later is a one-time edit.

**Refs.** Commit pending. Supersedes [LEARNINGS 2026-05-25 § F5 nfe_step=16] (still accurate empirically; the conclusion just moved one step forward). [DECISIONS 2026-05-26 § F5 nfe_step default flipped] is the formal lock-in.

---

## 2026-05-25

### WS layer-2 pipelining via asyncio producer/consumer — receive task pulls text while consumer is mid-synth

**Context.** WS layer-2 (`WS /v1/tts/stream`) shipped earlier today (commit `694b0fe`) with a sequential handler — for each WS message, the loop drained any complete sentences from `SentenceBuffer` and `await`ed `_synth_and_send()` before going back to `ws.receive_json()`. That meant: while `synth(s1)` ran in `run_in_threadpool`, the asyncio event loop COULD run other coroutines, but the *same coroutine* that owned receive could not pull new text frames until the current synth fully returned. Sentences arriving DURING synth(s1) sat in the WS recv buffer until the consumer was ready.

**Evidence.** Refactored to producer/consumer with an `asyncio.Queue` between them (commit pending). Producer coroutine = WS receive + SentenceBuffer feed + queue.put. Consumer coroutine = queue.get + `_synth_and_send`. Both `await`ed concurrently via `asyncio.gather`. Producer pushes `None` as the sentinel when the client signals `end: true` and the buffer is flushed; consumer exits cleanly on the sentinel.

Live smoke against the real server (Kokoro backend, 3 sentences in one text frame): producer drained all three sentence boundaries from the single text frame, queued all three, consumer synthesized each in order — all three audio frames + sentence_done events arrived correctly.

Unit tests: 4 new tests covering (a) burst input fanout (5 sentences in 1 frame), (b) trickle-while-synthesizing (multiple text frames interleaved with consumer work), (c) consumer error surfacing (synth raises → producer keeps queueing → error event sent), (d) burst-then-idle (all work queued before end frame arrives).

**Mechanism.** The F5 backend still holds an internal `threading.Lock()` for inference, so the actual synth work remains serial. What pipelining buys us is:

1. **Receive concurrency.** While synth(s1) runs in the threadpool worker, the producer coroutine can pull text frames + emit sentence boundaries to the queue. Sentences 2..N are queued BEFORE synth(s1) returns.
2. **Zero gap between consecutive synths.** As soon as `await ws.send_json("sentence_done", idx)` returns, the consumer hits `queue.get()` and immediately gets sentence 2 (already buffered) — no extra await for the next text frame.

Without pipelining, the gap between sentence_done(N) and synth_start(N+1) was bounded by network RTT + the time for the next sentence to fully arrive. With pipelining, that gap is bounded by `ws.send_json` time alone (microseconds in TestClient; tens of milliseconds on a real network).

**Size of the win in practice.** For a token-by-token LLM upstream feeding ~50 chars/sec into voice-forge, sentences emerge from `SentenceBuffer` faster than F5's `nfe_step=16` can synthesize them. After the first sentence, the consumer is always synth-bound and the producer is always ahead. The end-to-end latency reduction vs the sequential handler is roughly `(N-1) × per-receive-overhead` — a few seconds total on a 10-sentence story over a typical LAN.

**Tradeoffs considered + rejected.**

- **Multiple parallel consumer tasks (true parallel synth).** Doesn't work for in-process backends because of the backend-level `threading.Lock`. PyTorch models on a single device can't truly parallelize multiple inferences anyway. Would only help for subprocess-isolated backends (Piper, Chatterbox) — those each have their own child process, so two concurrent synth requests against different subprocess backends could in principle run in parallel. Skipped for v0.3; the gating concern (preserve sentence-ORDER in the output stream) makes it more work than it's worth for the current single-voice-per-WS use case.
- **Unbounded queue depth.** asyncio.Queue defaults to unbounded. For LLM token rate ~50 chars/sec and synth rate ~1 sentence per few seconds, the queue size is bounded by how much text the LLM produces during synth — at most low single digits. Not worth bounding for v0.3.

**Generalizable rule.** When a coroutine-based handler does receive → process → send in a loop, the process step blocks the receive step if both share a coroutine. Splitting into producer/consumer with an asyncio.Queue is the standard fix; the gather pattern keeps the lifetime of both halves coordinated. The win shows up specifically when "process" can run in the background (via `run_in_threadpool` or `asyncio.create_task`) — in our case, the threadpool offload for sync backend.synthesize calls.

**Refs.** Commit pending. Closes [QUEUED](QUEUED.md) → "Pipelining: synth sentence N+1 while sending sentence N (WS layer-2 perf)" / task #21.

---

### Upstream packaging defects in TTS backend ecosystem — three real ones found by actually trying to install

**Context.** v0.3 shipped a subprocess-isolated backend pattern + concrete backends for Piper / Chatterbox / MeloTTS. The `voice-forge backend install <name>` CLI was supposed to make these one-command installs. Real-world install attempts on macOS arm64 / Python 3.12 revealed three distinct upstream packaging defects.

**Defects found.**

1. **`chatterbox-tts<=0.1.3` → `pkuseg==0.0.25` build failure.** pkuseg is a transitive dep (Chinese segmentation); v0.0.25's setup.py imports numpy but doesn't declare it in build-system.requires. uv refuses to build it with `ModuleNotFoundError: No module named 'numpy'`. **Fix applied:** bump our pin to `chatterbox-tts>=0.1.7` — upstream cleaned this up in 0.1.4+.

2. **`melotts==0.1.1` sdist is broken.** The PyPI tarball's `setup.py` reads a `src/requirements.txt` that doesn't exist in the published archive. **Workaround attempted:** install from upstream git. Required adding `[tool.hatch.metadata] allow-direct-references = true` to our pyproject.toml so hatch would accept a direct-URL dep in our extras.

3. **MeloTTS's transitive transformers==4.27.4 → tokenizers==0.13.3 has no macOS arm64 wheel.** Once the sdist issue was bypassed, fugashi needed `mecab` as a system library (fixed via `brew install mecab`), but then `tokenizers==0.13.3` had no published wheel for the (macOS arm64, Python 3.12) tuple, forcing a Rust toolchain build that uv-with-pip-not-installed can't drive. **MeloTTS does not provision cleanly on arm64 macOS today.**

**Outcome.**

- **Piper**: ✓ provisioned in ~60 s. Clean install.
- **Chatterbox**: ✓ provisioned in ~3-4 min (after the pin bump).
- **MeloTTS**: ✗ blocked on upstream packaging quality. The backend module + pyproject extra ship; `voice-forge backend install melotts` is documented as "requires upstream fixes" in QUEUED.

**Mechanism.** Each defect is a different layer of the Python packaging stack:

- (1) is a *build-deps declaration bug* — the package declares what it imports but not what it needs to *build*. PEP 517 made this fixable per-package (build-system.requires) but old packages don't always declare it correctly.
- (2) is a *publish error* — the sdist tarball was assembled without `src/requirements.txt` despite setup.py reading it.
- (3) is a *wheel coverage gap* — newer Python + newer arch combinations exist where the published wheel matrix doesn't cover, so installs fall back to source builds that need toolchains the user hasn't installed.

These are independent failure modes. The subprocess-pattern doesn't make them go away — it just isolates them from the main voice-forge venv. We discovered them by actually running `voice-forge backend install <name>` for each backend in turn.

**Generalizable rule.** Shipping a wrapper around third-party Python packages means inheriting their packaging defects. "It installs cleanly in our dev env on Python 3.11 Linux" is not "it installs cleanly for users." Probe each backend on each supported (Python, OS, arch) combo BEFORE claiming it's installable, OR document the install failure modes honestly when you can't probe everywhere. Don't claim user-facing one-command install for backends you haven't run the command on.

**Refs.** Commit `05c1727` (chatterbox pin bump + melotts git-URL workaround). QUEUED entry "MeloTTS install blocked on upstream packaging quality (arm64 macOS)".

---

### Subprocess-isolated backends with HTTP-shim IPC give crash isolation + venv hygiene at ~5s cold-start cost

**Context.** Backends like Chatterbox (`torch==2.6.0` + `transformers==5.2.0` hard pins) and Fish Audio S2 Pro can't coexist with voice-forge's main F5/Kokoro/XTTS/Dia venv — installing them breaks every other backend. Piper is GPL-3, which we don't want to risk linking into our Apache-2 main process. The architectural question was: how do we ship these without polluting the main venv?

**Evidence.** Pattern shipped in `src/voice_forge/backends/_subprocess.py` (commit `63b3267`) using HTTP-shim IPC. Each subprocess backend lives in its own venv at `~/.voice-forge/backends/<name>/.venv/`. Parent spawns a child via `voice-forge-backend-shim <name>`; talks to it over localhost HTTP (`POST /synth` returns chunked float32-LE PCM).

10 unit tests validate the lifecycle with a real-but-fake child shim (actual `subprocess.Popen` + `http.server` + `urllib.request` round-trips — not mocks):
- provisioning-missing errors (4 variants — no venv, no state.json, corrupted state, no shim binary)
- happy-path load / health / synthesize / synthesize_stream
- shutdown idempotency
- two-concurrent-backends get different ports

Real-world install verification: Piper + Chatterbox provisioned end-to-end on macOS arm64 today (see the "Upstream packaging defects" LEARNING above for the bumps that took).

Cost characteristics:

- **Cold start**: ~3-5s extra on FIRST call (Popen + the child's `uv pip` venv activate + shim model warmup). Subsequent calls reuse the running child.
- **Per-call IPC overhead**: ~50-100ms. Negligible vs F5 batch synth at 5-15s.
- **Memory**: parent process RSS stays the same regardless of how many subprocess backends are loaded. Each child's RSS is independent.
- **Crash isolation**: child segfault or OOM doesn't kill the parent — only that one backend goes down, surfaced via `health()` returning `child_error`.

**Mechanism.** The HTTP-shim model exploits the fact that voice-forge already has its own REST API. The shim is a tiny FastAPI app (about 100 lines, in `src/voice_forge/subprocess_shim.py`) that imports the backend module, instantiates + loads, and serves `/synth` + `/health` on a localhost-only port. The parent's `SubprocessBackend` class delegates `synthesize_stream()` to a POST against that port.

The same backend module file works in both processes via a sentinel env var: when `VOICE_FORGE_SUBPROCESS_CHILD=1` is set (by the shim), the module registers an in-process implementation that imports the upstream lib directly. Otherwise it registers the SubprocessBackend wrapper. One file, two roles, no duplication.

**Tradeoffs considered + rejected.**

- **(b) stdin/stdout JSON-line IPC.** Simpler and avoids a port + HTTP dependency, BUT streaming PCM over stdin/stdout would require length-prefixed binary frames, which adds protocol complexity.
- **(c) Unix-domain socket + framed binary.** Lowest-overhead option, but only marginal latency win for our use case (~10-20ms vs HTTP's ~50ms), at the cost of platform portability.

HTTP shim wins on time-to-ship + portability, costs us ~50ms per call we'd never notice.

**Generalizable rule.** When a dependency closure can't coexist with the main process, the cheapest correct isolation is a per-extra venv + a localhost HTTP shim that re-exposes the same domain API the parent already speaks. The shim isn't new code — it's a thin re-export. The hardest part is making the same module file work in both processes; an env-var sentinel keeps that ~10 lines of branching.

**Refs.** Commit `63b3267` (subprocess pattern). Piper / Chatterbox modules at commit `9ad0700`. Same pattern would unblock Fish Audio S2 Pro (QUEUED P3) when we revisit that.

---

### Streaming wins are only as good as the weakest link — hermes' Discord adapter is the real bottleneck

**Context.** voice-forge shipped two streaming surfaces (HTTP layer-1 chunked, WS layer-2) that drop F5 first-audio from 60+ s to ~3 s on long-form text. Open question: does that win actually reach the listener at the *consuming* end of the chain (hermes-agent → Discord)? Spoiler: today, no — the adapter buffers everything back to disk before Discord ever sees a frame.

**Evidence.** Audit of the home-lab repo (`infiquetra/home-lab`), specifically:

- `ansible/roles/hermes_neutts_daemon/files/neutts_synth.py` lines 44-90 — hermes-agent's TTS adapter POSTs to `voice-forge/v1/audio/speech` with `stream: false`, then writes the *full* WAV response to a temp file (`out_path.write_bytes(audio_bytes)`).
- `tools/tts_tool.py` (in the agent gateway) — runs `ffmpeg WAV→MP3 -b:a 192k` to a second temp file.
- `discord.py::FFmpegPCMAudio(mp3_path)` then accepts that *file path* and pushes PCM-to-Opus frames to the Discord voice channel UDP gateway.

The final stretch (Opus encoding via libsodium + UDP push) IS real-time and IS streaming-capable. But the input to that stretch is a fully-buffered file on disk — every saved millisecond from voice-forge's WS surface gets erased waiting for the disk write to complete.

**Mechanism.** discord.py's `FFmpegPCMAudio` constructor accepts either a *path* or a *pipe/file-like* via its `pipe=True` flag. Hermes-agent's adapter is wired to the path variant because that's what the original Piper/edge-TTS integration assumed (both produced complete files quickly). When NeuTTS replaced those, the adapter kept the file shape — there was no reason to revisit until a streaming-capable backend showed up downstream. Now that voice-forge has WS-streaming PCM, the path-based shape is the bottleneck.

**Fix (queued).** Two changes in hermes-agent (NOT voice-forge), tracked together in QUEUED 2026-05-25 § "Wire voice-forge streaming into hermes-agent Discord adapter":

1. Replace `FFmpegPCMAudio(mp3_path)` with either `FFmpegPCMAudio(pipe=True, source=<pcm-stream>)` (FFmpeg does PCM→Opus) or a custom `discord.AudioSource` subclass that reads PCM frames straight off the voice-forge WS and yields Opus frames directly (bypasses FFmpeg).
2. Have hermes-agent forward LLM tokens to voice-forge's WS *as they arrive* from the LLM, instead of buffering the full LLM reply before POSTing.

End-to-end win after both changes: first audio in ~3-5 s after the LLM emits its first token, regardless of total reply length. Today it's `LLM_total_time + F5_full_synth + Discord_upload` — typically 60-120 s on long replies.

**What surprised.** I expected "mode (B)" (voice-channel push) to be the streaming-capable path and "mode (A)" (file attachment) to be the file-shaped one. But mode (B) can *also* be file-shaped if the adapter's input is a file path — the Discord-side transport is real-time but the producer side is buffered. Streaming-vs-file is a property of the entire chain, not just the last transport.

**Generalizable rule.** When auditing whether a streaming optimization actually reaches the user, trace the chain end-to-end and look for *every* place where the input shape changes from "stream" to "file" (or vice versa). Each conversion is a buffering point that erases streaming wins upstream of it. The Discord voice gateway is a stream; voice-forge's WS endpoint emits a stream; but the disk-backed adapter between them collapses the chain to "wait for the full thing." A streaming server with a file-based client is just a slow batch server.

**Refs.** QUEUED 2026-05-25 § "Wire voice-forge streaming into hermes-agent Discord adapter" (P2, depends on us not voice-forge). `infiquetra/home-lab` paths cited above. Earlier hermes integration LEARNING 2026-05-24 documents the original NeuTTS → Discord path for context.

---

### F5 nfe_step=16 is audibly equivalent to 32 on long-form narrative (on Mac Studio)

**Context.** F5-TTS is a diffusion model: each synth pass runs N denoising steps over the entire sentence's mel-spectrogram, and each step is one model forward pass. `nfe_step` ("number of function evaluations") is the knob. Upstream default is 32 — picked for batch-quality use. The streaming use case wants every saved millisecond of first-audio latency; halving the steps roughly halves synth wall-time. The open question was *whether* halving costs perceptible quality.

**Evidence.** A/B in the live WS demo (`GET /demo`) against the running voice-forge server with the dev-host audition registry, 2026-05-25:

- `saga-comms-f5` (nfe_step=32, default) vs `saga-comms-f5-fast` (nfe_step=16, same ref WAV + transcript)
- Stress text: Saga's full p3 narrative — 998 chars, 11 sentences, ~60-90s of synthesized audio
- Listener: human (the user) on a VPN'd browser into the Mac Studio host
- Outcome: *"held just as good as 32. I couldn't tell the difference whatsoever."*

Wall-clock effect, same prompt:
- 32-step first audio ≈ 5-6 s; total wall ≈ 60-90 s for the 11-sentence narrative
- 16-step first audio ≈ 2.5-3 s; total wall ≈ 30-45 s

Quality across the 11-sentence sequence held — the concern with aggressive step counts is *diffusion artifacts compounding* on later sentences (each is a fresh sample from random noise, so degradation would manifest as the listener got further in). The listener reported no degradation through sentence 11.

**Mechanism.** Each diffusion step is a full forward pass through F5's transformer. Quality is monotonically-non-decreasing in step count, but the marginal improvement falls off fast — most of the perceptual quality is locked in by step 16-20 on F5's v1 base model. Steps 20-32 buy fine-grain crispness on transients (sharp consonants, breath sounds, sibilants) that's audibly subtle in the casual-listening case. For the streaming use case where the listener is hearing the audio while the LLM is still generating the next sentence, the marginal crispness loss is doubly invisible.

**Fix.** F5 is now the **default backend** (see [DECISIONS 2026-05-25](DECISIONS.md)); `nfe_step=32` is the **quality preset** (batch synth), `nfe_step=16` is the **streaming preset** (HTTP layer-1 + WS layer-2). The per-voice `metadata.sampling.nfe_step` override (wired in commit `a2e045e`) is the surface for picking which preset a voice gets.

**Validation.** Live audition rerun with `saga-comms-f5-fast` + `heid-research-f5-fast` + `hnoss-books-f5-fast` (all cloned from their 32-step originals with `nfe_step=16`). All three held quality through 11 sentences in the live demo. The user's verdict was unprompted — they noticed the speed first ("first audio should land at ~half the time" was the prediction; it did), and *then* listened critically for quality drop and didn't find one.

**What surprised.** The default value (32) in F5's upstream README turned out to be calibrated for *batch quality benchmarks*, not for streaming use cases. Halving it cost no perceptible quality on real prose. Upstream defaults are tuned for the benchmark; user-facing defaults should be tuned for the use case.

**Generalizable rule.** When a diffusion-based backend exposes a step-count knob, the upstream default is almost always tuned for benchmark scores — not for the cadence the audio is consumed at. Probe the actual quality-vs-latency curve at half- and quarter-step counts before locking in defaults. The compute/quality knee is rarely where the README puts it.

**Refs.** Commit `44d8518` (preload long-story default + voice-picker sampling labels). Voice clones at `.audition-registry/{saga,heid,hnoss}-research-f5-fast/`. [DECISIONS 2026-05-25 § F5 default backend](DECISIONS.md). Linked tasks: #22 (this experiment — closed), #21 (WS pipelining — additional win on top), #20 (F5 accent retention tuning).

---

### Sentence-chunked synthesize_stream gives 10× first-audio win on F5 long-form

**Context.** F5-TTS's public API is `infer(ref_file, ref_text, gen_text)` which returns the *complete* waveform; the library exposes no per-token / per-chunk streaming hook. The v0.1 `synthesize_stream` for F5 was batch-with-extra-steps — it just ran `infer()` once and yielded the whole result, so streaming clients got no latency benefit over batch.

**Evidence.** Audition harness `scripts/asgard_audition.py --mode both` against `saga-comms-f5` (commit `282e84c`), with the voice tuned via `voice-forge voice tune saga-comms-f5 --sampling stream_chunk_chars=200`:

| Prompt | Text size | Batch first-audio | Stream first-audio | Speedup |
|---|---|---|---|---|
| p1 "Can you hear me?" | 17 chars | 16.4 s | 3.5 s | 4.7× *(F5 cold-load skew)* |
| p2 self-intro | ~297 chars | 19.6 s | 7.2 s | 2.7× |
| p3 narrative | ~995 chars | 62.8 s | 5.9 s | **10.6×** |

Index: `tests/functional/output/streaming-f5-tuned-20260525T132057Z/index.html`.

**Mechanism.** F5's `infer()` blocks until the *full* utterance is generated, then returns. The chunker (`src/voice_forge/backends/_chunking.py:chunk_text`) splits the input on sentence boundaries; `F5Backend.synthesize_stream()` then calls `infer()` per chunk and yields each PCM buffer as soon as the chunk is done. With 200-char chunks the 995-char p3 splits into ~5 chunks; first chunk completes in ~5.9 s instead of waiting for all 60+ seconds of synth. Each chunk runs through the same per-voice sampling code path as batch, so quality is preserved — content hashes are identical modulo a small per-chunk crossfade delta (≈7 kB on a 1.25 MB synth).

**Caveats baked into the result.**

1. **Quality vs latency tradeoff.** Smaller `stream_chunk_chars` = lower first-audio latency but each chunk has less context for F5's diffusion. The 200-char setting in the demo is aggressive; the backend's `DEFAULT_STREAM_CHUNK_CHARS=1000` favors quality. Tune per voice via metadata sampling block; don't drop the default.

2. **No magic on single-chunk text.** If the whole input fits in one chunk, stream and batch take identical paths. Saga's p2 (297 chars) under the *default* 1000 ceiling collapses to one chunk → first-audio matches batch. That's the "F5 looks unchanged" row in the first audition (`streaming-ab-20260525T131647Z/index.html`).

3. **Cold-load skews short-text rows.** p1 stream looks 4.7× faster than batch but the first synth call also pays F5's lazy-init cost — that confounds the measurement on a single short call.

**Generalizable rule.** When a backend has no native streaming hook but the API can be called on substrings, sentence-chunking the input is the cheapest streaming layer — pure Python, no model changes — and the win scales with text length. Default chunk size should favor quality; expose it as a per-voice tunable so latency-sensitive callers can drop it for that voice without touching the backend default.

**Refs.** Commit `5c144c8` (chunker + per-backend wiring), `282e84c` (audition fleets + deps pin). QUEUED.md → "WebSocket bidirectional streaming (layer 2)" still pending.

---

### Torch 2.9.x + torchcodec 0.13.0 ABI gap silently broke F5 on macOS

**Context.** torchaudio 2.9 removed the soundfile-backed `load()` path and now hard-routes every WAV read through `load_with_torchcodec()`. torchcodec 0.13.0 ships per-FFmpeg-major-version shim libraries that link against `libtorch_cpu`. On torch 2.9.x macOS arm64, `libtorchcodec_core8.dylib` references the symbol `_aoti_torch_aten_subtract_Tensor` which is not exported from the corresponding `libtorch_cpu.dylib`. Every `torchaudio.load()` call dies at dlopen with `Symbol not found`.

**Evidence.** Reproduced today (2026-05-25) at server stderr capture `$CLAUDE_JOB_DIR/srv-stderr.log`:

```
OSError: dlopen(.../torchcodec/libtorchcodec_core8.dylib):
  Symbol not found: _aoti_torch_aten_subtract_Tensor
  Referenced from: libtorchcodec_core8.dylib
  Expected in: torch/lib/libtorch_cpu.dylib
```

Surfaces user-side as `HTTP 500 Internal Server Error` on the very first `POST /v1/audio/speech` for any F5 voice. NeuTTS / Kokoro / Dia / XTTS unaffected — they don't reach into `torchaudio.load()`.

**Mechanism.** torchcodec was built against a torch HEAD that exported `_aoti_torch_aten_subtract_Tensor`; the published torch 2.9.0/2.9.1 wheels don't export it. Result: an undeclared binary contract between two upstream packages that both `f5-tts` (and therefore voice-forge) silently depend on.

**Fix.** `pyproject.toml` F5 extra now pins the last verified-working trio: `torch>=2.8,<2.9`, `torchaudio>=2.8,<2.9`, `torchcodec>=0.7,<0.8`. torchaudio 2.8 still has the soundfile fallback so even the broken torchcodec build wouldn't fire. Commit `282e84c`.

**Validation.** Post-pin, `python -c "import torchaudio, glob; torchaudio.load(glob.glob('.audition-registry/*/ref.wav')[0])"` succeeds; audition harness completes 12/12 + 6/6 rows.

**Generalizable rule.** When a transitive dependency carries unannotated binary contracts to its peers (here: torchcodec ↔ torch's libtorch_cpu), pinning the *triple* (or whatever closure of co-built packages applies) is the only honest fix. The wheel resolver doesn't enforce ABI; it'll happily install incompatible versions whose import-time error message blames everything except the actual contract gap.

**Refs.** [torchcodec compatibility table](https://github.com/pytorch/torchcodec?tab=readme-ov-file#installing-torchcodec). QUEUED.md → P2 "Lift torch 2.8 pin when upstream resolves the symbol gap."

---

### Fish Audio S2 Pro deferred — integration cost too high for predicted-similar quality

**Context.** Seventh backend candidate considered. Fish Audio S2 Pro (fishaudio/fish-speech, 4B params, Dual-AR architecture, decoder-only transformer with SGLang streaming, 80+ languages, inline emotion tags). PRIOR_ART originally marked it Apache-2; verifying 2026-05-25 turned up the actual license: **Fish Audio Research License** — non-commercial only, commercial requires paid license.

**Evidence collected (without running a smoke synth):**

- **License correction:** codebase + model weights both under Fish Audio Research License. Research/non-commercial allowed free; commercial needs `business@fish.audio` paid license + "Built with Fish Audio" attribution. Same license shape as XTTS's CPML; would need an equivalent `FISH_AUDIO_RESEARCH_LICENSE_AGREED=1` env-var gate.

- **Dep hygiene:** exact pins on `torch==2.8.0`, `pydantic==2.9.2`, `einx==0.2.2`, `datasets==2.18.0`, `modelscope==1.17.1`, plus an upper bound `transformers<=4.57.3`. Same "won't coexist with shared venv" pattern as Chatterbox — needs the subprocess-isolated backend pattern (QUEUED P1) to ship.

- **Architecture:** decoder-only transformer (Dual-AR slow 4B + fast 400M). Architecturally in the same family as XTTS + Chatterbox. The empirical pattern across our four decoder-only audits is "no accent preservation on identity cloning" — Fish Audio is predicted to land in the same pitch/gender-adapter bucket as XTTS + Chatterbox, not the identity-preserving bucket where F5 sits alone.

- **Integration cost:** no clean Python API. 3-step CLI pipeline (encode-ref → generate-tokens → decode-audio) OR run their `tools/api_server.py` as a subprocess. Plus ~10 GB model download. Plus `pyaudio` system dep (`brew install portaudio`). Plus the subprocess-isolation prerequisite.

**Decision (deferred).** Stopped short of running the 9-WAV smoke. Queued under QUEUED.md P3 — depends on the subprocess pattern landing AND a use case emerging that justifies the cost. The two scenarios that would re-prioritize:
1. Multilingual personas join the Asgard fleet (Fish Audio has 80+ languages vs F5's English-only).
2. The inline emotion-tag system (`[whisper]`, `[excited]`, 15K+ free-form tags) becomes valuable enough to want fine-grained prosody control. F5 doesn't have an equivalent.

**Mechanism — why we paused.** Six prior auditions established a clear pattern: F5 is the identity-preserving cloning leader; decoder-only TTS backends (NeuTTS, XTTS, Chatterbox) all converge on "good audio, no accent preservation." Spending 2-3 more hours on Fish Audio to likely confirm the same pattern is poor leverage given the open questions still on the v0.2 task board (per-voice tuning to close F5's Heid drift, streaming to hide F5's RTF, the Heid ref-WAV investigation).

**Generalizable rule.** **A backend's architectural family is a strong predictor of its cloning-fidelity bucket once you have 3+ data points within the family.** Don't audit every member to confirm the pattern; predict + queue + only verify when the predicted answer would change a decision.

**Refs.** [Cloning fidelity is a spectrum LEARNING](#cloning-fidelity-is-a-spectrum-not-a-binary--xtts-v2-produces-clean-audio-with-zero-accent-preservation), [Chatterbox audition LEARNING](#chatterbox-turbo-audition--exact-pin-packaging-hostile-to-shared-venvs-cloning-is-pitch-gender-only-heid-p1-works), [QUEUED P3 Fish Audio](QUEUED.md), PRIOR_ART.md license-correction note.

---

### Chatterbox-Turbo audition — exact-pin packaging hostile to shared venvs; cloning is pitch+gender only; Heid p1 works

**Context.** Sixth backend candidate evaluated on the Asgard sister refs. Chatterbox-Turbo from Resemble AI: 350M params, single-step diffusion built on a T3 token model, MIT-licensed wrapper. Promised sub-200ms first-byte latency + emotion control.

**Evidence (audio).** 9 WAVs synthesized in `$CLAUDE_JOB_DIR/chatterbox-audio/` (isolated venv, won't survive job teardown). User listening verdict 2026-05-25:

> "accents are lost on first two smaller versions and total gibberish for the long story. I assume the long story gets better if better configure for the longer text."

| Sister | p1 (short) | p2 (~30s) | p3 (~80s) |
|---|---|---|---|
| Saga | 1.32 s ✓ | 21.92 s ✓ (no accent) | 37.88 s ⚠ truncated → gibberish |
| Heid | **1.12 s ✓** (first non-K/F/X cloning backend to handle her p1!) | 15.24 s ✓ (no accent) | 35.96 s ⚠ truncated |
| Hnoss | 1.20 s ✓ | 18.20 s ✓ (no accent) | 35.00 s ⚠ truncated |

**RTF on M2 Ultra MPS:** 1.13-2.40 warm, 7.17 cold. Format: 24 kHz float32 (WAVE_FORMAT_IEEE_FLOAT — Python stdlib `wave` can't read; soundfile works fine).

**Cloning fidelity classification.** Adds to the XTTS bucket — **pitch + gender adapter, NOT identity-preserving**. F5 remains the only audited backend in the identity-preserving cloning bucket (with the Heid drift exception).

**Evidence (deployment-fitness).** Chatterbox-tts 0.1.7 metadata reveals **five exact-version pins** on heavy ML deps:

```
torch==2.6.0
transformers==5.2.0
diffusers==0.29.0
safetensors==0.5.3
gradio==6.8.0
```

The `transformers==5.2.0` pin alone is incompatible with every other v0.2 backend (which need 4.x). Installing chatterbox into voice-forge's main venv broke F5, Kokoro, XTTS, Dia simultaneously — `transformers` was upgraded to 5.2 which removed APIs the other backends use (`transformers.pytorch_utils.isin_mps_friendly` etc.). Restoring required `uv pip install --reinstall "transformers<5"` to roll back, plus restoring `torch>=2.7,<2.10`.

Plus a runtime crash on import: `perth.PerthImplicitWatermarker()` returned None because `resemble-perth` (Perth watermarker — same library we disabled in NeuTTS for click-artifact reasons) changed its API and chatterbox didn't update. Needed a no-op stub monkeypatch before model load to proceed.

**Mechanism.** Chatterbox's exact-pinned approach is reasonable from their isolation perspective ("we tested with these specific versions; we don't promise anything else works") but pathological for downstream library integration. Combined with the Perth API breakage, two upstream packaging decisions made it impossible to ship Chatterbox as a coexisting v0.2 voice-forge backend.

**Fix (queued).** Subprocess-isolated backend pattern, [P1 QUEUED entry](QUEUED.md). Per-backend venvs let each backend hold whatever exact pins upstream insists on without polluting voice-forge's core venv. Chatterbox integration becomes a follow-up after the pattern lands.

**Generalizable rule.** **Treat exact-version pins on transitive ML deps as a packaging fitness signal**, not just a constraint to resolve. A backend wrapper that pins `transformers==X.Y.Z` exact has chosen "won't work in a shared venv with other transformers users." That decision propagates: voice-forge's `[chatterbox]` extra can't actually express the constraint — every other extra would silently break. The right architectural response isn't "negotiate the version" — it's "isolate that backend." Save the negotiation energy for the upstream PR to relax the pins, if you have time.

Subsidiary rule: **the smoke-in-isolated-venv pattern is the right preflight** for any backend candidate whose pyproject pins worry you. Get the audio data point and the dep diagnostic in one pass; the audio answers "is this worth the integration cost," the deps answer "what does integration cost."

**Refs.** [Chatterbox QUEUED P2](QUEUED.md), [Subprocess pattern QUEUED P1](QUEUED.md), `$CLAUDE_JOB_DIR/run_chatterbox_smoke.py` (ephemeral throwaway script), [cloning-fidelity spectrum LEARNING](#cloning-fidelity-is-a-spectrum-not-a-binary--xtts-v2-produces-clean-audio-with-zero-accent-preservation) (Chatterbox now in the pitch/gender-adapter bucket alongside XTTS).

---

### Heid's reference WAV breaks autoregressive token-sampling — three backends, same failure mode

**Context.** Across five backends (NeuTTS, Kokoro, F5, XTTS, Dia) auditioned against the same 9 Asgard sister refs from `infiquetra/home-lab/.../persona_refs/`, **Heid's `ref.wav` + "Can you hear me?" produces a 0.16-0.20 s near-silent WAV on every autoregressive backend tested**. The other 8 sisters' refs work fine on the same backends with the same prompt.

**Evidence.** Three independent audition runs, three different autoregressive sampling architectures, same failure:

| Backend | Architecture | Heid p1 duration | Other sisters' p1 duration |
|---|---|---|---|
| NeuTTS Air Q8 | llama-cpp autoregressive token sampler | 0.20 s | 0.94 - 2.72 s |
| Dia-1.6B | HF Transformers `generate()` autoregressive | 0.19 s | 1.08 - 1.16 s |
| (NeuTTS reproduction) | (same as above) | 0.16-0.20 s (multiple runs) | (same) |

Backends that DO handle Heid p1 correctly:

| Backend | Architecture | Heid p1 duration |
|---|---|---|
| Kokoro 82M | encoder-decoder (no autoregressive token sampling for speech) | 1.60 s |
| F5-TTS | flow-matching diffusion | 1.18 s |
| XTTS-v2 | decoder-with-CFG (not pure autoregressive) | 1.43 s |

The split is clean: **autoregressive samplers fail; non-autoregressive don't**.

**Mechanism (hypothesis).** Autoregressive TTS samples speech tokens one at a time and terminates when the model emits a stop / end-of-speech token. Something about Heid's `ref.wav` — when encoded into the model's conditioning latent — pushes the autoregressive decoder toward emitting a stop token almost immediately. This isn't a "the model can't handle short utterances" issue (Saga p1 works on the same backends with similar text). It's specific to Heid's ref.

Candidate root causes inside `heid-research/ref.wav`:
- **Trailing silence or low-energy tail** that the model encodes as "speaker is done" — encourages early stop.
- **Specific acoustic features** (breathiness, low-frequency content, post-recording compression artifacts) that map to internal "this is an ending" embedding region.
- **Length above the model's training-distribution** for refs — but other sister refs are similar duration, so probably not this.
- **Speech-pace artifact** — Heid speaks slowly in her ref, the model "learns" she's leaving long pauses, then emits stop after one short word.

**Fix (queued).** Two follow-ups:
1. **Inspect and re-trim `heid-research/ref.wav`.** Compare its waveform / spectrogram to Saga's (which works). Look for trailing silence, weird endings, or low-energy artifacts. `voice_lab.trim_to_sentence_boundary` may need to be re-run with stricter parameters for this ref.
2. **Add a heuristic in cloning backends** to detect this failure mode (synth returned < 0.5 s of audio) and **retry with stochastic re-seeding**. This is generic across autoregressive backends.

Heid also produced wrong-gender output on Dia (user verdict 2026-05-25: "even wrong gender in heid's case") — additional evidence the ref is problematic. F5 also drifted on Heid (held Saga + Hnoss, lost Heid).

**Generalizable rule.** **When the same ref breaks multiple backends with the same architectural family, the ref is the bug, not the backend.** Empirical pattern recognition only emerges from auditioning the same data across many backends — exactly what the audition harness is for. Single-backend audits would have attributed each failure to "this backend has issues with short text" or similar single-cause story.

Subsidiary rule: **the audition harness has high leverage for finding cross-backend invariants** that you can't see when looking at one backend in isolation. Keep auditioning.

**Refs.** `infiquetra/home-lab/ansible/roles/hermes_neutts_daemon/files/persona_refs/heid-research/ref.wav` (the suspect), audition runs `tests/functional/output/v0.2-mac-studio-20260525T025950Z/` (initial NeuTTS reproduction), `v0.2-triple-20260525T045249Z/` (NeuTTS + F5 + Kokoro), `v0.2-dia-20260525T055909Z/` (Dia), [F5 voice-fidelity variance](#f5-voice-fidelity-variance--heid-drifted-saga--hnoss-held-on-identical-reference-audio).

---

### Dia-1.6B `max_new_tokens=3072` is too small for long-form — truncates at ~18-21 s, not at the theoretical 35.7 s

**Context.** Dia's upstream README recommends `max_new_tokens=3072` as the default. At 86 audio tokens per second, that's a theoretical ceiling of 35.7 s of generated audio. The v0.2 audition's p3 stories are ~80 s of expected audio (200 words at 150 wpm) — way above the cap. We expected truncation around 36 s.

**Evidence.** Audition `v0.2-dia-20260525T055909Z`: all three sisters' p3 stories truncated **at ~18-21 s, not 36 s**. p2 (~30 s expected) came out at 11-16 s — also short. The prompts that fit well within the cap (p1 ~2 s) generated cleanly.

**Mechanism.** Dia's prompt format for cloning is `[S1] {ref_text} [S1] {gen_text}`. The ref transcript (typically 15-25 tokens for the Asgard sisters' ~10 s refs) plus the generation text + special tokens all consume the `max_new_tokens` budget. So the effective budget for the actual output text is `3072 - ref_tokens - overhead` ≈ 1500-2000 tokens ≈ 17-23 s of audio. Matches the empirical truncation.

**Fix (workaround).** For long-form Dia synth: pass `max_new_tokens=8192` (≈95 s) or higher via the backend config. This is the **first concrete use case for the per-voice tunable params system** (QUEUED P2). Voices with long-form requirements would set `sampling.max_new_tokens=8192` in their `metadata.json`; voices with short-form (notifications, system prompts) keep the default.

**What surprised.** That the cap kicked in below the theoretical token math suggests something other than tokens/s rate is at play — possibly Dia's special tokens (speaker tags, stop tokens) account for a non-trivial overhead per chunk. The empirical 18-21 s budget should be the working assumption when sizing `max_new_tokens` for Dia, not the theoretical 35.7 s.

**Generalizable rule.** **A backend's "default" generation params are often tuned for the backend's authors' use case, not yours.** Always plan to override them on a per-voice basis once a real audit surfaces their behavior. The per-voice tunable params system isn't a nice-to-have — it's the difference between "this backend works for our content" and "this backend only works for content matching the upstream demo."

**Refs.** `src/voice_forge/backends/dia.py:DEFAULT_MAX_NEW_TOKENS`, [QUEUED § Per-voice tunable sampling params](QUEUED.md), audition results `v0.2-dia-20260525T055909Z`.

---

### Cloning fidelity is a spectrum, not a binary — XTTS-v2 produces clean audio with zero accent preservation

**Context.** Triple- + quad-backend audition runs against the 9 Asgard sister refs surfaced an unexpected per-backend behavior that PRIOR_ART.md's "voice cloning" cell didn't capture. Each backend successfully cloned in the literal sense (took a ref WAV, returned audio that wasn't the default voice), but the *degree* of cloning varies dramatically.

**Evidence.** User-supplied ear verdicts across two audition runs on identical Asgard refs + identical text:

| Backend | Sister identity preserved? | User verdict |
|---|---|---|
| NeuTTS Air | ✓ all 9 (production baseline) | "sounds like the Mac mini" |
| F5-TTS | ✓ Saga + Hnoss; ❌ Heid drifted | "Held saga and hnoss's, but lost heid's" |
| XTTS-v2 | ❌ none preserved | "All sounded good, no accent on a single one. But no stutter or poor quality" |
| Chatterbox-Turbo | ❌ none preserved | "accents are lost on first two smaller versions and total gibberish for the long story" |

XTTS's failure isn't quality-related — the audio is clean, intelligible, no stutter or artifacts. It's that the cloning step produces a voice that's *adjacent* to the ref (similar gender, similar broad pitch range) but **doesn't preserve accent, fine-grained timbre, or persona character**. The Asgard sisters' refs are American English with distinct individual character; XTTS's outputs are generic-clean American female.

**Mechanism (hypotheses).**
- **Model age + training data.** XTTS-v2 was released early-2024; trained on a moderate-sized multilingual speaker pool. Speaker embedding capacity may be insufficient to capture fine accent / personal-timbre signal beyond gender + broad pitch.
- **Encoder architecture.** XTTS uses a fixed-size speaker embedding extracted via its encoder; F5 (and NeuTTS) condition on a longer reference window with more degrees of freedom.
- **Multilingual trade-off.** XTTS supports 17 languages from one model; the speaker encoder is shared across all of them, which may dilute per-accent specificity.

**Practical implication for voice-forge.** The Asgard use case = sister voices need to sound like specific personas. XTTS is **not viable** for that even though its audio quality is the cleanest of the four backends tested. F5 wins this comparison despite its slower pace + occasional drift (Heid).

For use cases where "any reasonable female voice" is enough (generic narration, system notifications, etc.), XTTS is great. For persona TTS, it doesn't deliver.

**Generalizable rule.** **A "voice cloning backend" label is too coarse.** Better classification:
- **Identity-preserving clone**: NeuTTS (autoregressive prompted), F5 (diffusion conditioned on long ref), Dia (presumed).
- **Pitch-and-gender adapter**: XTTS-v2 — produces a voice in the right gender + pitch range as the ref, but loses identity.
- **No-clone preset**: Kokoro, Kitten — preset embeddings, no ref-audio input.

When adding a new backend to BACKENDS.md, note **which point on this spectrum** it lands at, ideally validated by an audition pass before committing. The Audition harness is the right tool — ear judgment is the validator.

**Update 2026-05-25 after Chatterbox audition:** Chatterbox-Turbo joins the pitch/gender-adapter bucket (no accent preservation on Saga + Hnoss, gibberish on long-form p3 at default config). With four backends audited, the spectrum split is **F5 alone in the identity-preserving bucket**, **XTTS + Chatterbox in pitch/gender adapter**, **Kokoro in preset-only**. F5's lead is widening — neither newer cloning-capable backend matched its identity preservation.

**Decision (provisional).** F5 remains the leading NeuTTS-replacement candidate. XTTS stays in the registry as a "clean-voice-for-non-persona" backend option. Once per-voice tunables ship (QUEUED P2), revisit F5 with Heid-specific tuning to close that one remaining drift.

**Refs.** Audition runs `tests/functional/output/v0.2-triple-20260525T045249Z/` (F5 vs NeuTTS vs Kokoro) and `tests/functional/output/v0.2-xtts-20260525T053201Z/` (XTTS), `src/voice_forge/backends/xtts.py`, [F5 voice-fidelity variance entry](#f5-voice-fidelity-variance--heid-drifted-saga--hnoss-held-on-identical-reference-audio).

---

### XTTS-v2 license is split — coqui-tts library is MPL-2 but the model weights are CPML (non-commercial)

**Context.** When wiring up the XTTS-v2 backend, the first synth attempt blocked on a stdin prompt:

    > "I have purchased a commercial license from Coqui: licensing@coqui.ai"
    > "Otherwise, I agree to the terms of the non-commercial CPML: https://coqui.ai/cpml" - [y/n]

PRIOR_ART.md had the XTTS-v2 row as MPL-2 — that was wrong. PRIOR_ART was tracking the *library* license; the model weights are a separate licensing question entirely.

**Evidence.** Two distinct license artifacts:
- **`coqui-tts` PyPI package**: MPL-2.0 (file-level copyleft — safe to depend on for an Apache-2 project, can't directly include the source). Confirmed in `pyproject.toml` metadata.
- **`tts_models/multilingual/multi-dataset/xtts_v2` model weights**: [Coqui Public Model License (CPML)](https://coqui.ai/cpml) — **non-commercial use only** unless the user has purchased a commercial license from Coqui (licensing@coqui.ai). The runtime auto-prompt is Coqui's compliance gate.

**Mechanism.** "Library license" and "model weights license" are independent. The library is open-source MPL-2 freely; the weights it loads at runtime are governed by a separate license you accept by downloading them from HuggingFace. This split is increasingly common in TTS ecosystem — XTTS-v2, the late-Coqui-era models, certain Microsoft VibeVoice variants all have similar splits.

**Fix.** `XTTSBackend.load()` runs a pre-flight check for `COQUI_TOS_AGREED=1` in the process environment. Missing → `RuntimeError` with the CPML URL and a pointer to `licensing@coqui.ai` for commercial use. voice-forge does **not** accept the license on the user's behalf — they have to opt in explicitly. Documented in `src/voice_forge/backends/xtts.py:load`, `docs/BACKENDS.md` XTTS section, and the `[xtts]` optional-extra comment in `pyproject.toml`.

**What surprised.** That the library + weights license split was invisible until first synth. There's no static metadata that says "this PyPI package will at runtime download CPML-licensed weights." A user reading just the pyproject classifiers would believe XTTS is MPL-2 end-to-end. We're now careful in BACKENDS.md to label the library and model licenses separately.

**Generalizable rule.** **When documenting a backend's license in BACKENDS.md, always list BOTH the wrapper-library license AND the model-weights license separately.** PRIOR_ART.md needs a refresh pass to do this for every entry. Added as a doc-hygiene QUEUED item.

**Refs.** `src/voice_forge/backends/xtts.py:load`, `docs/BACKENDS.md` XTTS section, `pyproject.toml` `[xtts]` extra (with the `transformers<5` pin doc'd inline), [QUEUED.md PyPI publishing](QUEUED.md).

---

### XTTS-v2 MPS is 5× slower than CPU on M2 Ultra — Coqui codebase falls back per-op

**Context.** When picking the device for the XTTS audition, naive intuition said "1.8 GB model, M2 Ultra has 128 GB unified memory, MPS should win." That turned out to be wrong by 5×.

**Evidence.** Identical synth (16-char text against saga-comms ref), back-to-back on the same process:

| Device | Cold load | Warm synth | Audio out | RTF |
|---|---|---|---|---|
| CPU | 51.19 s (incl. ~1.5 GB weight download) | 2.03 s | 1.29 s | 1.57 |
| MPS | 18.39 s (warm, model already downloaded) | **10.56 s** | 1.29 s | **8.18** |

MPS synth is 5× slower than CPU. Switching back to CPU is the correct device pick for XTTS on Apple Silicon.

**Mechanism.** Coqui's TTS codebase has documented patchy MPS support — many operations fall back to CPU mid-graph because the MPS implementation lacks them. Each fallback requires a tensor round-trip between GPU and CPU memory (technically cheap on unified-memory hardware, but each crossing incurs torch's tensor-marshalling cost + kernel-launch overhead). The cumulative per-op churn dominates the synth wall-clock; the "GPU compute" never gets to amortize because most ops aren't running on the GPU anyway.

**Fix.** `XTTSBackend.load()` default `device=None` → CPU. Docstring explicitly recommends CPU on Apple Silicon and warns that MPS is currently 5× slower. If upstream coqui-tts gets the MPS path fixed (e.g., by porting more ops to MPS native), re-bench.

**What surprised.** This is **the opposite** of the F5 result on the same machine: F5 happily uses MPS (RTF 1.05) because diffusion models like F5 are uniform-tensor-op-heavy and MPS coverage is good for those. The Apple Silicon device-pick heuristic is now: **per-backend benchmark, don't extrapolate from "model size + unified memory."** Codebase op coverage matters more than model architecture.

**Generalizable rule.** **Device picks are codebase-dependent, not just model-dependent.** Two ~1-2 GB PyTorch models on the same Apple Silicon hardware can have inverse MPS/CPU performance just because their library implementations have different op-coverage profiles. Always bench both before defaulting.

**Refs.** `src/voice_forge/backends/xtts.py` (CPU default + docstring), [F5 resource profile LEARNING](#f5-tts-on-apple-silicon--rtf-105-with-default-nfe_step32-ram-comparable-to-kokoro-no-30-second-cliff) (MPS works for F5), `docs/BACKENDS.md` XTTS section.

---

### F5-TTS on Apple Silicon — RTF ~1.05 with default `nfe_step=32`, RAM comparable to Kokoro, no 30-second cliff

**Context.** Adding F5-TTS (`SWivid/F5-TTS`, MIT wrapper, Apache-2 model weights) as the cloning-capable backend candidate to replace NeuTTS, after NeuTTS's documented 30s-narrative cliff and reproducible heid-research short-utterance collapse made it clear we needed a better cloning path.

**Evidence.** Controlled bench on Mac Studio M2 Ultra (128 GB unified memory), same shape as the prior Kokoro/NeuTTS bench: single server process, identical 274-char input for the warm synth, RSS sampled via `ps -o rss=`. F5 with default `device=None` (autodetect → MPS), default `nfe_step=32`:

| Metric | F5-TTS | NeuTTS Q8 (prior bench) | Kokoro 82M (prior bench) |
|---|---|---|---|
| Disk (model cache) | 314 MB initial + 1.5 GB on first synth | 1.9 GB | 314 MB |
| Cold-load latency | 37.6 s (incl. weight download) | 26.1 s | 3.6 s |
| Resident RSS after load | 1,468 MB | 5,682 MB | 1,421 MB |
| Synth time (274 chars) | 25.0 s | 16.6 s | 1.1 s |
| Audio duration produced | 23.83 s | 20.74 s | 17.00 s |
| RTF | 1.05 | 0.80 | 0.07 |

**Triple-backend audition (9 sisters × 3 backends × 3 prompts; same Asgard refs from `infiquetra/home-lab/.../persona_refs/`):**

- 26/27 rows synthesized (one HTTP 500 on `hnoss-books` NeuTTS p1 — see separate LEARNING below).
- F5 produced **all 9 rows cleanly**, including p3 stories at 71-86 s long-form. No truncation, no degradation past the 30-s mark, no the-second-half-rots audible decay that NeuTTS shows.
- F5 reads at a noticeably slower pace than NeuTTS / Kokoro on identical text (Saga p3: 86.5 s F5 vs 59.0 s NeuTTS vs 58.4 s Kokoro — same words). Default `speed=1.0` is conservative.

**Mechanism.** F5 is a flow-matching diffusion model — generates audio in N iterative denoising steps (`nfe_step` controls how many). Each step is a forward pass through a ~335M-parameter transformer. The per-step cost is what dominates wall-clock; lowering `nfe_step` to 16 should approximately halve synth time with quality cost (untested in this LEARNING, queued for follow-up). MPS on M2 Ultra handles the diffusion well — the model is big enough that GPU kernel-launch overhead amortizes (unlike NeuTTS Q8, where MPS underperforms CPU).

**What surprised.**
- **F5 RAM is comparable to Kokoro**, not bigger. I had expected diffusion to be heavier than encoder-decoder + GAN vocoder; it's actually similar (~1.5 GB resident). The model file is bigger on disk (1.5 GB vs Kokoro's 314 MB) but the runtime working set is the same order.
- **RTF 1.05 means slightly slower than realtime, not 5-10× slower.** PRIOR_ART.md had described F5 as "requires GPU for usable RTF (CPU is too slow for conversational use)." That was an NVIDIA-CUDA mental model; on Apple Silicon MPS, the M2 Ultra is fast enough for the use case to be viable.
- **No 30-second cliff.** F5's diffusion architecture doesn't autoregressively drift the way NeuTTS's llama-cpp does. Long utterances stay coherent end-to-end.

**Generalizable rule.** **Trust the model architecture, not the platform's marketing.** "Needs GPU" claims in upstream READMEs usually assume CUDA; Apple Silicon MPS with unified memory often satisfies the same constraint. Always measure rather than defer to the upstream's deployment defaults.

**Decision.** F5 is the cloning-backend candidate for retiring NeuTTS, pending more audio review at scale and per-voice tuning ([QUEUED § Per-voice tunable params](QUEUED.md)).

**Refs.** `src/voice_forge/backends/f5.py`, `tests/functional/output/v0.2-triple-20260525T045249Z/` (the audition WAVs), [Kokoro/NeuTTS bench](#kokoro-vs-neutts-resource-profile--kokoro-rtf-14-and-14-gb-ram-neutts-resident-memory-was-higher-than-estimated) for the parallel measurement template.

---

### F5 voice-fidelity variance — Heid drifted, Saga + Hnoss held, on identical reference audio

**Context.** The triple-backend audition fed the same Asgard sister ref WAVs (`infiquetra/home-lab/.../persona_refs/<sister>/ref.wav` + matching `ref.txt`) to both NeuTTS and F5. NeuTTS's clones were the production baseline — they sound recognizably like each sister. F5's clones were the new variable.

**Evidence.** Audition rows in `tests/functional/output/v0.2-triple-20260525T045249Z/`. User-supplied verdict 2026-05-25: "Held saga and hnoss's, but lost heid's." Subjectively, Saga's F5 clone preserves dry-witted timbre; Hnoss's preserves the careful-librarian cadence; **Heid's drifts — no longer recognizable as Heid**.

**Mechanism.** Unverified. Plausible causes:
- F5's reference-audio encoder might be sensitive to specific acoustic features (pitch range, breathiness, room acoustics) that one of the refs differs on. Heid's ref might have characteristics that fall outside the encoder's well-trained region.
- Default `cfg_strength=2` may need per-voice tuning.
- F5's diffusion sampling is stochastic — fixed `seed=None` means different runs produce different outputs. The "lost Heid" might be one bad seed; reproducibility check at fixed seed would tell.

**Fix (queued).** No fix yet. Tracked under [QUEUED § Per-voice tunable params](QUEUED.md) — the per-voice metadata.json `sampling` block is exactly where seed / `cfg_strength` / `nfe_step` overrides would live. Two specific follow-ups before retiring NeuTTS on Heid:
1. Reproducibility check: synth Heid p3 with fixed `seed=42` three times. If they're identical → drift is deterministic; if not → it's stochastic per-run.
2. CFG sweep: try `cfg_strength` in [1.5, 2.0, 2.5, 3.0]. Higher CFG should pull harder toward the reference.

Also worth investigating: Heid's `ref.wav` itself. If the recording has unique room reverberation or compression characteristics, re-trimming with `voice_lab.trim_to_sentence_boundary` and/or denoising might fix it.

**Generalizable rule.** **Cross-backend voice fidelity is per-voice, not per-backend.** "Backend X clones well" is the wrong question — the right one is "backend X clones reference Y well." Voice-by-voice empirical check needed before claiming a backend is production-ready for a fleet.

**Refs.** [F5-TTS resource profile](#f5-tts-on-apple-silicon--rtf-105-with-default-nfe_step32-ram-comparable-to-kokoro-no-30-second-cliff) (the bench LEARNING above), QUEUED.md (per-voice tunable params).

---

### NeuTTS HTTP 500 on hnoss-books p1 during triple-backend audition — first hard failure, root cause TBD

**Context.** During the 27-row triple-backend audition (`v0.2-triple-20260525T045249Z`), the `hnoss-books/p1_hear_me` row returned HTTP 500 from the voice-forge server. This is **the first time we've seen NeuTTS hard-fail** — prior failures were the documented short-utterance collapse (`heid-research p1` → 0.16-0.20 s) which still returns valid (just very short) audio. A 500 is qualitatively different.

**Evidence.** Audition log line: `hnoss-books/p1_hear_me: synthesizing ... -> FAIL: HTTP 500: Internal Server Error`. All other 26 rows succeeded. Same NeuTTS backend was working fine for saga-comms + heid-research p2/p3 in the same run.

**Mechanism (hypotheses, unverified).**
1. **Memory pressure from loading three backends in one process.** Combined resident ~8.5 GB. M2 Ultra has 128 GB so pressure is unlikely at OS level, but PyTorch's CUDA/MPS allocator might have its own constraints.
2. **PyTorch state contamination.** F5 and Kokoro both load PyTorch models; NeuTTS does NOT use PyTorch directly but does use llama-cpp-python. Shared MPS / Metal state between F5 and the NeuTTS llama-cpp path is theoretically possible if both reach for Metal context.
3. **A NeuTTS-side flake.** llama-cpp-python autoregressive sampling can occasionally produce edge-case input combinations that crash internally.
4. **A voice-forge-side bug.** The lock + thread state in `NeuTTSBackend._lock` interacts poorly with concurrent requests if the server isn't actually serializing them. (FastAPI-asyncio + threading.Lock combo is worth a closer look.)

**Fix.** Not yet. Move to QUEUED if reproducible; for now logged here as evidence-toward-NeuTTS-retirement. If we ship the F5-based replacement first, the 500 becomes a non-issue.

**Next step if we want to investigate:** rerun the same triple-backend audition with verbose server logging; capture stderr. Currently the audition harness sends server stderr to PIPE without consuming it.

**Generalizable rule.** **Combined-backend processes can surface failure modes that single-backend processes don't.** Future LEARNING + bench protocol: when adding a new backend, run an audition with **all** prior backends loaded too — the integration risk lives in the interaction, not the individual.

**Refs.** Audition output `tests/functional/output/v0.2-triple-20260525T045249Z/` (note the missing `hnoss-books_p1_hear_me.wav`), `scripts/asgard_audition.py:_synthesize` (where the HTTP error is caught).

---

## 2026-05-24

### Kokoro vs NeuTTS resource profile — Kokoro RTF ~14× and ~1.4 GB RAM, NeuTTS resident memory was higher than estimated

**Context.** After validating the pluggable abstraction by running the audition harness against both backends, the user asked for the resource impact of adding Kokoro. Needed actual measurements (not estimates) so deployment-host decisions (Pi vs Mac mini vs Mac Studio) could be made honestly.

**Evidence.** Controlled bench in one server process: cold-load each backend serially, identical 274-char input for the warm synth, RSS sampled via `ps -o rss=`. Mac Studio M-series, Python 3.12, voice-forge worktree venv:

| Metric | NeuTTS Q8 GGUF | Kokoro 82M | Delta |
|---|---|---|---|
| Disk (HF model cache) | 1.9 GB (neucodec 1.1G + q8-gguf 766M) | 314 MB | +314 MB |
| Disk (net-new pip deps when NeuTTS already installed) | — | 36 MB (kokoro 72KB + misaki 15MB + spacy 21MB) | +36 MB |
| Cold-load latency | 26.1s | 3.6s | — |
| Resident RSS after load | 5,682 MB | +1,421 MB on top of NeuTTS = 7,103 MB combined | +1.4 GB |
| Synth time (274 chars, ~17-21s audio out) | 16.6s | 1.1s | — |
| Real-time factor (RTF) | 0.80 | **0.07** (~14× realtime) | — |

Reference run that produced the audition WAVs was 4m02s wall-clock for 18 rows (9 NeuTTS + 9 Kokoro); the controlled bench above isolates per-backend cost more cleanly.

**Mechanism.**
- NeuTTS Q8 disk-to-resident expansion is large because llama-cpp-python materializes the GGUF into a memory-mapped buffer, then layers in KV cache + neucodec activations. The 766 MB on-disk model expands to ~5.6 GB working set during inference.
- Kokoro's resident cost (~1.4 GB) is the 82M-parameter PyTorch model + transformers tokenizer + misaki spaCy pipeline + activations.
- Kokoro's RTF dominance comes from being a small encoder-decoder model with no token-by-token LLM-style decoding; NeuTTS does autoregressive token generation via llama-cpp which is inherently slower per-token.

**What surprised.**
- NeuTTS resident memory was ~3× higher than the mental model. I had been describing it as "~2-3 GB resident." The real number is **5.6 GB**. The Q8 disk size (766 MB) is misleading — llama-cpp's KV cache + neucodec push it well past the model file's size.
- NeuTTS RTF is 0.80 on Apple Silicon CPU, not 1.0. I'd been describing it as "~RTF 1" loosely. It's faster than realtime — just not by much.
- Kokoro RTF 0.07 is ~14×, not the "7-10×" I'd initially eyeballed from the audition wall-clock. The audition was inflated by NeuTTS rows running concurrently in the same process timer.

**Fix / decision.** Updated `docs/BACKENDS.md` with the table above + a deployment-host implication matrix (Pi 4 / Pi 5 / Mac mini base / Mac mini Pro / Mac Studio). Future LEARNINGS for additional backends should follow the same bench shape (same server, same input, isolated RSS samples) so the numbers compose into a reference table.

**Generalizable rule.** **Trust on-disk model size as a lower bound, not a working-memory estimate.** For inference engines that build KV caches / activations / vocoder buffers on top of the loaded weights, resident memory can be 5-10× the file size. Always measure resident-after-warmup, not at-load.

A second rule: **measure RTF in a single-backend process.** A combined-backend run's wall-clock divided by total audio understates the fast backend's RTF and overstates the slow one's. Isolate.

**Refs.** `docs/BACKENDS.md` (the reference table this LEARNING informs), [Kokoro library pick](#kokoro-library-pick--kokoro-apache-2--pytorch-over-kokoro-onnx-mit--onnx-trading-python-313-support) (license choice that landed us on the PyTorch wrapper rather than the smaller ONNX path), `pyproject.toml` (kokoro/neutts optional extras showing the install layering).

---

### Kokoro library pick — `kokoro` (Apache-2 / PyTorch) over `kokoro-onnx` (MIT / ONNX), trading Python 3.13 support

**Context.** v0.2 adds a second backend to prove the pluggable abstraction. Two candidate libraries both publish to PyPI under the same model family (Kokoro-82M, Apache-2 weights from `hexgrad/Kokoro-82M`):
- `kokoro` (PyPI), from `hexgrad/kokoro` — Apache-2 wrapper, PyTorch + transformers + misaki[en]
- `kokoro-onnx` (PyPI), from `thewh1teagle/kokoro-onnx` — MIT wrapper, onnxruntime, ~10× smaller install

**Evidence.** PyPI metadata pulled 2026-05-24 via `curl https://pypi.org/pypi/{kokoro,kokoro-onnx}/json | jq .info`:
- `kokoro==0.9.4`: `requires-python: >=3.10,<3.13`, License: Apache 2.0
- `kokoro-onnx==0.5.0`: `requires-python: >=3.10,<3.14`, License: MIT
- Upstream `hexgrad/kokoro` `pyproject.toml` HEAD declares `<3.14` but no release has been cut with the relaxed constraint.

**Mechanism.** The published `kokoro==0.9.4` wheel was built against an older pyproject; pip respects the wheel-declared `requires-python` regardless of repo HEAD. Until upstream cuts a release with `<3.14`, installing `kokoro` from PyPI blocks Python 3.13.

**Fix.** Picked `kokoro` for v0.2 (commit `<PR-3 commit>`). License-aligned with voice-forge (Apache-2 to Apache-2); PyTorch backend gets MPS support on Apple Silicon for free; the lib exposes `KPipeline` as a native generator giving us streaming for free. Dropped Python 3.13 from CI matrix (`["3.11", "3.12"]`) and from `pyproject.toml` classifiers. Re-add 3.13 the moment upstream publishes a release with `<3.14`.

**What surprised.** That PyPI-served metadata and upstream-repo-HEAD pyproject can disagree about Python version support for the same version number. The wheel metadata is the authoritative constraint pip uses; the repo HEAD is aspirational until the next release.

**Generalizable rule.** When picking between two libraries that wrap the same model, check the **wheel-declared** `requires-python` from PyPI's JSON API, not the repo's current `pyproject.toml`. The wheel is what pip honors.

**Refs.** `pyproject.toml` (kokoro optional extra + classifier list), `docs/engineering-journal/QUEUED.md` (re-add 3.13 in v0.2.x), `src/voice_forge/backends/kokoro.py` (the implementation).

---

### Kokoro voice-mixing tensor blending — parser ships, consumption deferred

**Context.** Kokoro's README (`hexgrad/kokoro`) shows `voice=` accepts a `torch.Tensor` directly, with an example loading a per-voice `.pt` file via `torch.load('path/to/voice.pt', weights_only=True)`. voice-forge inherits the `name(weight)+name(weight)` mix syntax from Kokoro-FastAPI's prior art, and v0.2 wanted to ship full blending.

**Evidence.** Upstream README at github.com/hexgrad/kokoro and the [PRIOR_ART.md Kokoro-FastAPI section](../PRIOR_ART.md) show the syntax. `KPipeline.voices` / `pipeline.model.voices` / the exact HF-cache file path for per-voice tensors is **not documented** in the upstream README we surveyed.

**Mechanism.** Without upstream guidance on accessing the per-voice embedding tensors via the public API, naively loading them from the HF cache would couple voice-forge to undocumented filesystem layout — brittle.

**Fix (queued).** PR 3 (commit `<PR-3 commit>`) ships:
- The parser (`src/voice_forge/backends/_mixing.py`), fully tested.
- `KokoroBackend._resolve_voice` calls the parser; for single-voice specs it passes the bare name; for multi-voice mixes it logs a `voice-mix degradation` warning and picks the highest-weight name as a fallback.

Tensor-blending is queued as a v0.2.x item — once we have a real impl running on the Mac Studio we can probe `pipeline.voices` interactively and either pin the API or file an upstream issue requesting one.

**Generalizable rule.** When a feature has a clean syntax surface but the consumption path is uncertain, **ship the surface anyway** behind a documented degradation. Users get the right CLI / API shape; the implementation upgrade is a non-breaking follow-up.

**Refs.** `src/voice_forge/backends/kokoro.py:_resolve_voice`, `src/voice_forge/backends/_mixing.py`, [PRIOR_ART.md § Kokoro-FastAPI](../PRIOR_ART.md).

---

### Q4 / Q8 / BF16 × CPU / MPS on Apple M-series — Q4+CPU+Accelerate is fastest, BF16 is 4x slower

**Context.** Pre-investigation assumption was that Metal/MPS would be faster than CPU on Apple Silicon for the NeuTTS model. Initial measurements on a Mac mini M4 Pro (24GB unified memory) disproved this for the ~500MB-1.5GB NeuTTS model class.

**Evidence.** Latency measurements across 3 model variants × 2 devices × 3 text lengths (33 / 237 / 1214 chars):

| Combo | 33ch | 237ch (~14s audio) | 1214ch | Model load |
|---|---|---|---|---|
| BF16 full + MPS | 6.34s | 4.96s | 13.39s | 70s |
| Q8 GGUF + MPS | 1.92s | 4.46s (RTF 0.32) | 2.27s | 8.45s |
| Q4 GGUF + MPS | 1.92s | 5.19s (RTF 0.30) | 2.29s | 4.06s |
| **Q4 GGUF + CPU** ⭐ | **1.36s** | **3.91s (RTF 0.27)** | 1.81s | **2.79s** |

Later A/B with BF16 batch on long content (1991-char Saga story):
- Q8 batch: 164s audio in 57s synth (RTF 0.35)
- BF16 batch: 130s audio in 230s synth (RTF 1.76) — 4× slower, fewer clicks but same content-degradation

**Mechanism.** Two things:
1. **MPS doesn't help small models.** Metal kernel-launch overhead exceeds GPU benefit for ~500MB-1.5GB models on M-series. Apple Accelerate (CPU + BLAS) wins for this size class. Confirmed empirically; the official NeuTTS install docs corroborate (recommend `-DGGML_METAL=OFF` for M-series even though Metal IS available).
2. **BF16 quantization quality vs speed tradeoff.** Half the click rate but 4× slower synth on CPU. Same long-content degradation as Q8.

**Decision.** `NeuTTSBackend` defaults to `device="cpu"` + `model="neuphonic/neutts-air-q8-gguf"`. BF16 is opt-in via config. (DECISIONS § "Q8 GGUF default for NeuTTS backend".)

**Generalizable rule.** Measure CPU vs GPU on actual hardware before assuming GPU is faster. For small models (<2GB), CPU+BLAS often wins on Apple Silicon. Don't trust general "GPU is faster" intuition for small models.

### Perth watermarker is a per-chunk artifact source — disabling cuts streaming clicks 15×

**Context.** NeuTTS streaming output had audible "cracks" that batch output didn't. After ruling out FIFO/WAV-header issues, the suspect became NeuTTS's `_infer_stream_ggml` per-chunk processing. Each yielded chunk passes through `self.watermarker.apply_watermark(recon, sample_rate=24_000)` if `tts.watermarker` is not None. The Perth implicit watermarker injects an imperceptible random-noise signature per chunk — but the noise PATTERNS differ between chunks, so the boundary samples don't align cleanly, producing audible clicks at chunk transitions.

**Evidence.** A/B same-text Saga synth with streaming:
- Watermarker ON (default): max_delta=27,597, jumps>10000=1,167, jumps>20000=27
- Watermarker OFF (`tts.watermarker = None` after construction): max_delta=12,858, jumps>10000=**79**, jumps>20000=**0**
- ~15× reduction in big-jump count; eliminated extreme jumps entirely

**Mechanism.** `_infer_stream_ggml` decodes chunks via `_linear_overlap_add(audio_cache, stride=streaming_stride_samples)` which DOES crossfade chunk boundaries. But the WATERMARKER is applied INSIDE the per-chunk path, BEFORE the overlap-add. Each chunk has different watermark noise. The crossfade smooths the audio shape but can't smooth the per-chunk-different watermark noise → discontinuity.

**Fix.** In `NeuTTSBackend.load()`: `if tts.watermarker is not None: tts.watermarker = None`. The watermark is an AI-fingerprint feature we don't need for our deployment.

**Generalizable rule.** When a model library has an OPTIONAL post-processing step (watermarking, denoising, etc.) and you're using STREAMING output, suspect that step at chunk boundaries. Test with the step disabled before tuning anything else. "Imperceptible noise" injected per-chunk is NOT imperceptible at chunk seams.

**Refs.** `src/voice_forge/backends/neutts.py` has the watermarker-disable in `load()`. Discovery story in the spin-out narrative.

### NeuTTS streaming drops 15-21% of audio content vs batch on long inputs

**Context.** NeuTTS `infer_stream()` produces noticeably less audio than batch mode (`infer()`) for identical text. Measured during voice-forge's `synthesize_stream` validation.

**Evidence.** Same 1991-char text via NeuTTSBackend:
- Streaming (no penalty patch on stream path): 130.5s audio
- Batch: 164.5s audio
- Streaming + Llama.__call__ wrap injecting repeat_penalty=1.05 into stream path: 142.2s audio
- BF16 batch (full precision PyTorch): 130.9s audio, 4× slower synth (RTF 1.76)

Stream-mode (Q8) is 21% short of batch (Q8). Patching the stream path's sampling recovers some content (12s of 34s gap) but doesn't fully close it.

**Mechanism (partial).** Half-explained: NeuTTS's `_infer_stream_ggml` calls `self.backbone(prompt, max_tokens=..., temperature=1.0, top_k=50, stop=[...], stream=True)` WITHOUT passing `repeat_penalty`, while `_infer_ggml` (batch) sets it. Our `Llama.__call__` wrap injects the missing kwarg → recovers some content. The remaining 14% gap is somewhere in the stream-path's chunk-stitching / overlap-add / early-stop logic.

**Fix.** Default to batch mode in voice-forge client. Streaming opt-in via env var. QUEUED separately for deeper investigation (would require instrumenting `_infer_stream_ggml` to log every emitted token + the `<|SPEECH_GENERATION_END|>` stop-token detection).

**Generalizable rule.** When a library exposes both batch + streaming inference, A/B them on long-content tests BEFORE relying on streaming for latency benefits. Streaming-mode in ML libraries sometimes has subtle behavior differences (sampling, stop conditions, early termination) that don't surface on short inputs but bite on long ones.

**Refs.** `src/voice_forge/backends/neutts.py:synthesize_stream` has the WARNING docstring. QUEUED entry "NeuTTS streaming content-loss investigation". DECISIONS § "Batch mode default in voice-forge client".

### NeuTTS-Air degrades into incoherent phonemes on >30s sustained narrative

**Context.** Long narrative responses (1991+ chars producing 100+ seconds of audio) produced incoherent phonemes mid-narrative across all NeuTTS-Air variants (Q4, Q8, BF16) and across batch and streaming modes. Surfaced when testing long story-telling responses.

**Evidence.** Three same-text WAVs auditioned by user: streaming pre-patch (130s), streaming patched (142s), batch (164s). All three exhibited "speaking in tongues" — clean speech at start, drifts into incoherent phoneme sequences around the 30-second mark.

**Mechanism.** NeuTTS-Air is a ~500M-parameter speech-token language model trained on short TTS utterances (typical 5-15s training samples). For 100+ seconds of sustained narrative across multiple independent inference chunks (each chunk being a fresh inference call with the same ref priming), the speech-token output degrades beyond the training distribution. Per-chunk re-priming gives ENTRY tokens for each chunk but doesn't reset the within-chunk drift — and each chunk still has to coherently sustain 20-30s of speech in one inference call, which is at the edge of what the model can do.

**Fix.** None at the NeuTTS-Air level. The model is **right for short utterances**, **wrong for long narrative**. The fix path is a different backend optimized for long-form: F5-TTS, XTTS-v2, or specifically VibeVoice (Microsoft research model designed for up to 90-minute coherent multi-speaker audio). All tracked in ROADMAP.md.

**Generalizable rule.** When a generative model produces clean output on short inputs but degrades on long ones, check the model card / paper for training-sample length distribution. "Beyond training distribution" is a real and predictable failure mode that no amount of sampling-knob tuning fixes. The fix is a different model trained for the longer regime.

**Refs.** ROADMAP.md tracks backends that address this. QUEUED entry "NeuTTS long-narrative quality". This is the PRIMARY motivation for the pluggable backend architecture.

### FFmpeg default MP3 bitrate for mono is 32 kbps — not 128k as commonly assumed

**Context.** voice-forge's `server.py` does WAV → MP3 conversion via ffmpeg when `response_format=mp3`. Initial implementation called `ffmpeg -i <wav> -f mp3 <output>` with no `-b:a` flag. Result was unexpectedly low-quality MP3 at 32 kbps (audible artifacts; near-AM-radio quality).

**Evidence.** `ffprobe` on output: `Duration: 00:01:14.56, bitrate: 32 kb/s`. After adding `-b:a 192k`: clean MP3 at 192 kbps, click rate dropped substantially.

**Mechanism.** When no `-b:a` flag is passed to ffmpeg, the libmp3lame encoder picks a "default" bitrate based on input characteristics. For mono 24kHz audio, the default lands at 32 kbps. This is documented but not surfaced unless you ffprobe the output. Most users assume 128 kbps default because that's what stereo CD-quality input picks.

**Fix.** voice-forge's `server._wav_to_format()` passes `-b:a 192k` for mp3 + `-b:a 96k` for opus. Always explicit.

**Generalizable rule.** Always explicit-set audio bitrate when programmatic ffmpeg conversion is involved. Defaults are content-dependent and can produce surprisingly low quality for mono / low-sample-rate inputs. `ffprobe <file>` early in debugging cycles to verify the encoded bitrate matches expectations.

**Refs.** `src/voice_forge/server.py:_wav_to_format` is where the explicit bitrate lives. Downstream consumers (like the infiquetra/home-lab hermes-agent deployment) maintain a parallel patch to hermes-agent's own ffmpeg invocation for the same reason.

### Whisper STT auto-detect mis-flags Norwegian-accented English as Swedish/Norwegian

**Context.** voice-forge's `voice_lab/whisper.py` (for ref transcription during voice registration) forces `language="en"` rather than letting Whisper auto-detect. The choice was empirical: auto-detect mis-flagged accented English as Swedish or Norwegian on ~30% of trial samples.

**Evidence.** During home-lab Asgard voice setup (which uses Norwegian-accented voices designed via ElevenLabs Voice Lab), Whisper auto-detect repeatedly identified accented English speech as Swedish (`sv`) or Norwegian (`no`). Once flipped, decoder used non-English token priors, producing garbage transcripts.

**Mechanism.** Whisper's language ID head runs on a short audio prefix before the main decode. Accented English at low confidence can flip to a phonetically-similar language. Once flipped, the decoder uses different token priors. Forcing `language="en"` bypasses the ID step entirely (~200ms saved per transcription) AND eliminates the misflag.

**Fix.** `voice_lab.whisper.transcribe()` and `voice_lab.whisper.segments()` both accept `language=` parameter, defaulting to `"en"`. Callers can override for non-English voices.

**Generalizable rule.** For known-language audio (any deployment where you control or know the spoken language), explicitly set `language=<code>` in Whisper. Auto-detect is an extra failure mode that only earns its keep for unknown-language audio.

**Refs.** `src/voice_forge/voice_lab/whisper.py` callers default `language="en"`. Override per-call via the function parameter or per-voice via metadata.

### Shim-swap cutover pattern (parallel-port + thin integration layer)

**Context.** voice-forge's first production deploy in `infiquetra/home-lab` had to migrate a fleet of running services (4 Discord voice bots) from a pre-existing ad-hoc NeuTTS daemon to voice-forge with zero user-visible downtime + instant rollback. This is the general pattern for "replace a daemon" deployments and applies to ANY voice-forge integration where you're replacing existing TTS.

**The pattern.**

```
Pre-cutover state:
  hermes-agent ──subprocess──> neutts_synth.py (Unix-socket-client)
                                   │
                                   └──> ad-hoc daemon @ /tmp/neutts.sock

During cutover:
  voice-forge installed on a DIFFERENT launchd label (ai.hermes.voice-forge)
  voice-forge serves on a DIFFERENT port (TCP :9876)
  Old daemon untouched, still on /tmp/neutts.sock
  Both services running concurrently — zero conflict.

Cutover step (the only action that flips traffic):
  cp neutts_synth.py neutts_synth.py.socket-client-backup    # backup
  cp HTTP-shim-version neutts_synth.py                       # swap
  (no daemon restart, no gateway restart needed —
   subprocess pattern means next TTS call uses new shim)

Rollback:
  cp neutts_synth.py.socket-client-backup neutts_synth.py    # one command
  (traffic flows back to ad-hoc daemon, still running)
```

**Why this works.** The integration layer (`neutts_synth.py` — a ~150-line subprocess script that hermes-agent runs per TTS call) is THIN. Replacing it = one `cp`. Rollback = inverse `cp`. The DAEMONS themselves never get touched during cutover — they coexist on different transports + launchd labels.

**Generalizable rule.** When integrating a new service that's invoked via a THIN integration layer (a subprocess script, a function call adapter, a config-driven import), replacing the integration layer is much smaller blast radius than replacing the service itself. Cutover = `cp` (or symlink swap); rollback = inverse `cp`. Validate the new service standalone first; flip the integration last. The "test without Discord" CLI surface is what makes the standalone validation possible.

**Refs.** First validated in `infiquetra/home-lab` Phase G cutover 2026-05-24 (see that repo's `narratives/2026-05-24-voice-forge-phase-g-cutover.md`). DECISIONS § "Spin TTS out of home-lab" for the context.

### First production cutover (2026-05-24 same day as v0.1.0 ship) — design validated

**Context.** v0.1.0 shipped at ~17:30 (home-lab time) on 2026-05-24. By ~20:00 the same day, all 4 NeuTTS sisters in the infiquetra/home-lab Asgard fleet were running on voice-forge in production. The end-to-end loop (uv pip install from git tag → register voices → run as launchd service → hermes-agent integration via HTTP-shim) all worked first try after one pip-syntax fix.

**Evidence.** Home-lab repo PRs #134-138 + voice-forge v0.1.0 tag. Cutover narrative at `infiquetra/home-lab/docs/engineering-journal/narratives/2026-05-24-voice-forge-phase-g-cutover.md`.

**What worked.**
- Backend Protocol with VoiceRef union handled the NeuTTS case cleanly. No abstraction-mismatch surprises.
- FastAPI /v1/audio/speech endpoint integrated with OpenAI-SDK-style clients (the home-lab HTTP-shim uses urllib.request POST).
- FS-backed registry was trivial to seed from existing daemon's persona ref files (shell copy + metadata.json template).
- CLI `voice-forge synth` direct-synth mode was the validation interface — text→WAV without HTTP, without Discord. This was the design principle made literal.

**What needed fixing during deploy.**
- pip 26 rejected `#egg=name[extras]` URL fragment syntax — fixed in home-lab PR #137 (the ansible role's install command). Voice-forge itself is fine; the fix is in the consumer's deployment.
- Hermes-agent's `PROVIDER_MAX_TEXT_LENGTH[neutts]=2000` cap was too conservative for voice-forge's chunker capability. Fixed in home-lab PR #138 (consumer-side hermes-agent patch).

**Generalizable rule.** Design principles ("test without Discord", "pluggable backend Protocol", "CLI surface for direct testing") earn their cost during integration. The first downstream consumer is when you find out whether the abstractions match reality. Spending the planning time upfront (Phase B prior-art research, Phase C scaffolding, devil's-advocate verification pass) paid off — no architectural surprises in the cutover.

**Refs.** v0.1.0 release notes. Home-lab Phase G cutover narrative. Plan at `~/.claude/plans/i-am-under-the-merry-finch.md` (the user's plans directory, not committed here).
