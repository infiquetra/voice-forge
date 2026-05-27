"""Voice Design prompt construction with best-practices ordering baked in.

Best-practices rules
--------------------
1. **Voice-engineering specs come FIRST** (gender + age + accent + audio
   quality), persona color comes SECOND.

   Discovered the hard way: a personality-only prompt like
   *"calm, no-nonsense, dry"* returned 2 of 3 male voice candidates
   even for a female persona, because ElevenLabs Voice Design treats
   personality traits as gender-neutral and falls back to a male
   default if no explicit gender is stated. Always put
   ``Female, early 40s`` BEFORE any personality language. Same
   logic applies to age, accent, and audio quality.

2. **Audio quality is a free strength signal**. Including
   *"Perfect audio quality"* (or *"Studio-quality recording"*) at the
   top of the prompt nudges the generated voice toward cleaner samples
   that clone better with F5/NeuTTS. Skip it and the model sometimes
   produces realistic-but-noisy room-tone variants.

3. **Accent specificity matters**. *"Norwegian"* alone produces
   inconsistent results between Bokmål-rooted (the standard the user
   likely wants for Asgard-style personas) and Swedish/Danish defaults.
   Explicit constraint syntax that works: ``Thick Norwegian accent
   (Bokmål-rooted — not Swedish, not Danish)``. The negation
   *"not Swedish, not Danish"* genuinely changes the output.

4. **Persona color goes LAST**. Role, emotion, pitch, pacing,
   personality notes — these refine an already-locked engineering
   profile. If they come first the engineering parameters become
   advisory and the model picks defaults.

5. **Prompt cap is ~1000 chars**. ElevenLabs trims silently past
   that; ``trim_for_design_prompt`` cuts at the last sentence boundary
   in the budget to avoid mid-sentence truncation.

Schema
------
The structured spec mirrors the rule order:

.. code-block:: yaml

   voice_engineering:        # § ordered first by build_prompt()
     language: "Native Norwegian speaker speaking English"
     gender: female           # one of: female, male, neutral
     age: "early 40s"
     audio_quality: "Perfect"
     accent: "Thick Norwegian accent (Bokmål-rooted — not Swedish, not Danish)"
     pitch: "Warm contralto, mid-low pitch"
     pace: "Slow, deliberate pacing"

   persona:                   # § appended after engineering block
     role: "Vanir goddess of magic, love, war, and foresight"
     emotion: "warm, confident, measured"
     style: "Soft on the surface, steel underneath. No uptalk."

Any field can be omitted. ``build_voice_design_prompt`` produces a
single concatenated description suitable for the ``voice_description``
field of ``/v1/text-to-voice/create-previews``.

For backwards-compatible escape-hatch use, a raw string under ``casting``
bypasses the structured assembly and is used verbatim.
"""

from __future__ import annotations

from collections.abc import Mapping

VOICE_ENGINEERING_ORDER = (
    "language",
    "gender",
    "age",
    "audio_quality",
    "accent",
    "pitch",
    "pace",
)

PERSONA_ORDER = (
    "role",
    "emotion",
    "style",
)

PROMPT_CHAR_LIMIT = 1000
PROMPT_SAFETY_MARGIN = 50  # cut at limit-50 so trailing punctuation isn't lost


def trim_for_design_prompt(text: str, limit: int = PROMPT_CHAR_LIMIT - PROMPT_SAFETY_MARGIN) -> str:
    """Truncate to fit Voice Design's prompt cap, preferring sentence boundaries.

    If the trimmed prefix has a sentence break (``. ``) in its last 30 %,
    we cut there. Otherwise we hard-truncate — usually still produces a
    usable prompt because the engineering block is at the top.
    """
    if len(text) <= limit:
        return text
    cut = text[:limit]
    last_period = cut.rfind(". ")
    if last_period > limit * 0.7:
        return cut[: last_period + 1]
    return cut


def _fmt_gender_age(eng: Mapping[str, str]) -> str:
    """Format gender + age as a single clause (the most important sentence).

    ``Female, early 40s`` → keeps the order ElevenLabs reads cleanly.
    Falls back to gender alone or age alone if one is missing.
    """
    gender_map = {"female": "Female", "male": "Male", "neutral": "Person"}
    gender = gender_map.get(str(eng.get("gender", "")).lower())
    age = eng.get("age")
    if gender and age:
        return f"{gender}, {age}."
    if gender:
        return f"{gender}."
    if age:
        return f"Voice, {age}."
    return ""


def build_voice_design_prompt(spec: Mapping[str, object]) -> str:
    """Build a Voice Design prompt from a structured spec.

    Order of concatenation (best-practices §1–4):
        language → gender+age → audio_quality → accent → pitch → pace
        → persona.role → persona.emotion → persona.style

    Accepts either:
    - Structured spec: ``{"voice_engineering": {...}, "persona": {...}}``
    - Raw string: ``{"casting": "Native ..."}`` — used verbatim
    """
    raw = spec.get("casting")
    if isinstance(raw, str) and raw.strip():
        return trim_for_design_prompt(raw.strip())

    eng_in = spec.get("voice_engineering") or {}
    persona_in = spec.get("persona") or {}
    if not isinstance(eng_in, Mapping) or not isinstance(persona_in, Mapping):
        raise TypeError(
            "spec.voice_engineering and spec.persona must be mappings; "
            f"got {type(eng_in).__name__}, {type(persona_in).__name__}"
        )

    parts: list[str] = []

    # § 1. Voice-engineering block — order MATTERS.
    if lang := eng_in.get("language"):
        parts.append(f"{str(lang).strip().rstrip('.')}.")
    if ga := _fmt_gender_age(eng_in):
        parts.append(ga)
    if quality := eng_in.get("audio_quality"):
        q = str(quality).strip().rstrip(".")
        # Don't repeat the word "quality" — "Perfect audio quality." reads
        # better than just "Perfect." Allow either form in the spec.
        if "quality" not in q.lower():
            q = f"{q} audio quality"
        parts.append(f"{q}.")
    if accent := eng_in.get("accent"):
        parts.append(f"{str(accent).strip().rstrip('.')}.")
    if pitch := eng_in.get("pitch"):
        parts.append(f"{str(pitch).strip().rstrip('.')}.")
    if pace := eng_in.get("pace"):
        parts.append(f"{str(pace).strip().rstrip('.')}.")

    # § 2. Persona color — comes after engineering.
    if role := persona_in.get("role"):
        parts.append(f"Persona: {str(role).strip().rstrip('.')}.")
    if emotion := persona_in.get("emotion"):
        parts.append(f"Emotion: {str(emotion).strip().rstrip('.')}.")
    if style := persona_in.get("style"):
        parts.append(str(style).strip().rstrip(".") + ".")

    if not parts:
        raise ValueError("spec produced empty prompt — provide voice_engineering or persona fields")

    return trim_for_design_prompt(" ".join(parts))


# Public re-export of the best-practices doc, useful for CLI ``--show-best-practices``
# and for docs/voice-design-guide.md rendering.
BEST_PRACTICES = __doc__
