# voice-forge pre-history — the NeuTTS investigation that led here

**Date:** 2026-05-24 (events earlier the same day as v0.1.0 ship)
**Status:** Historical context — describes the engineering work in `infiquetra/home-lab` that motivated spinning out voice-forge.
**Companion narrative:** `2026-05-24-voice-forge-spin-out.md` (the spin-out decision itself)

## Why this narrative exists

voice-forge was born from a prototype: a NeuTTS-Air daemon built inside `infiquetra/home-lab` to give a fleet of 9 Discord voice bots (the "Asgard sisters") local TTS that preserved their ElevenLabs-designed Norwegian accents. Six iterations of that prototype taught us the specific knobs, gotchas, and architectural patterns that voice-forge now encodes. This narrative captures the engine-level lessons from those iterations so future voice-forge contributors don't have to re-derive them.

(For deployment-specific lessons — how to integrate voice-forge into an existing TTS pipeline, how to cutover safely — see `2026-05-24-voice-forge-spin-out.md` and the home-lab repo's `2026-05-24-voice-forge-phase-g-cutover.md`.)

## The starting question

Could NeuTTS-Air replace ElevenLabs for local voice cloning? The pre-investigation plan assumed:
1. MPS faster than CPU on Apple Silicon
2. Sub-500ms first-byte latency feasible with warm pool
3. Monkey-patch the existing dispatcher to keep the model warm in-process

Devil's-advocate research + actual measurement DEMOLISHED all three assumptions:

## Finding 1: MPS doesn't help — Q4+CPU is fastest in every bucket

Counterintuitive but real on M4 Pro. See LEARNINGS § "Q4 / Q8 / BF16 × CPU / MPS on Apple M-series" for the full measurement table. Bottom line: NeuTTS (~500MB-1.5GB) is small enough that Metal kernel-launch overhead exceeds GPU benefit. Apple Accelerate (CPU+BLAS) wins.

→ voice-forge's `NeuTTSBackend` defaults to `device="cpu"`.

## Finding 2: BF16 is dramatically the slowest, not the fastest

We expected BF16 full precision to be slower than Q8 (smaller weights), but the magnitude surprised us: 4× slower synth (RTF 1.76 vs Q8's 0.30 on M4 Pro CPU). BF16 had slightly fewer clicks but the same long-narrative degradation as Q8. The slow-down made it unusable for conversational TTS.

→ voice-forge's `NeuTTSBackend` defaults to Q8 (`neuphonic/neutts-air-q8-gguf`). BF16 is opt-in via config.

## Finding 3: n_ctx defaults to 2048 — way under what the model supports

NeuTTS hardcodes `self.max_context = 2048` in its `__init__`, which flows through to `Llama(n_ctx=2048)`. The underlying model is trained at 32K. Long input text silently truncated at the model boundary.

→ voice-forge's `NeuTTSBackend.load()` monkey-patches `_load_backbone` to set `self.max_context` to a configurable value (default 8192) BEFORE the Llama is constructed. The patch is idempotent via a module-level flag so re-instantiation doesn't compound.

## Finding 4: Daemon architecture > monkey-patch warm pool

The pre-investigation plan was to monkey-patch the dispatcher to keep the NeuTTS model warm in-process per gateway. User pushback in real time ("can't we just start it as a service?") plus actual prototype implementation showed:
- Monkey-patch: 9 gateways × 1.5GB model copies = 13.5GB RAM (impossible on 24GB Mac mini)
- Daemon: 1 shared 1.5GB process + 9 thin clients = ~2GB total

Plus monkey-patching is fragile (hermes-agent dispatcher API can change); a daemon with a stable wire protocol is more robust.

→ voice-forge's design IS this daemon-as-service pattern. The FastAPI HTTP server is the stable wire protocol. Clients (including the home-lab hermes-agent integration) are thin.

## Finding 5: Isolated venv beats shared venv for heavy ML deps

First install attempt: `pip install neutts[llama]` into the shared hermes-agent venv. Result: cascade-breaking deps (transformers, huggingface-hub, tokenizers all forced to versions incompatible with hermes-agent's other tools). Had to fully revert.

→ voice-forge ships as its OWN package with its OWN deps. Downstream consumers should install into an isolated venv (the home-lab Ansible role uses `~/.hermes/voice-forge-venv/`). Documented in CONTRIBUTING.md and the role README.

## What the daemon prototype taught about the model itself

Beyond architecture findings, the daemon iteration cycle (v1 → v6) discovered model-level limits and gotchas:

### Stuttering (v2 → v4)

v1 used NeuTTS defaults (temperature=1.0, top_k=50, no repeat_penalty). Output stuttered on long text — model got stuck in tight token loops. v2 tried lowering temperature to 0.3 → made stuttering WORSE (tighter loops). v3 reverted. v4 added `repeat_penalty=1.05` via `_infer_ggml` monkey-patch — fixed.

→ voice-forge's `NeuTTSBackend.load()` wraps `Llama.__call__` to inject `repeat_penalty=1.05` if missing. Applies to BOTH batch and streaming paths (NeuTTS's streaming path doesn't pass it by default — see LEARNINGS § "NeuTTS streaming drops 15-21%").

### Streaming clicks (v6)

Streaming output had cracks that batch didn't. Root cause: NeuTTS's Perth watermarker is applied PER CHUNK during streaming, and the per-chunk noise patterns don't align at boundaries. See LEARNINGS § "Perth watermarker is a per-chunk artifact source" for the empirical reduction (15× fewer clicks with watermarker disabled).

→ voice-forge's `NeuTTSBackend.load()` sets `tts.watermarker = None` after construction.

### Long-narrative degradation (v6+)

Beyond ~30 seconds of sustained narrative, NeuTTS-Air produces incoherent phonemes ("speaking in tongues"). Affects all quantizations (Q4, Q8, BF16) and both batch and streaming modes. Training-distribution limit (~5-15s utterances).

→ Cannot be fixed by tuning NeuTTS-Air. voice-forge's ROADMAP tracks long-form-capable backends (F5-TTS, XTTS-v2, VibeVoice specifically designed for 90+ minute coherent audio). The pluggable backend architecture is what makes the eventual swap trivial.

## What the daemon prototype taught about deployment

These lessons informed voice-forge's API surface design (not its internals):

### "Test the slow part without the fast part"

Hours wasted iterating TTS quality through full Discord round-trips. Each iteration: type into Discord → STT → LLM → TTS subprocess → Discord plays audio → listen → iterate. ~30-60 seconds per cycle.

→ voice-forge ships a CLI direct-synth (`voice-forge synth <voice_id> "<text>" --out file.wav`) that bypasses ALL of that. Same iteration loop drops to ~2-5 seconds. README and CONTRIBUTING.md both feature this prominently.

### Voice Lab workflow (the freya_v2 + saga retrim discoveries)

Multiple discoveries about ref WAV preparation:
1. ElevenLabs Voice Lab previews are the only reliable way to get the ACCENTED voice from ElevenLabs (fresh API synthesis strips the accent).
2. Ref audio + ref text MUST match exactly. If audio extends past text, the cloning model drifts.
3. Trim audio at sentence boundaries via Whisper, not arbitrary time cuts.
4. Force `language="en"` in Whisper to avoid Norwegian-accented-English-misflagged-as-Swedish.

→ voice-forge's `voice_lab.elevenlabs.pull_and_prepare()` encodes the full pipeline: pull preview → MP3→WAV → Whisper-transcribe → trim to sentence boundary → write matching pair. The Whisper module forces `language="en"` by default with override available.

## Cross-references

- `narratives/2026-05-24-voice-forge-spin-out.md` — the spin-out decision narrative (the WHY of this repo existing)
- `LEARNINGS.md` — all 8 findings from this pre-history in structured format
- `DECISIONS.md` — Q8 default, batch default, Protocol-based backend abstraction, all locked here
- `docs/PRIOR_ART.md` — what we surveyed before committing to fresh-build
- `docs/ROADMAP.md` — the backend swap roadmap that addresses the long-narrative limit
- Plan file (in user's `~/.claude/plans/`, not committed): `i-am-under-the-merry-finch.md` Phase A→H
