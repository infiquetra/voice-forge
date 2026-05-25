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

## 2026-05-24

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

