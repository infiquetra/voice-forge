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

## 2026-05-25

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

