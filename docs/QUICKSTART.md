# Quickstart — voice-forge in 5 minutes

Goal: go from `pip install` to **hearing a voice** in five minutes. After this you can listen to streamed audio in your browser, register a real cloned voice, and call voice-forge from `curl` / Python / your own client.

If anything in this guide doesn't work, please [open an issue](https://github.com/infiquetra/voice-forge/issues) — we treat quickstart drift as a bug.

---

## 1. Prerequisites

- **macOS or Linux** (Windows is untested; use WSL2 if you're on Windows)
- **Python 3.11 or 3.12** (3.13 is blocked by the Kokoro extra — see [BACKENDS.md](BACKENDS.md))
- **`uv`** (recommended) or `pip`. Install uv with `curl -LsSf https://astral.sh/uv/install.sh | sh`

That's it for the F5 default. If you also want Kokoro voices, you'll need `espeak-ng`:

```bash
# macOS
brew install espeak-ng

# Debian / Ubuntu
sudo apt-get install -y espeak-ng
```

## 2. Install voice-forge

Pick the backends you want. The default is **F5** (identity-preserving cloning, long-form coherence). Extras are additive — install more later by re-running with extra names appended.

```bash
# Recommended starting point: F5 + the Voice Lab tools (Whisper trimmer + ElevenLabs pull)
uv pip install "voice-forge-tts[f5,voice-lab]"

# Add Kokoro preset voices (requires espeak-ng):
uv pip install "voice-forge-tts[f5,kokoro,voice-lab]"

# Everything (heavy install — F5 + Kokoro + NeuTTS + XTTS + Dia + voice-lab):
uv pip install "voice-forge-tts[all]"
```

> First install pulls PyTorch + transformers + F5 weights (~1.5 GB cold download). Subsequent runs use the cached weights.

## 3. Run the server

```bash
voice-forge serve --host 127.0.0.1 --port 9876
```

You should see uvicorn boot logs and `Application startup complete.` within a few seconds. Leave this running.

## 4. Hear something — the in-browser demo

Open this URL in your browser:

> **http://127.0.0.1:9876/demo**

You'll see a voice picker and a text box. The picker will be empty for now (we haven't registered any voices yet) — that's the next step.

The page itself proves voice-forge is up. Keep the tab open; we'll come back to it.

## 5. Register your first voice

Two paths, depending on whether you want **preset** voices (no audio needed) or **cloned** voices (you bring a reference WAV).

### 5a. Preset voice — fastest path (Kokoro)

Requires you installed the `[kokoro]` extra above and have `espeak-ng` on PATH.

```bash
voice-forge voice add kokoro-bella --backend kokoro --preset af_bella
```

That's it. There are ~54 preset voices shipped with Kokoro — the full list is in [BACKENDS.md § Kokoro](BACKENDS.md). Try `af_heart`, `af_nicole`, `am_adam`, `bf_emma`, etc.

### 5b. Cloned voice — bring your own reference (F5)

You need a 3-15 second reference WAV of someone speaking clearly, with the matching transcript.

```bash
# Put a ref WAV at /tmp/my-ref.wav with someone saying:
# "Hello, this is a test of the voice cloning system."
# Then:

voice-forge voice add my-voice /tmp/my-ref.wav \
  --ref-text "Hello, this is a test of the voice cloning system." \
  --backend f5
```

The first cloning run downloads F5 weights (~1.5 GB) — be patient. Subsequent calls reuse the cache.

### 5c. Pull a voice from ElevenLabs

If you have an ElevenLabs account with custom voices:

```bash
export ELEVENLABS_API_KEY=sk_...
voice-forge voice from-elevenlabs my-voice --elevenlabs-voice-id <your-voice-id> --backend f5
```

This pulls the **frozen preview MP3** (which preserves the original accent), converts to WAV, runs Whisper to transcribe + trim, and registers the result.

## 6. Synthesize

Pick one of these — they all produce the same audio.

### 6a. Via the live demo (already open in your browser)

Refresh `http://127.0.0.1:9876/demo`. Your newly-registered voice now appears in the picker. Type something, click **Speak**, and the audio streams into your browser via the Web Audio API.

### 6b. Via the CLI

```bash
voice-forge synth my-voice "Hello, world. This is voice-forge." /tmp/hello.wav
afplay /tmp/hello.wav   # macOS
# or
aplay /tmp/hello.wav    # Linux
```

### 6c. Via HTTP (OpenAI-compatible)

```bash
curl http://127.0.0.1:9876/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{
    "model": "voice-forge",
    "input": "Streaming this one so the first audio arrives fast.",
    "voice": "my-voice",
    "response_format": "wav",
    "stream": true
  }' \
  --output /tmp/streamed.wav
```

`stream: true` flips to HTTP chunked transfer-encoding — synth begins on sentence 1 and PCM frames arrive progressively. Useful when you're piping into a player like `ffplay -`.

### 6d. Via WebSocket (for LLM-driven pipelines)

If your text is itself a stream (LLM tokens arriving over time), the `WS /v1/tts/stream` endpoint is the right surface — synth starts on sentence 1 as soon as the sentence boundary forms in your token stream, instead of waiting for the LLM to finish.

See [API_SPEC.md § Streaming surface — Layer-2 (WebSocket)](API_SPEC.md) for the wire protocol. The live demo page is a working client; `scripts/asgard_ws_audition.py` is another.

## 7. Tune a voice (optional)

Each backend exposes sampling knobs you can override per voice. The F5 streaming preset is `nfe_step=16` — half the diffusion steps, audibly indistinguishable from the 32-step default on long-form text:

```bash
voice-forge voice tune my-voice --sampling nfe_step=16
```

See [BACKENDS.md](BACKENDS.md) for each backend's tunable knobs.

## 8. Where to go next

- **[BACKENDS.md](BACKENDS.md)** — per-backend deep-dive: licenses, paradigms, resource costs, tunables, when to pick which.
- **[API_SPEC.md](API_SPEC.md)** — full REST + WebSocket contract with examples.
- **[ROADMAP.md](ROADMAP.md)** — what shipped in v0.2, what's planned for v0.3.
- **[engineering-journal/](engineering-journal/)** — LEARNINGS / DECISIONS / QUEUED with mechanisms and rationale for everything voice-forge has decided.
- **`http://127.0.0.1:9876/docs`** — auto-generated Swagger UI for the REST API.
- **`http://127.0.0.1:9876/openapi.json`** — raw OpenAPI 3.1 spec.

## Troubleshooting

**"`voice-forge` not found"** — your shell can't see the binary. Reload PATH (`hash -r` on bash/zsh) or check that the venv where you installed it is active.

**"backend f5 known but not installed"** — you didn't include the `[f5]` extra. Re-run: `uv pip install "voice-forge-tts[f5,voice-lab]"`.

**"OSError: dlopen ... libtorchcodec ..."** — torch + torchcodec ABI mismatch on macOS. The `[f5]` extra pins torch 2.8.x to avoid this; if you've upgraded torch manually, downgrade with `uv pip install --reinstall "voice-forge-tts[f5]"`. See [LEARNINGS 2026-05-25 § "Torch 2.9.x + torchcodec 0.13.0 ABI gap"](engineering-journal/LEARNINGS.md).

**"Kokoro voice silent / espeak-ng error"** — Kokoro needs `espeak-ng` on the host PATH. `brew install espeak-ng` (macOS) or `apt-get install espeak-ng` (Linux).

**"XTTS refuses to load"** — XTTS-v2 weights are CPML-licensed (non-commercial). voice-forge requires `COQUI_TOS_AGREED=1` in the env to confirm you've read [Coqui's license terms](https://coqui.ai/cpml). See [BACKENDS.md § XTTS-v2](BACKENDS.md).

**Voice picker is empty in `/demo`** — no voices registered yet. Go back to step 5.

**Browser plays nothing on Speak** — open the browser DevTools Console; voice-forge surfaces WS errors there. The demo also has an event log panel below the metrics — it shows every WS frame as it arrives. If the log shows `sentence_done` events but no audio plays, your browser may be blocking the AudioContext until you've clicked somewhere on the page (autoplay restriction). Click Speak again.
