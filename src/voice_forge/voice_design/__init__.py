"""Voice Design module — create + manage persona voices via ElevenLabs.

This package is generic (no persona-specific data). Users supply a
``fleet.yaml`` describing the personas they want; the module:

- builds Voice Design prompts with best-practices ordering
  (gender/age/accent FIRST, persona color SECOND) — see
  :mod:`voice_forge.voice_design.prompt_builder` for the rules and the
  reasons we follow them.
- auditions each persona against ElevenLabs Voice Design and persists
  the chosen preview as a permanent voice (:mod:`audition`).
- regenerates reference WAVs for an already-persisted voice via the
  standard TTS endpoint (:mod:`elevenlabs.text_to_speech`).

Quick start (Python):

.. code-block:: python

    from pathlib import Path
    from voice_forge.voice_design import load_fleet, audition_persona, pick_auto

    fleet = load_fleet(Path("personas/asgard/fleet.yaml"))
    spec = fleet.by_voice_id("freya-pa")
    result = audition_persona(
        spec,
        out_dir=Path("~/voice-auditions").expanduser(),
        picker=pick_auto,  # or pick_interactive
    )
    print(result.persisted_voice_id)  # → 'CBEzlSXhnIFLk379R1mo' (or similar)

Quick start (CLI):

.. code-block:: bash

    export ELEVENLABS_API_KEY=sk-...
    voice-design audition --fleet personas/asgard/fleet.yaml --persona freya
    voice-design regen --fleet personas/asgard/fleet.yaml --persona freya

See ``docs/voice-design-guide.md`` for the best-practices rules and
examples in full.
"""

from __future__ import annotations

from .audition import (
    AuditionResult,
    audition_persona,
    generate_previews_only,
    persist_preview,
    pick_auto,
    pick_interactive,
)
from .elevenlabs import (
    ElevenLabsError,
    Preview,
    create_voice_from_preview,
    create_voice_previews,
    text_to_speech,
)
from .fleet import Fleet, PersonaSpec, load_fleet
from .prompt_builder import (
    BEST_PRACTICES,
    build_voice_design_prompt,
    trim_for_design_prompt,
)

__all__ = [
    "AuditionResult",
    "BEST_PRACTICES",
    "ElevenLabsError",
    "Fleet",
    "PersonaSpec",
    "Preview",
    "audition_persona",
    "build_voice_design_prompt",
    "generate_previews_only",
    "persist_preview",
    "create_voice_from_preview",
    "create_voice_previews",
    "load_fleet",
    "pick_auto",
    "pick_interactive",
    "text_to_speech",
    "trim_for_design_prompt",
]
