# Higgs Audio V2 Backend — Rewrite Plan

**Date:** 2026-05-26
**Goal:** Replace the broken `HiggsAudioServeEngine`-based child impl with a direct port of upstream's `HiggsAudioModelClient` from `examples/generation.py`. Wire the missing `audio_processing/` source files into the higgs venv via a post-install hook.

## Root Cause

The installed `boson-multimodal` PyPI wheel (built from `git+https://github.com/boson-ai/higgs-audio.git` via setuptools' default `find_packages`) excludes two namespace-package directories (`serve/` and `audio_processing/`) because they lack `__init__.py` files. The actual model + dataset + collator + utils modules ARE shipped. Upstream's own reference inference script (`examples/generation.py`) uses `HiggsAudioModelClient` (a custom class in that script, NOT in the package), which depends on `boson_multimodal.audio_processing.higgs_audio_tokenizer.load_higgs_audio_tokenizer`.

## Strategy

1. **Don't use `serve_engine`.** Port the reference `HiggsAudioModelClient` pattern directly into `_HiggsInProcess`. Adapt to voice-forge's `VoiceRef`-driven API.
2. **Stitch `audio_processing/` into the venv** at provision time via a backend-specific post-install hook (clone upstream + cp -r the missing tree).
3. **Add upstream's runtime deps to the `[higgs]` extra.** transformers, librosa, dacite, loguru, vector_quantize_pytorch, descript-audio-codec, pandas, tqdm, jieba, langid, accelerate, huggingface_hub.

## Tasks

- [x] Investigate upstream packaging defect (confirm missing `__init__.py`)
- [x] Read upstream `examples/generation.py` reference impl
- [x] Read upstream `boson_multimodal/audio_processing/higgs_audio_tokenizer.py`
- [x] [P1] Add `POST_INSTALL_HOOK` mechanism to `cli.py:backend_install`
- [x] [P1] Define `POST_INSTALL_HOOK` in `_higgs_post_install.py` that copies missing audio_processing/ tree
- [x] [P1] Update `[higgs]` extra in pyproject.toml with all transitive deps
- [x] [P1] Rewrite `_HiggsInProcess` to use direct model + tokenizer + collator pattern
- [x] [SEQ] Reprovision higgs venv via `voice-forge backend install higgs`
- [x] [SEQ] Discovered + pinned tokenizer revision (issue #176 — trfms-support config-schema break)
- [x] [SEQ] Discovered + pinned model revision (same trfms-support break, model side)
- [x] [SEQ] Cold-test end-to-end with Mimir voice — PASS (27.88s @ RMS 0.117)
- [x] [SEQ] Verify lint clean (ruff)
- [x] [SEQ] Final reporting

## Result

Cold-test PASS:
- Load: 105.8s (cold, includes 3-shard model download + tokenizer download)
- Synth: 92.9s for 27.88s audio = 3.3x slower than realtime on MPS
- Output: 24kHz mono 16-bit PCM WAV at /tmp/mimir-higgs-test.wav
- Peak: 0.7006, RMS: 0.1169 (both well above silence threshold)

## Cold-test target

- Voice: `personas/asgard/mimir-engineer/ref.wav` (14.66s) + `ref.txt`
- Text: 4-sentence Mimir-style monologue
- Output: `/tmp/mimir-higgs-test.wav` (24kHz mono, int16 WAV)
- Pass criteria: duration ≥10s, RMS ≥0.05, no exceptions
