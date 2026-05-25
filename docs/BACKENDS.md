# Backends — voice-forge's pluggable TTS surface

This is the reference for the TTS backends that voice-forge knows how to drive. It exists so a new contributor can answer:

1. "Which backend should I use for my use case?"
2. "What does it cost to add this backend to my deployment host?"
3. "How does this backend differ from the others architecturally?"

For the abstraction itself — the `TTSBackend` Protocol, the `VoiceRef` union dataclass, the registry, the dispatch path — see [`docs/ARCHITECTURE.md`](ARCHITECTURE.md). For the broader landscape of self-hosted TTS engines (Coqui, F5, XTTS, Dia, Kitten, VibeVoice, etc.) see [`docs/PRIOR_ART.md`](PRIOR_ART.md).

## At a glance — what ships in v0.2

| Backend | License | Voice paradigm | Cold load | Resident RSS | RTF (Apple Silicon CPU) | Status |
|---|---|---|---|---|---|---|
| **NeuTTS Air (Q8 GGUF)** | Apache 2.0 | Ref-WAV cloning (3-15s reference) | ~26 s | ~5.6 GB | 0.80 (faster than realtime) | shipped v0.1 |
| **Kokoro 82M** | Apache 2.0 | Preset voice (~54 bundled embeddings) | ~3.6 s | ~1.4 GB | 0.07 (~14× realtime) | shipped v0.2 |

Both backends are pure-CPU on Apple Silicon. No MPS / CUDA required (and for NeuTTS Q8, MPS is actually *slower* — see [LEARNINGS § "Q4/Q8/BF16 × CPU/MPS"](engineering-journal/LEARNINGS.md#q4--q8--bf16--cpu--mps-on-apple-m-series--q4cpuaccelerate-is-fastest-bf16-is-4x-slower)).

Numbers above come from a controlled bench documented at [LEARNINGS § "Kokoro vs NeuTTS resource profile"](engineering-journal/LEARNINGS.md#kokoro-vs-neutts-resource-profile--kokoro-rtf-14-and-14-gb-ram-neutts-resident-memory-was-higher-than-estimated). Re-run the bench locally and post-deploy when you want to ground numbers in your hardware.

## Picking a backend

Decision tree, in order of how voice-forge users have asked it so far:

**"I want a specific person's voice."**
→ NeuTTS Air. Drop a 3-15s ref WAV + matching transcript into `~/.voice-forge/voices/<id>/`, call `voice-forge synth <id> "..."`. Cloning is on by default. Quality is "Medium" by voice-forge's internal ranking — fine for agent chatter, audible NeuTTS character on long-form (see the 30-second cliff caveat below).

**"I want clean high-quality TTS, voice identity doesn't matter."**
→ Kokoro. Pick from `af_bella`, `af_nicole`, `af_heart`, `am_adam`, `bf_emma`, etc. (full list in the [Kokoro section below](#kokoro-82m)). No cloning — these are pre-trained voice embeddings shipped with the model.

**"I need ≥30-second utterances that stay coherent."**
→ Kokoro for any-clean-voice. NeuTTS rots noticeably past ~30 s ([LEARNINGS § NeuTTS streaming content loss](engineering-journal/LEARNINGS.md#neutts-streaming-content-loss--streaming-emits-15-21-less-audio-than-batch-for-identical-input-on-long-content) and the empirical 41-69 s rows from the v0.2 audition show audible drift in the back half).
→ For long-form WITH cloning: queued for v0.3 (F5 / XTTS / VibeVoice — see [QUEUED.md](engineering-journal/QUEUED.md)).

**"I'm running on constrained hardware (Pi 5, low-end Mac)."**
→ Kokoro only. NeuTTS's ~5.6 GB resident set is too heavy for most 8 GB hosts.

**"I'm running on a real workstation (16+ GB Mac, 32+ GB server)."**
→ Both. Same registry, same server; `backend` per voice in metadata.json routes to the right engine.

## Deployment-host capacity

| Host (RAM)                    | Both backends | Kokoro only | NeuTTS only |
|---|---|---|---|
| Raspberry Pi 4 (4 GB)         | ❌ no chance         | ⚠ borderline (~1.5 GB)   | ❌ |
| Raspberry Pi 5 (8 GB)         | ❌ would OOM         | ✓ comfortable             | ⚠ tight (swap-prone) |
| Mac mini M1/M2 base (8 GB)    | ❌ no headroom       | ✓ comfortable             | ⚠ swap-prone |
| Mac mini M2/M4 base (16 GB)   | ⚠ tight              | ✓                         | ✓ |
| **Mac mini M4 Pro (24 GB)**   | ✓ comfortable        | ✓                         | ✓ (Asgard production host) |
| Mac Studio / 32 GB+           | ✓ trivial            | ✓                         | ✓ |

(Numbers measured 2026-05-24 on a Mac Studio. RSS numbers reflect both backends loaded; idle ~67 MB.)

## NeuTTS Air

- **License:** Apache 2.0
- **Repo:** [`Neuphonic/neutts`](https://github.com/neuphonic/neutts)
- **Default model:** `neuphonic/neutts-air-q8-gguf` (Q8 quantized GGUF, ~766 MB on disk)
- **Inference engine:** [`llama-cpp-python`](https://github.com/abetlen/llama-cpp-python) (autoregressive token generation) + `neucodec` (codec → PCM)
- **Voice paradigm:** Ref-WAV cloning. Each voice is registered with a 3-15 s reference WAV and a matching transcript (`ref.txt`). Whisper transcribes if no transcript is provided.
- **Sample rate:** 24 kHz mono float32 PCM
- **Streaming:** Supported via `synthesize_stream` (chunked HTTP); native, but with a documented ~15-21% content-loss vs batch ([LEARNINGS § NeuTTS streaming](engineering-journal/LEARNINGS.md)) — callers should default to batch.

### NeuTTS quirks worth knowing

- **30-second narrative coherence cliff.** Long utterances (>30 s) drift, lose words, or produce repeated tokens. The v0.2 audition produced 41-69 s rows that demonstrated this audibly. Not a hard cutoff — Freya's clone went 35.9 s cleanly on one run — but unreliable past ~30 s. Tracked in [QUEUED.md](engineering-journal/QUEUED.md) under "VibeVoice backend (long-form quality)".
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

### Adding a Kokoro voice

```bash
voice-forge voice add kokoro-bella --backend kokoro --preset af_bella
voice-forge synth kokoro-bella "Hello from Kokoro." --out /tmp/test.wav
```

The voice IS the preset embedding — no ref WAV, no transcript. The `voice_id` you choose (`kokoro-bella` above) is just the local registry key.

## Backends queued for future versions

These live in [`docs/engineering-journal/QUEUED.md`](engineering-journal/QUEUED.md) with priority + effort + worth-it-when triggers. Listed here so contributors evaluating a new backend candidate can find the prior thinking.

| Backend | Why it's queued | Blocker |
|---|---|---|
| F5-TTS | Higher quality cloning than NeuTTS; Apache-2 | GPU required for usable RTF |
| XTTS-v2 (Coqui) | Multilingual + voice cloning; MPL-2 | GPU; project officially discontinued (forks exist) |
| Dia | Multi-speaker dialogue (`[S1]`/`[S2]` tags); Apache-2; **first community wrapper opportunity** | 10 GB VRAM mandatory |
| VibeVoice (Microsoft) | Long-form coherence — up to 90 min multi-speaker | Research-stage license; verify before depending |
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
