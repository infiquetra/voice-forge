# Voice Lab — workflow for managing agent voices

The "Voice Lab" subsystem in voice-forge is a toolkit for the lifecycle of an agent voice: source it, refine it, register it, use it. v0 supports two source flows: **ElevenLabs Voice Lab pull** and **direct ref-WAV upload**.

## The lifecycle

```
1. SOURCE         2. REFINE          3. REGISTER        4. USE
   ──────         ───────             ─────────         ────
   ElevenLabs    Whisper-transcribe   Save to            POST /v1/audio/speech
   Voice Lab  →  Trim to sentence  →  ~/.voice-forge/ →  with voice_id
   preview MP3   boundary             voices/<id>/
   (frozen MP3)  (12-14s clean WAV)
   
   OR
   
   Direct WAV
   upload
   (3-15s)
```

## Why this workflow

We discovered the hard way (see home-lab `narratives/2026-05-24-voice-forge-spin-out.md`) that:

1. **ElevenLabs Voice Lab previews are the only reliable way to get the accented voice from ElevenLabs.** Fresh synthesis via their API strips the accent that was present in the original Voice Lab preview. So if you want to clone an ElevenLabs voice, you pull the PREVIEW MP3, not a synthesized sample.
2. **The ref WAV's text must match the audio exactly.** If you trim audio without re-transcribing, the cloning model will produce garbage. Always Whisper-transcribe the trimmed audio to get matching `ref_text`.
3. **Trim at sentence boundaries.** Mid-sentence cuts cause the cloning model to drift. A clean ".!?" boundary gives stable output.
4. **NeuTTS / similar models need 3-15s of ref audio.** Less is unstable; more is wasted (model only uses first ~10s of audio embedding context).

## Source flows

### Flow A: Pull from ElevenLabs

```bash
voice-forge voice from-elevenlabs --source saga --target saga-comms \
  --elevenlabs-voice-id c7qAAWgc7aGYHCLDzd8Y
```

What happens:
1. ElevenLabs API call: `GET /v1/voices/{id}` → `preview_url`
2. Download preview MP3
3. ffmpeg convert to 24kHz mono WAV (full duration — typically 30-45s)
4. faster-whisper transcribe (language=en forced)
5. Find last segment ending with `.!?` within 14s → trim WAV at that timestamp
6. Save trimmed WAV + transcript to `~/.voice-forge/voices/saga-comms/`
7. Register in metadata.json

You can also do this via HTTP:
```bash
curl -X POST http://localhost:9876/voices/from-elevenlabs \
  -H "Content-Type: application/json" \
  -d '{"voice_id": "saga-comms", "elevenlabs_voice_id": "c7qAAWgc7aGYHCLDzd8Y"}'
```

### Flow B: Upload your own ref WAV

```bash
voice-forge voice add saga-comms /path/to/my-ref.wav \
  --ref-text "The transcript exactly matching the audio." \
  --backend neutts
```

If you don't provide `--ref-text`, voice-forge Whisper-transcribes it for you.

## Refining a ref that doesn't work

If a freshly-registered voice produces gibberish or wrong-character output, try:

1. **Re-trim to a tighter sentence boundary**:
   ```bash
   voice-forge voice retrim saga-comms --max-seconds 10
   ```
2. **Force a different language hint** if the ref has accent / non-English phonemes:
   ```bash
   voice-forge voice retrim saga-comms --language en
   ```
3. **Manually edit the ref_text** if Whisper got it wrong:
   ```bash
   $EDITOR ~/.voice-forge/voices/saga-comms/ref.txt
   # re-register: voice-forge will pick up the new text
   ```
4. **Try a different source clip** — the ElevenLabs preview might be a longer reading; the first 14s might not be the best 14s. Pull again with `--trim-start` to skip the opening.

## Reference WAV requirements

| Backend | Min duration | Max duration | Format |
|---|---|---|---|
| NeuTTS Air | 3 sec | 15 sec | 24kHz mono WAV |
| F5-TTS | 8 sec | 15 sec | 24kHz mono WAV |
| XTTS-v2 | 6 sec | 30 sec | 24kHz mono WAV |
| Dia | 5 sec | unbounded | 24kHz mono WAV |
| Kokoro | n/a | n/a | uses preset_id, not ref WAV |
| Kitten | n/a | n/a | uses preset_id, not ref WAV |

voice-forge enforces the backend-appropriate range when you register.

## Voice metadata

Each voice's `metadata.json` carries:

```json
{
  "voice_id": "saga-comms",
  "backend": "neutts",
  "model": "neuphonic/neutts-air-q8-gguf",
  "language": "en",
  "description": "Saga — history-keeper, dry-witted",
  "source": "elevenlabs:c7qAAWgc7aGYHCLDzd8Y",
  "ref_audio_path": "ref.wav",
  "ref_text_path": "ref.txt",
  "duration_sec": 9.20,
  "created_at": "2026-05-24T17:30:00Z",
  "sampling": {
    "temperature": 1.0,
    "top_k": 50,
    "repeat_penalty": 1.05
  }
}
```

Sampling overrides are per-voice (the backend has defaults; this metadata can override).

## Future Voice Lab features

- **Voice Design** — generate new voices from text descriptions (ElevenLabs-style); requires backends that support this (XTTS-v2, ChatTTS, etc.)
- **Bulk import** — pull a whole ElevenLabs workspace at once
- **Speaker diarization** — split multi-speaker reference audio into per-speaker refs
- **Voice mixing** — interpolate between two reference voices to create a new one (where backend supports — Kokoro syntax)
- **A/B audition UI** — browse voices in a TUI, generate test samples, compare

Tracked in [ROADMAP.md](ROADMAP.md).
