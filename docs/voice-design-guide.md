# Voice Design Guide

How to build persona voices for voice-forge using ElevenLabs Voice
Design — what works, what doesn't, and the prompt-engineering rules
that took experimentation to discover.

This guide is generic. It does NOT cover any specific persona set;
for a worked example fleet, see `personas/asgard/fleet.yaml` (the
maintainer's own Asgard fleet, used as a reference implementation
of the schema).

## When to use this

You need a persona voice (for cloning into F5/NeuTTS/XTTS/Chatterbox)
and one of:

- you want to control accent precisely (regional English, Nordic,
  Hindi-accented English, etc.);
- you don't want to use a real person's voice (consent / legal /
  ethical reasons);
- you want the persona's voice to match a specific character brief
  (mature warm baritone counselor, brisk young efficient travel
  agent, dry-witted history archivist, …).

Voice Design generates a synthetic voice that isn't derived from any
specific identifiable person, so it sidesteps the consent question
that comes with cloning real speakers. The resulting `voice_id` is
yours to use in your ElevenLabs library; you can then either render
text through it directly (good for production NeuTTS-style use) or
use a short rendered clip as a reference WAV for F5/NeuTTS cloning
(good when you want offline + lower latency).

## The four rules

These came out of real audition failures during the Asgard fleet
buildout. The first one cost a wasted batch of generations.

### Rule 1 — voice-engineering FIRST, persona color SECOND

A personality-only prompt like *"calm, no-nonsense, dry"* returns
gender-defaulted results from ElevenLabs Voice Design — typically
**male**, even for an unambiguously-female-persona brief. The model
treats abstract personality language as gender-neutral.

Always put gender + age + accent + audio quality at the **top** of
the prompt:

> **Bad:** *"Calm, precise, quietly authoritative archivist. Speaks
> less than she reads."*
>
> Result: 2 of 3 previews come back male.

> **Good:** *"Native Norwegian speaker speaking English. Female,
> mid-30s. Perfect audio quality. Thick Norwegian accent (Bokmål-
> rooted — not Swedish, not Danish). Persona: archivist who has
> read every letter ever written. Calm, precise, quietly
> authoritative."*
>
> Result: all 3 previews are female, all 3 are Nordic-accented,
> variance is in micro-emotion.

The `prompt_builder.build_voice_design_prompt` function enforces
this order automatically — fields are concatenated as
`language → gender → age → audio_quality → accent → pitch → pace`
then persona `role → emotion → style`. Don't try to be clever and
override the order.

### Rule 2 — "Perfect audio quality" is free signal

Including `audio_quality: Perfect` (or `"Studio-quality recording"`)
at the top of the prompt nudges Voice Design toward cleaner samples.
Without it, the model sometimes generates realistic-but-noisy room-
tone variants that look authentic but **clone badly** through F5 —
the room noise is baked into the reference and infects every clone.

Use it. It costs zero characters of meaningful prompt budget and
materially improves downstream cloning quality.

### Rule 3 — accent specificity matters

Naming a language family is not enough. *"Norwegian accent"* alone
produces inconsistent results across Bokmål / Nynorsk / Swedish /
Danish defaults. The model's training distribution is dominated by
the geographically-largest accent in each region, which is often
NOT what you want.

Two specificity boosters that demonstrably work:

1. **Constrained accent specs** — e.g.
   `"Thick Norwegian accent (Bokmål-rooted — not Swedish, not Danish)"`.
   The negation **"not X, not Y"** is real signal to the model and
   genuinely changes the output. It looks redundant. It isn't.

2. **Intensity adjective** — `thick`, `light`, `heavy`. Default
   without an adjective is somewhere between "slight" and "moderate"
   — usually too subtle for the cloning backends to preserve through
   F5/NeuTTS encoding.

If you want the accent to **survive cloning**, lean harder than
you'd think necessary. *"Thick"* in the Voice Design prompt becomes
roughly *"moderate"* in the rendered audio, becomes roughly *"light"*
in an F5 clone of the rendered audio.

### Rule 4 — persona color goes LAST

Personality, emotion, pacing notes, character framing — these refine
an **already-locked** engineering profile. Put them after the engineering
block. If you put them first, the engineering parameters become
advisory and the model picks defaults.

The structured spec enforces this:

```yaml
voice_engineering:    # — built first
  language: ...
  gender: ...
  age: ...
  audio_quality: ...
  accent: ...
  pitch: ...
  pace: ...

persona:              # — appended after
  role: ...
  emotion: ...
  style: ...
```

## Schema

Each persona in `fleet.yaml`:

```yaml
- voice_id: narrator-warm-male
  display_name: Narrator
  elevenlabs_voice_id: null            # filled in after audition

  voice_engineering:
    language: "Native English speaker"  # what they speak natively
    gender: male                        # female | male | neutral
    age: "mid-40s"                      # freeform — be specific
    audio_quality: Perfect              # free signal; always include
    accent: "Slight West-coast US"      # be SPECIFIC; lean THICK
    pitch: "Warm baritone, mid-low"     # freeform
    pace: "Measured; comfortable"       # freeform

  persona:
    role: "Audiobook narrator"          # role/identity in one line
    emotion: "warm, present, calm"      # delivery quality
    style: "Long-form-friendly..."      # any additional notes

  sample_text: |                        # what the previews will speak
    A clear, paragraph-length sample
    in the voice you want to test...
```

All fields are optional — but **gender, age, accent are practically
required** if you want predictable output. The omissions you'll
notice fastest are gender (defaults male) and accent (defaults
geographic-majority).

## Sample-text guidance

The sample_text is what the 3 preview voices will speak — choose it
carefully:

- **Length: 200–600 chars.** Short enough that auditioning 3 is
  pleasant; long enough that you can hear pace and emotion
  variation, not just timbre.
- **In-character.** Use a sentence the persona would actually say.
  This makes "is this the right voice?" much easier to answer than
  a generic *"The quick brown fox…"*.
- **Include the hard sounds.** If the accent has signature
  consonants (Norwegian `r`, French nasals, German `ch`) make sure
  the sample has at least one occurrence.
- **End with a definitive sentence.** A trailing question mark or
  ellipsis biases the model toward uptalk; flat statements end-
  on-period give you a cleaner read.

## What to do with the chosen voice

After Voice Design picks and persists, you have an
`elevenlabs_voice_id`. Two paths:

1. **Use it directly via ElevenLabs.** Render speech through it at
   call time. Highest quality, lowest setup, requires API access and
   credits per call.

2. **Use it as the source of a reference clip for offline cloning.**
   Run `voice-design regen` to render a 12-second `ref.wav` of the
   sample_text through the voice. Drop into voice-forge's registry.
   F5 / NeuTTS / XTTS / Chatterbox clone the reference at synth
   time. Offline, lower per-call cost, slight quality drop.

The Asgard fleet uses path 2 (offline cloning).

## Common failure modes

- **2-of-3 wrong-gender results.** → Rule 1 violation. Move gender
  to the top of the prompt.
- **All 3 previews sound similar but none have the accent.** → Rule
  3 violation. Use a thicker accent adjective + the "not X, not Y"
  negation.
- **Voice sounds right but F5 clones it without accent.** → Either
  (a) the reference WAV is bandwidth-limited (centroid below ~1 kHz
  — check with `ffprobe`), regenerate with `voice-design regen`;
  or (b) Voice Design's accent was too subtle to survive F5's
  encoder, redo the audition with `thick` / `heavy` instead of the
  current adjective.
- **Voice has the right accent but wrong pace.** → ElevenLabs Voice
  Design doesn't reliably honor pace specs in the prompt. The
  rendered audio's pace is mostly determined by the sample_text's
  punctuation and length. Adjust the sample_text, not the prompt.

## Cost budget

ElevenLabs Voice Design (`/v1/text-to-voice/create-previews`) charges
character cost: roughly sample_text length × 3 previews per audition,
plus a small per-call overhead. For a 600-char sample, that's
~1,800–2,000 chars per audition × N personas. The Creator plan
(100k chars/month) comfortably handles a 10-persona fleet with room
for ~5–10 re-audition rounds per persona.

Saved voices (`/v1/text-to-voice/create-voice-from-preview`) are
free. Subsequent rendering through the saved voice
(`/v1/text-to-speech/{voice_id}`) is metered at standard TTS rates.

## CLI reference

See `scripts/voice_design.py --help` and per-subcommand help. The
four subcommands are:

| Subcommand | Purpose |
|---|---|
| `list` | Show all personas in a fleet with audition status |
| `show` | Print the rendered Voice Design prompt for a persona (no API calls) |
| `audition` | Generate 3 previews per persona, pick one interactively, persist the voice_id |
| `regen` | Re-render the reference WAV for an already-auditioned persona |

## Python API

The same operations are available programmatically:

```python
from pathlib import Path
from voice_forge.voice_design import (
    load_fleet, build_voice_design_prompt,
    audition_persona, pick_auto,
)

fleet = load_fleet(Path("personas/asgard/fleet.yaml"))
spec = fleet.by_voice_id("mimir-engineer")

# Sanity-check the prompt before spending an audition
prompt = build_voice_design_prompt(spec.design_spec())
print(prompt)

# Run audition (interactive picker by default)
result = audition_persona(
    spec,
    out_dir=Path("~/voice-auditions").expanduser(),
)
print(result.persisted_voice_id)
```

See `src/voice_forge/voice_design/__init__.py` for the full public
surface.
