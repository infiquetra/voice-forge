# Asgard audition harness

A manual, ear-driven verification of every sister voice in the Asgard fleet. Not run by `pytest` — invoke `scripts/asgard_audition.py` and open the generated HTML in a browser to listen.

## Why this exists

Unit tests catch shape and contract regressions. They don't catch:

- Timbre drift after a NeuTTS / Kokoro upgrade
- Voice cloning quality degradation
- Long-utterance coherence cliffs (NeuTTS-Air rots noticeably past ~30 seconds)
- Repeat-penalty / sampling parameter regressions that affect prosody

Listening to 27 WAVs (9 sisters × 3 prompts) catches all of those by ear in under a minute.

## What gets produced

```
tests/functional/output/{run_id}/
├── freya-pa_p1_hear_me.wav, freya-pa_p2_who_are_you.wav, freya-pa_p3_story.wav
├── saga-comms_p1_hear_me.wav, ...
│   ... (9 sisters × 3 prompts = 27 WAVs)
└── index.html   ← <audio controls> per row, grouped by sister
```

`output/` is gitignored — every run is reproducible from the inputs.

## Inputs

- `fleet.yaml` — **generated** by `scripts/sync_fleet_from_home_lab.py`. Lists the 9 Asgard sisters with their voice_id (matches what's registered in `~/.voice-forge/voices/`), backend, and a unique Norse-god `target_agent` for prompt 3.
- `prompts.yaml` — hand-authored, 3 prompt templates per sister:
  - `p1_hear_me`: "Can you hear me?" — sanity check
  - `p2_who_are_you`: "{response_p2}" — ~30s self-introduction
  - `p3_story`: "{response_p3}" — free-form anecdote naming the target_agent
- `responses.yaml` — pre-captured persona responses. Hand-edit when persona text drifts. Each entry carries a `captured:` date that appears in the HTML so reviewers know how stale the text is.

## Prerequisites

1. **Install voice-forge** locally:
   ```bash
   uv pip install "voice-forge-tts[neutts,kokoro,voice-lab]"
   brew install espeak-ng    # for Kokoro
   ```

2. **Register the sister voices**. The audition only synthesizes; it doesn't create voices. Run once on a fresh machine:
   ```bash
   export ELEVENLABS_API_KEY=...
   for sister in freya-pa saga-comms gersemi-time hnoss-books eir-wellness \
                 beyla-travel heid-research bygul-procurement trjegul-skeptic; do
       voice-forge voice from-elevenlabs --voice-id "$sister" --elevenlabs-voice-id "<el id>"
   done
   ```
   (The infiquetra/home-lab Ansible role handles this automatically on the Mac mini production host.)

3. **Refresh `responses.yaml`** if you're auditioning a real persona drift — see the procedure inside the file.

## Run

```bash
python scripts/asgard_audition.py
# OR with custom paths:
python scripts/asgard_audition.py --output tests/functional/output/2026-06-01-pre-tag
```

The script:

1. Starts `voice-forge serve --host 127.0.0.1 --port 9876` in the background.
2. Polls `/health` until 200 (up to 60s for cold model load).
3. For each fleet row × each prompt, fills the template and POSTs to `/v1/audio/speech`. Writes the WAV body to `output/{run_id}/{voice_id}_{prompt_id}.wav`.
4. Generates `output/{run_id}/index.html` with `<audio controls>` rows grouped by sister, plus the `captured:` date footer per row.
5. Sends SIGTERM to the server subprocess.

If a voice isn't registered locally, the corresponding row shows `(not registered)` in the HTML and no WAV is written — the rest of the run still completes.

## Review

```bash
open tests/functional/output/{run_id}/index.html
```

What to listen for:

- **p1 ("Can you hear me?")** should sound clean on every sister. Static, clicks, or stutters indicate a regression.
- **p2 (30-second introduction)** WILL show degradation on NeuTTS sisters past ~25-30 seconds. This is the documented NeuTTS-Air coherence cliff. **Audible noise, gibberish, or skipped words after ~30s is expected.** If you need clean long-form output, edge TTS or a future v0.3+ backend (VibeVoice, F5) is the alternative.
- **p3 (story)** should sound like the sister's persona, mention her `target_agent` naturally, and maintain clone fidelity throughout. Look (listen) for: timbre consistency vs the v0.1 baseline, prosody on proper nouns, correct pronunciation of "Loki" / "Heimdall" etc.

## Refreshing responses.yaml

When personas evolve in hermes-agent, the cached responses go stale. To refresh:

1. For each sister, ask the live persona:
   - "In about 30 seconds, tell me who you are."
   - "Tell me an old story about you and `<target_agent>`."
2. Paste each response into the matching `p2:` / `p3:` slot under the sister's ID in `responses.yaml`.
3. Bump the `captured:` date to today.
4. Commit the refreshed file separately so the diff is reviewable.

The harness will use whatever text is in the file. No silent fallbacks. If a sister is missing entries, the corresponding rows show `(no response cached)` in the HTML.

## Adding a new sister

1. Add the persona to home-lab's `roles/hermes_neutts_daemon/defaults/main.yml :: neutts_daemon_personas`.
2. Re-run `python scripts/sync_fleet_from_home_lab.py --home-lab-path ~/workspace/infiquetra/home-lab`.
3. The new sister appears in `fleet.yaml` with a new Norse-god target.
4. Add entries for the new sister to `responses.yaml`.
5. Commit both files. Re-run the audition.
