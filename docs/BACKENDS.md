# Backends — voice-forge's pluggable TTS surface

This is the reference for the TTS backends that voice-forge knows how to drive. It exists so a new contributor can answer:

1. "Which backend should I use for my use case?"
2. "What does it cost to add this backend to my deployment host?"
3. "How does this backend differ from the others architecturally?"

For the abstraction itself — the `TTSBackend` Protocol, the `VoiceRef` union dataclass, the registry, the dispatch path — see [`docs/ARCHITECTURE.md`](ARCHITECTURE.md). For the broader landscape of self-hosted TTS engines (Coqui, F5, XTTS, Dia, Kitten, etc.) see [`docs/PRIOR_ART.md`](PRIOR_ART.md).

## At a glance — what ships in v0.2

**F5-TTS is the default backend** as of [DECISIONS 2026-05-25](engineering-journal/DECISIONS.md). `nfe_step=32` is the quality preset (batch); `nfe_step=16` is the streaming preset — audibly indistinguishable on the 11-sentence stress test ([LEARNINGS](engineering-journal/LEARNINGS.md)).

| Backend | License (lib / weights) | Voice paradigm | Cloning fidelity (M-Silicon ear-test) | Cold load | Resident RSS | RTF (M2 Ultra) | Status |
|---|---|---|---|---|---|---|---|
| **F5-TTS** ⭐ default | MIT / Apache-2 | Ref-WAV cloning (diffusion) | **Identity-preserving** (Saga + Hnoss + Heid all held with `nfe_step=16`) | ~37 s (+1.5 GB DL) | ~1.5 GB | 1.05 (MPS, nfe_step=32) / ~0.5 (nfe_step=16) | shipped v0.2 — **default** |
| **Kokoro 82M** | Apache-2 / Apache-2 | Preset (~54 embeddings) | N/A (no cloning) | ~3.6 s | ~1.4 GB | 0.07 (CPU) | shipped v0.2 — preset-voice fallback |
| **NeuTTS Air (Q8 GGUF)** | Apache-2 / Apache-2 | Ref-WAV cloning (autoregressive) | **Identity-preserving** (short utterances only — 30 s cliff) | ~26 s | ~5.6 GB | 0.80 (CPU) | shipped v0.1 — kept for short-form cloning |
| **XTTS-v2** | MPL-2 / **CPML (non-commercial)** | Ref-WAV cloning + multilingual | **Pitch/gender only** — no accent preservation | ~51 s (+1.8 GB DL) | ~2.0 GB | 1.57 (CPU; MPS 5× slower) | shipped v0.2 — license-gated |
| **Dia-1.6B** | Apache-2 / Apache-2 | Ref-WAV cloning + multi-speaker tags ([S1]/[S2]) | **Mixed — Heid wrong-gender; default cap truncates long-form to ~18-21s** | ~120 s (+3 GB DL) | ~3 GB est | ~3-5 (MPS, 1.6B params) | shipped v0.2 (with caveats) |

**Read the cloning-fidelity column.** "Voice cloning" is a spectrum, not a binary. Three of these backends accept a ref WAV; only NeuTTS + F5 preserve speaker identity in the audible-to-an-ear-test sense. XTTS-v2 produces clean audio that adapts pitch + gender to the ref but loses accent and persona character — see [LEARNINGS § Cloning fidelity is a spectrum](engineering-journal/LEARNINGS.md#cloning-fidelity-is-a-spectrum-not-a-binary--xtts-v2-produces-clean-audio-with-zero-accent-preservation).

**Read the license column carefully.** Library and model-weights licenses are independent. XTTS-v2's library wrapper is MPL-2 (safe to depend on) but its model weights are CPML — **non-commercial unless you've purchased a commercial license from Coqui**. voice-forge can't accept the CPML on the user's behalf; `XTTSBackend.load()` requires `COQUI_TOS_AGREED=1` in the env. See [LEARNINGS § XTTS-v2 license is split](engineering-journal/LEARNINGS.md#xtts-v2-license-is-split--coqui-tts-library-is-mpl-2-but-the-model-weights-are-cpml-non-commercial).

NeuTTS + Kokoro run pure-CPU on Apple Silicon (and for NeuTTS Q8, MPS is actually *slower* — see [LEARNINGS § "Q4/Q8/BF16 × CPU/MPS"](engineering-journal/LEARNINGS.md#q4--q8--bf16--cpu--mps-on-apple-m-series--q4cpuaccelerate-is-fastest-bf16-is-4x-slower)). F5 picks MPS by default on Apple Silicon and benefits — diffusion models are large enough that GPU kernel-launch overhead amortizes.

Numbers above come from a controlled bench documented at [LEARNINGS § "Kokoro vs NeuTTS resource profile"](engineering-journal/LEARNINGS.md#kokoro-vs-neutts-resource-profile--kokoro-rtf-14-and-14-gb-ram-neutts-resident-memory-was-higher-than-estimated). Re-run the bench locally and post-deploy when you want to ground numbers in your hardware.

## Picking a backend

Decision tree, in order of how voice-forge users have asked it so far:

**"I want a specific person's voice."**
→ NeuTTS Air. Drop a 3-15s ref WAV + matching transcript into `~/.voice-forge/voices/<id>/`, call `voice-forge synth <id> "..."`. Cloning is on by default. Quality is "Medium" by voice-forge's internal ranking — fine for agent chatter, audible NeuTTS character on long-form (see the 30-second cliff caveat below).

**"I want clean high-quality TTS, voice identity doesn't matter."**
→ Kokoro. Pick from `af_bella`, `af_nicole`, `af_heart`, `am_adam`, `bf_emma`, etc. (full list in the [Kokoro section below](#kokoro-82m)). No cloning — these are pre-trained voice embeddings shipped with the model.

**"I need ≥30-second utterances that stay coherent."**
→ Kokoro for any-clean-voice. F5-TTS for long-form **WITH cloning** — verified clean at 71-86 s on the Asgard sister refs in the v0.2 audition. NeuTTS rots noticeably past ~30 s ([LEARNINGS § NeuTTS streaming content loss](engineering-journal/LEARNINGS.md#neutts-streaming-content-loss--streaming-emits-15-21-less-audio-than-batch-for-identical-input-on-long-content) and the empirical 41-69 s rows from the v0.2 audition show audible drift in the back half).

**"I'm running on constrained hardware (Pi 5, low-end Mac)."**
→ Kokoro only. NeuTTS's ~5.6 GB resident set is too heavy for most 8 GB hosts. F5 at ~1.5 GB resident is borderline — depends on what else runs on the host.

**"I'm running on a real workstation (16+ GB Mac, 32+ GB server)."**
→ All three. Same registry, same server; `backend` per voice in metadata.json routes to the right engine.

## Deployment-host capacity

Combined-load = all three backends loaded into the same process (~8.5 GB resident).

| Host (RAM)                    | All three | NeuTTS + F5 | Kokoro + F5 | Kokoro only | F5 only | NeuTTS only |
|---|---|---|---|---|---|---|
| Raspberry Pi 4 (4 GB)         | ❌ | ❌ | ❌ | ⚠ (~1.5 GB) | ❌ | ❌ |
| Raspberry Pi 5 (8 GB)         | ❌ | ❌ | ⚠ tight | ✓ | ⚠ tight | ⚠ tight |
| Mac mini M1/M2 base (8 GB)    | ❌ | ❌ | ⚠ tight | ✓ | ⚠ tight | ⚠ swap |
| Mac mini M2/M4 base (16 GB)   | ⚠ tight | ✓ | ✓ | ✓ | ✓ | ✓ |
| **Mac mini M4 Pro (24 GB)**   | ✓ comfortable | ✓ | ✓ | ✓ | ✓ | ✓ (Asgard prod host) |
| **Mac Studio M2 Ultra (128 GB)** | ✓ trivial | ✓ | ✓ | ✓ | ✓ | ✓ (dev host) |

Numbers measured 2026-05-24 / 2026-05-25 on a Mac Studio M2 Ultra. F5 cold-load + warm RSS: ~1.5 GB; combined with NeuTTS + Kokoro: ~8.5 GB total resident. Idle voice-forge server ~67 MB.

## NeuTTS Air

- **License:** Apache 2.0
- **Repo:** [`Neuphonic/neutts`](https://github.com/neuphonic/neutts)
- **Default model:** `neuphonic/neutts-air-q8-gguf` (Q8 quantized GGUF, ~766 MB on disk)
- **Inference engine:** [`llama-cpp-python`](https://github.com/abetlen/llama-cpp-python) (autoregressive token generation) + `neucodec` (codec → PCM)
- **Voice paradigm:** Ref-WAV cloning. Each voice is registered with a 3-15 s reference WAV and a matching transcript (`ref.txt`). Whisper transcribes if no transcript is provided.
- **Sample rate:** 24 kHz mono float32 PCM
- **Streaming:** Supported via `synthesize_stream` (chunked HTTP); native, but with a documented ~15-21% content-loss vs batch ([LEARNINGS § NeuTTS streaming](engineering-journal/LEARNINGS.md)) — callers should default to batch.

### NeuTTS per-voice tunables

NeuTTS's `repeat_penalty` is currently applied at **load time** via a monkey-patch of `Llama.__call__` (the only way to inject it into NeuTTS's autoregressive sampling without forking the upstream). Per-voice override would require thread-local state through the patch — out of scope for v0.2 since NeuTTS is being retired. Document for future: queued under per-voice tuning if/when we revive NeuTTS investment.

### NeuTTS quirks worth knowing

- **30-second narrative coherence cliff.** Long utterances (>30 s) drift, lose words, or produce repeated tokens. The v0.2 audition produced 41-69 s rows that demonstrated this audibly. Not a hard cutoff — Freya's clone went 35.9 s cleanly on one run — but unreliable past ~30 s. F5-TTS (shipped in v0.2) is the replacement candidate that closes this gap with cloning intact.
- **Three monkey-patches** are applied in `_apply_neutts_patches`: `n_ctx=8192` (upstream hardcodes 2048), `repeat_penalty=1.05` injection on `Llama.__call__` (upstream omits this on the streaming path, causing ~15% content drop), and `tts.watermarker = None` (the Perth implicit watermarker introduces per-chunk audible clicks at streaming boundaries). All documented in `src/voice_forge/backends/neutts.py:_apply_neutts_patches` with reasoning.
- **Short-utterance sampling can collapse on specific voice/text combos.** The audition reproducibly produced 0.16 s of "audio" for `heid-research` × "Can you hear me?" — NeuTTS sampled stop tokens immediately. Other sisters with similar refs produced 1-3 s of intelligible audio. Worth a follow-up investigation (suggested mitigations: longer prompts, temperature bump for utterances < 10 chars, or a retry-with-stochasticity loop).

### Adding a NeuTTS voice

```bash
voice-forge voice add saga-comms /path/to/saga-ref.wav --ref-text "matching transcript"
# or pull from ElevenLabs (auto-trims to sentence boundaries via Whisper):
export ELEVENLABS_API_KEY=...
voice-forge voice from-elevenlabs saga-comms --elevenlabs-voice-id <id>
```

## Kokoro 82M

- **License:** Apache 2.0 (both model weights AND the [`hexgrad/kokoro`](https://github.com/hexgrad/kokoro) Python wrapper)
- **PyPI:** `kokoro>=0.9.4,<1.0` (Python `>=3.10,<3.13` until upstream cuts a release with the relaxed `<3.14` constraint — see [LEARNINGS](engineering-journal/LEARNINGS.md))
- **Default model:** `hexgrad/Kokoro-82M` (~314 MB on disk after first HF download)
- **Inference engine:** PyTorch (CPU; MPS-capable but not enabled in v0.2)
- **Voice paradigm:** Preset only. ~54 voice embeddings ship with the model, encoded as `<lang><gender>_<name>`:

  | Prefix | Language | Examples |
  |---|---|---|
  | `af_*` | American female | alloy, aoede, bella, heart, jessica, kore, nicole, nova, river, sarah, sky |
  | `am_*` | American male | adam, echo, eric, fenrir, liam, michael, onyx, puck, santa |
  | `bf_*` / `bm_*` | British female / male | alice, emma, isabella, lily / daniel, fable, george, lewis |
  | `ef_*` / `em_*` | Spanish female / male | dora / alex, santa |
  | `ff_*` | French female | siwis |
  | `hf_*` / `hm_*` | Hindi female / male | alpha, beta / omega, psi |
  | `if_*` / `im_*` | Italian female / male | sara / nicola |
  | `jf_*` / `jm_*` | Japanese female / male | alpha, gongitsune, nezumi, tebukuro / kumo |
  | `pf_*` / `pm_*` | Brazilian Portuguese female / male | dora / alex, santa |
  | `zf_*` / `zm_*` | Mandarin female / male | xiaobei, xiaoni, xiaoxiao, xiaoyi / yunjian, yunxia, yunyang, yunxi |

- **Sample rate:** 24 kHz mono float32 PCM
- **Streaming:** Native. `KPipeline` is a Python generator yielding per-segment `(graphemes, phonemes, audio)` tuples; voice-forge's `synthesize_stream` forwards each yield directly.

### Kokoro quirks worth knowing

- **System prerequisite: `espeak-ng`.** `misaki[en]` (Kokoro's G2P) uses espeak-ng for English OOD fallback. Install: `brew install espeak-ng` (Mac) / `apt-get install espeak-ng` (Linux). `KokoroBackend.load()` runs a pre-flight `shutil.which("espeak-ng")` check and raises a clear RuntimeError if missing — better than the cryptic phonemizer error you'd otherwise see at first synth.
- **No cloning at runtime.** Training a new voice embedding requires the Kokoro training pipeline + voice samples + GPU + time. Not available as an inference-time path.
- **Voice mixing syntax is parsed but not fully consumed in v0.2.** voice-forge accepts `--preset "af_bella(2)+af_sky(1)"` and parses it correctly. Multi-voice mixes currently degrade to picking the highest-weight name and logging a warning — tensor-blending the embeddings requires HF-cache path discovery for the per-voice `.pt` files that the upstream README doesn't document. Tracked in [QUEUED.md](engineering-journal/QUEUED.md) under "Kokoro voice-mixing tensor blending".

### Kokoro per-voice tunables

| Key | Type | Default | What it does |
|---|---|---|---|
| `speed` | float | 1.0 | Playback rate. Threads through to KPipeline's `speed=` param. >1 = faster. |

Example:

```bash
voice-forge voice tune kokoro-bella --sampling speed=1.15
```

(Future: voice-mixing tensor blending when upstream API stabilizes — see [QUEUED voice-mixing](engineering-journal/QUEUED.md).)

### Adding a Kokoro voice

```bash
voice-forge voice add kokoro-bella --backend kokoro --preset af_bella
voice-forge synth kokoro-bella "Hello from Kokoro." --out /tmp/test.wav
```

The voice IS the preset embedding — no ref WAV, no transcript. The `voice_id` you choose (`kokoro-bella` above) is just the local registry key.

## F5-TTS

- **License:** MIT wrapper ([`SWivid/F5-TTS`](https://github.com/SWivid/F5-TTS) Python lib, `pip install f5-tts`); Apache-2 model weights from the same repo.
- **PyPI:** `f5-tts>=1.1,<2.0` (no upper Python bound; works on 3.11/3.12 in our matrix)
- **Default model:** `F5TTS_v1_Base` (~1.5 GB on disk after first HF download)
- **Inference engine:** PyTorch (Apple Silicon: MPS autodetect; falls back to CPU)
- **Voice paradigm:** Ref-WAV cloning, **same shape as NeuTTS** — 3-15 s reference WAV + matching transcript. Encoding happens inside `infer()`; no pre-encode hook exposed (we set `encode_reference()` to return `None`).
- **Sample rate:** 24 kHz mono float32 PCM
- **Streaming:** No native streaming. `synthesize_stream` degrades to one chunk = full batch result.

### F5 quirks worth knowing

- **Slightly slower than realtime on M2 Ultra (RTF ~1.05)** with default `nfe_step=32`. A 30-second utterance takes ~31 seconds to synthesize. Lower `nfe_step` (e.g. 16) trades quality for speed; 16 is the practical floor.
- **No 30-second cliff** — diffusion-based architecture sustains long utterances cleanly. The v0.2 audition produced clean 71-86 s long-form rows on the Asgard sister refs.
- **Voice fidelity varies by reference.** The v0.2 audition surfaced this: on identical refs, **Saga and Hnoss came out faithful to their NeuTTS counterparts; Heid drifted noticeably**. F5's encoder appears sensitive to certain timbres / acoustic characteristics. Worth experimenting with seed values or reference-audio preprocessing per voice when cloning quality matters. See [LEARNINGS § F5 voice-fidelity variance](engineering-journal/LEARNINGS.md).
- **F5's `infer()` accepts a `speed=` param** (defaults to 1.0). voice-forge doesn't expose this through the Protocol yet — see the queued "per-voice tunable params" item.

### F5 per-voice tunables

Set via `voice-forge voice add ... --sampling key=value` (at registration) or `voice-forge voice tune <id> --sampling key=value` (post-registration). Lands in `metadata.json` under the `sampling` block; F5 reads what it recognizes, ignores the rest.

| Key | Type | Default | What it does |
|---|---|---|---|
| `nfe_step` | int | 32 | Diffusion-step count. Lower (e.g. 16) = ~2× faster synth, slightly lower quality. 16 is the practical floor. |
| `cfg_strength` | float | 2.0 | Classifier-free guidance. Higher = stronger adherence to reference. Try `2.5` or `3.0` when a voice drifts (e.g. Heid). |
| `seed` | int | None | RNG seed for reproducibility. Pin a seed when a specific render sounded right. |
| `speed` | float | 1.0 | Playback-rate multiplier. >1 = faster speech. F5's default pace is slower than NeuTTS; bumping to `1.1`-`1.2` makes it more conversational. |
| `cross_fade_duration` | float | 0.15 | Seconds of crossfade between F5's internal chunks. |
| `sway_sampling_coef` | float | -1 | F5's sampling-schedule param. Advanced; usually leave alone. |
| `target_rms` | float | 0.1 | Output volume normalization. |
| `remove_silence` | bool | False | Post-process silence trim. |

Example tune for Heid (the drift case from the v0.2 audition):

```bash
voice-forge voice tune heid-research-f5 --sampling cfg_strength=3.0 --sampling seed=42
```

### Adding an F5 voice

```bash
voice-forge voice add saga-f5 /path/to/saga-ref.wav --ref-text "matching transcript" --backend f5
```

Same workflow as NeuTTS — the only difference is `--backend f5`.

## XTTS-v2 (Coqui idiap fork)

- **Library license:** MPL-2.0 (via [`coqui-tts`](https://github.com/idiap/coqui-ai-TTS), the actively-maintained idiap fork of the discontinued upstream Coqui)
- **Model weights license:** [**CPML — non-commercial only**](https://coqui.ai/cpml) unless commercially-licensed via Coqui (licensing@coqui.ai)
- **PyPI:** `coqui-tts>=0.27,<0.30` + `transformers<5` (pin reason: coqui-tts uses `transformers.pytorch_utils.isin_mps_friendly` which was removed in v5)
- **Default model:** `tts_models/multilingual/multi-dataset/xtts_v2` (~1.8 GB on disk after first HF download)
- **Inference engine:** PyTorch (Apple Silicon: stay on **CPU**, see device note below)
- **Voice paradigm:** Ref-WAV cloning + multilingual (17 languages). **Does NOT need `ref_text`** — XTTS encodes the speaker WAV directly. Language code is required and pulled from `voice.metadata["language"]` (defaults to `"en"`).
- **Sample rate:** 24 kHz mono float32 PCM
- **Streaming:** No native streaming via the `TTS.api.TTS.tts()` surface; `synthesize_stream` degrades to one chunk.

### XTTS-v2 quirks worth knowing

- **License preflight required.** `XTTSBackend.load()` checks for `COQUI_TOS_AGREED=1` in the environment and refuses to load without it. The CPML is non-commercial unless you've paid Coqui. **voice-forge does not auto-accept** — you have to set the env var yourself after reading the CPML. Failure mode is a clear `RuntimeError` with the URL + commercial-licensing contact, not a stdin prompt.
- **Cloning is pitch + gender, NOT accent.** Empirically on the Asgard sister refs (American English, distinct individual character): XTTS produces clean audio that lands in the right gender + broad pitch range but loses each sister's accent and timbre. NeuTTS and F5 preserve identity; XTTS doesn't. Use it where "any clean voice" is enough, not for persona TTS.
- **MPS is 5× SLOWER than CPU on Apple Silicon.** Coqui's codebase has documented patchy MPS support — many ops fall back to CPU mid-graph and the per-op marshalling kills any GPU benefit. Default `device=None` → CPU is correct on M-series; don't override to `"mps"` until upstream coqui-tts ships better op coverage.
- **Library and model versions can have transformers conflicts.** `coqui-tts==0.27.5` calls `transformers.pytorch_utils.isin_mps_friendly`, an API removed in transformers v5. The `[xtts]` extra explicitly pins `transformers<5`. When you upgrade `coqui-tts`, check if the upper bound is still needed.

### XTTS per-voice tunables

| Key | Type | Default | What it does |
|---|---|---|---|
| `speed` | float | model default | Playback rate. |
| `temperature` | float | model default | Sampling temperature. Higher = more variation. |
| `top_k` | int | model default | Top-k sampling. |
| `top_p` | float | model default | Nucleus sampling. |
| `repetition_penalty` | float | model default | XTTS-specific repeat suppression. |
| `length_penalty` | float | model default | XTTS-specific length bias. |

### Adding an XTTS voice

```bash
# One-time consent (the model weights are CPML; you have to accept):
export COQUI_TOS_AGREED=1

# Register a voice (XTTS doesn't use ref_text but the registry tolerates it):
voice-forge voice add saga-xtts /path/to/saga-ref.wav --ref-text "any text" --backend xtts

# Or skip the transcript entirely:
voice-forge voice add saga-xtts /path/to/saga-ref.wav --ref-text "ignored by xtts" --backend xtts
```

(`voice add` will Whisper-transcribe if `--ref-text` is omitted; XTTS doesn't care what the transcript says but the registry expects a `ref.txt` so it's recorded anyway for compatibility with other backends.)

## Dia-1.6B (Nari Labs)

- **License:** Apache-2.0 (both [`nari-labs/dia`](https://github.com/nari-labs/dia) repo AND the model weights at `nari-labs/Dia-1.6B-0626` on HuggingFace).
- **PyPI:** none — accessed via native `transformers.DiaForConditionalGeneration` (added in transformers 4.46+). The `[dia]` extra pins `transformers>=4.46,<5` + `librosa>=0.10` (for the 44.1→24 kHz resample).
- **Default model:** `nari-labs/Dia-1.6B-0626` (~3 GB on disk after first HF download)
- **Inference engine:** PyTorch via HF Transformers (Apple Silicon: MPS autodetect; 1.6B params, big enough to amortize MPS launch overhead)
- **Voice paradigm:** Ref-WAV cloning + **multi-speaker dialogue** via `[S1]` / `[S2]` tags. v0.2 audition only exercises single-speaker; multi-speaker is a follow-up.
- **Sample rate:** 44.1 kHz native; voice-forge resamples to 24 kHz to match the Protocol convention.
- **Streaming:** No native streaming through HF Transformers's `generate()` surface; `synthesize_stream` degrades to one chunk.

### Dia quirks worth knowing (and there are several)

- **`max_new_tokens=3072` default caps output at ~18-21 s in practice** (theoretical ceiling 35.7 s at 86 tokens/s, but in our audition the ref-transcript prefix consumed budget too, leaving ~18 s for actual generation). Long-form text gets truncated, NOT rushed. For p3 stories (~80 s expected) bump `max_new_tokens` to 8192 or higher; per-voice tuning ([QUEUED P2](engineering-journal/QUEUED.md)) is the right home for this.
- **Heid's ref WAV broke Dia exactly like NeuTTS** — 0.19 s of audio for "Can you hear me?", same ~0.16-0.20 s collapse the autoregressive llama-cpp path produces. **Third autoregressive sampler to fail on this specific reference.** F5 (diffusion), Kokoro (encoder-decoder), XTTS (decoder with CFG) all handle the same ref + text cleanly. **The ref WAV itself is doing something that breaks autoregressive token-sampling stop conditions.** See [LEARNINGS § Heid ref breaks autoregressive sampling](engineering-journal/LEARNINGS.md).
- **Heid came out wrong-gender on Dia** — user verdict 2026-05-25 listening to the v0.2 audition: "voices [are] too fast and even wrong gender in heid's case." Adds to the evidence that Heid's ref is problematic.
- **All p2 outputs sound faster than expected** — same text in 11-16 s where F5 used 16-20 s. Likely Dia's documented "long input → unnaturally fast speech" behavior; input is ref-transcript + gen-text, which together exceed Dia's sweet spot.
- **Prompt format is opinionated.** Upstream requires text to begin with `[S1]`, and for cloning specifically: `[S1] {ref_text} [S1] {gen_text}`. voice-forge formats this internally — users don't need to know.
- **15-minute audition for 9 WAVs on M2 Ultra MPS** — Dia is the slowest backend we've shipped. ~3-5 RTF estimate. Mostly the 1.6B-param MPS pass; the 3 GB model download dominates the first-run cold-load.
- **Sampling defaults** are upstream-recommended: `max_new_tokens=3072, guidance_scale=3.0, temperature=1.8, top_p=0.90, top_k=45`. All exposed via the `config` dict passed to `load()`.

### When to use Dia anyway

Dia is the only backend voice-forge ships in v0.2 with **multi-speaker dialogue** capability (`[S1]`/`[S2]` tags in input text). For dialogue-shaped content where you want two voices conversing in one synth call — interactive fiction, agent-to-agent conversations, audiobook-style narration — Dia is the right tool. For single-speaker persona TTS on long-form content, F5 is the better pick today; revisit Dia once per-voice `max_new_tokens` tuning ships.

### Dia per-voice tunables

| Key | Type | Default | What it does |
|---|---|---|---|
| `max_new_tokens` | int | 3072 | Audio-token budget. Default caps output at ~18-21 s (ref-transcript prefix eats budget). **Bump to 8192 for long-form** — closes the documented Dia long-form truncation. |
| `guidance_scale` | float | 3.0 | Classifier-free guidance. |
| `temperature` | float | 1.8 | Sampling temperature. |
| `top_p` | float | 0.90 | Nucleus sampling. |
| `top_k` | int | 45 | Top-k sampling. |

Example tune for the long-form truncation problem:

```bash
voice-forge voice tune saga-comms-dia --sampling max_new_tokens=8192
```

### Adding a Dia voice

```bash
voice-forge voice add saga-dia /path/to/saga-ref.wav --ref-text "matching transcript" --backend dia
```

Same shape as NeuTTS / F5. For multi-speaker reference (the unique Dia feature), the ref WAV should contain both speakers alternating, with the transcript using `[S1]`/`[S2]` tags. v0.2 doesn't yet expose a CLI flag for multi-speaker; this lands with the per-voice tunable params work.

## Backends queued for future versions

These live in [`docs/engineering-journal/QUEUED.md`](engineering-journal/QUEUED.md) with priority + effort + worth-it-when triggers. Listed here so contributors evaluating a new backend candidate can find the prior thinking.

| Backend | Why it's queued | Blocker |
|---|---|---|
| F5-TTS | Higher quality cloning than NeuTTS; Apache-2 | GPU required for usable RTF |
| XTTS-v2 (Coqui) | Multilingual + voice cloning; MPL-2 | GPU; project officially discontinued (forks exist) |
| Dia | Multi-speaker dialogue (`[S1]`/`[S2]` tags); Apache-2; **first community wrapper opportunity** | 10 GB VRAM mandatory |
| Kitten | Smallest model (15-80M); ONNX; CPU-only; Apache-2 | None — straightforward port |
| MeloTTS | Multilingual + CPU-friendly; MIT | None — straightforward port |
| Chatterbox-Turbo | Sub-200 ms first-token; MIT | None — straightforward port |
| Piper | 30+ languages; subprocess-only (GPL-3) | GPL contamination — subprocess wrapper only |
| Fish Audio S2 Pro | 80+ languages, voice cloning; Apache-2 | Serving-stack complexity |

See [`docs/PRIOR_ART.md`](PRIOR_ART.md) for the full comparative study these are drawn from.

## Adding a new backend (for contributors)

The fast path:

1. Drop a module at `src/voice_forge/backends/<name>.py` exposing a class that satisfies the `TTSBackend` Protocol — see `kokoro.py` for a preset-voice example, `neutts.py` for a cloning example.
2. Call `register_backend("<name>", YourBackend)` at module top level (auto-registers on import).
3. Add `"<name>": "voice_forge.backends.<name>"` to `_BACKEND_MODULES` in `src/voice_forge/backends/__init__.py` so the dispatcher knows the name.
4. Add a `[project.optional-dependencies] <name> = [...]` entry to `pyproject.toml` for the heavy ML deps. Update the `all` extra too.
5. Add a sys.modules-injection fake at `tests/_stubs/fake_<name>lib.py` and a corresponding `tests/unit/test_<name>_backend.py` (model the shape after `fake_neuttslib.py` / `fake_kokorolib.py`).
6. Document in this file (a section like "Kokoro 82M" above) + add a LEARNING for any non-obvious quirks.

For the deeper architectural reasoning (Protocol vs ABC, why FS-backed registry, why REST-first), see [`docs/ARCHITECTURE.md`](ARCHITECTURE.md).

## How to bench a backend on your host

Reproduce the table at the top of this doc against your own hardware:

```bash
. .venv/bin/activate
export VOICE_FORGE_REGISTRY="$(pwd)/.bench-registry"
mkdir -p "$VOICE_FORGE_REGISTRY"
# Register at least one voice per backend you want to bench (e.g. the Kokoro flow above).

# Use scripts/asgard_audition.py for the structured test, or the inline Python
# bench in docs/engineering-journal/LEARNINGS.md ("Kokoro vs NeuTTS resource
# profile") for tight cold-load + RSS + RTF numbers in a single process.
```

Post your numbers back to a LEARNING entry if they're materially different from the table — different hardware = different RTF and different resident memory.
