# personas/asgard/

The Asgard fleet — Jeff's personal Voice-Designed voice set, 10 personas
(9 Norse sister goddesses + Mimir, the engineering counselor).

## What's here

- `fleet.yaml` — declarative spec for all 10 personas: voice_id,
  elevenlabs_voice_id, structured Voice Design fields, sample_text.
  Source of truth — every other artifact derives from this.
- `<voice_id>/ref.wav` — 24 kHz mono reference clip used by F5 / NeuTTS
  / XTTS / Chatterbox cloning backends. 9 sisters have one; Mimir is
  awaiting Voice Design audition (so his directory is empty).
- `<voice_id>/ref.txt` — exact transcript of `ref.wav`. F5 uses this
  for phoneme alignment; a mismatch degrades cloning fidelity.

## Provenance

Migrated 2026-05-26 from `infiquetra/home-lab`:
- VOICE_CASTING + SAMPLE_TEXT entries from
  `ansible/roles/hermes/files/asgard_voice_design/design_voices.py`
- 9 reference WAVs from
  `ansible/roles/hermes_neutts_daemon/files/persona_refs/`
- ElevenLabs voice IDs from
  `ansible/inventory/host_vars/jeffs-mac-mini.infiquetra.com.yml`

Mimir's spec is new — drafted from
`ansible/roles/hermes/files/souls/mimir.md`. He has not been Voice
Designed yet; run:

```bash
export ELEVENLABS_API_KEY=sk-...
python scripts/voice_design.py audition \
    --fleet personas/asgard/fleet.yaml --persona mimir-engineer
```

This auditions Mimir against ElevenLabs, lets you pick from 3 previews,
and writes the chosen voice_id back into `fleet.yaml`.

## To regenerate a reference WAV

`fleet.yaml` already has the elevenlabs_voice_id for the 9 sisters, so
you can re-render any of their reference clips against the same
ElevenLabs voice (useful if the original was bandwidth-limited or you
want a different sample sentence):

```bash
export ELEVENLABS_API_KEY=sk-...
python scripts/voice_design.py regen \
    --fleet personas/asgard/fleet.yaml --persona freya-pa
```

This calls `/v1/text-to-speech/{voice_id}` with the persona's
`sample_text` (or a `--text` override), writes the result as
24 kHz mono PCM into `freya-pa/ref.wav`, and updates `ref.txt`
to match. After regen, restart voice-forge so its F5/NeuTTS backends
drop their cached encoded references.

## Why this is in the repo but not the package

These voices are Jeff's. They reference his ElevenLabs account, his
persona designs, and his Norse-mythology framing. They are NOT a
template — every voice-forge user has their own set.

The repo carries them because the maintainer's day-to-day voice-forge
work uses them, and they're a useful concrete example of the fleet
schema for anyone reading the code. But they are excluded from the
wheel + sdist, so `pip install voice-forge-tts` doesn't drag them
into other users' installs.

See `pyproject.toml :: [tool.hatch.build.targets.wheel]` for the
exclusion (the wheel includes only `src/voice_forge/`).
