# v6 NeuTTS daemon snapshot

Provenance: the two `.py` files in this directory are a frozen copy of the v6 NeuTTS daemon + client that ran in `infiquetra/home-lab` before voice-forge was spun out (see `../../2026-05-24-pre-history.md` and `../../2026-05-24-voice-forge-spin-out.md`).

They are **reference implementations only** — voice-forge's `src/voice_forge/backends/neutts.py` is the live code path. These files document:

- the original `n_ctx=8192` monkey-patch (now in `_apply_neutts_patches`)
- the original `repeat_penalty=1.05` `Llama.__call__` wrap (same)
- the original `watermarker = None` post-construction (same)
- the original streaming FIFO + WAV-header chunking pattern (lives in voice-forge's `server.py` `_streaming_wav_header` + `_stream_wav` helpers)

They were parked at the repo root under `_porting/` during the v0.1 port, then moved here in v0.2 once the port stabilized. Kept because they are the empirical ground-truth for the three monkey-patches — if NeuTTS upstream changes shape, we compare-and-contrast against this snapshot to figure out what broke.
