"""Fleet config loader for the voice_design pipeline.

A ``fleet.yaml`` declares one or more persona voices the user wants to
manage via Voice Design. Each entry pairs a voice_id (used by
voice-forge's registry) with an ElevenLabs voice_id (after audition) and
the structured Voice Design spec needed to regenerate it.

This module loads + validates fleet files. It is intentionally generic
— it knows nothing about specific personas. The user's actual fleet
data lives outside the installed package (e.g. ``personas/asgard/``);
the loader works on any directory that holds a ``fleet.yaml`` shaped
per :class:`PersonaSpec` below.

Schema
------
.. code-block:: yaml

   personas:
     - voice_id: freya-pa
       display_name: Freya
       elevenlabs_voice_id: CBEzlSXhnIFLk379R1mo  # null = not yet auditioned
       voice_engineering:
         language: "Native Norwegian speaker speaking English"
         gender: female
         age: "early 40s"
         audio_quality: "Perfect"
         accent: "Thick Norwegian accent (Bokmål-rooted — not Swedish, not Danish)"
         pitch: "Warm contralto, mid-low pitch"
         pace: "Slow, deliberate pacing"
       persona:
         role: "Vanir goddess of magic, love, war, and foresight"
         emotion: "warm, confident, measured"
         style: "Soft on the surface, steel underneath. No uptalk."
       sample_text: |
         Good morning. You have three things on the calendar today...
       # Optional — defaults to <fleet_dir>/<voice_id>/{ref.wav,ref.txt}
       ref_audio: freya-pa/ref.wav
       ref_text: freya-pa/ref.txt
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class PersonaSpec:
    """One persona's Voice Design + reference-audio config."""

    voice_id: str
    display_name: str
    elevenlabs_voice_id: str | None
    voice_engineering: dict[str, str]
    persona: dict[str, str]
    sample_text: str
    ref_audio: Path
    ref_text: Path
    extra: dict[str, Any] = field(default_factory=dict)

    def has_ref_audio(self) -> bool:
        return self.ref_audio.is_file()

    def has_been_auditioned(self) -> bool:
        return bool(self.elevenlabs_voice_id)

    def design_spec(self) -> dict[str, Any]:
        """Shape expected by :func:`prompt_builder.build_voice_design_prompt`."""
        return {"voice_engineering": dict(self.voice_engineering), "persona": dict(self.persona)}


@dataclass(frozen=True)
class Fleet:
    """A loaded fleet: per-persona specs + the directory they came from."""

    root: Path
    personas: list[PersonaSpec]

    def by_voice_id(self, voice_id: str) -> PersonaSpec:
        for p in self.personas:
            if p.voice_id == voice_id:
                return p
        known = ", ".join(p.voice_id for p in self.personas)
        raise KeyError(f"voice_id {voice_id!r} not in fleet (have: {known})")

    def by_display_name(self, name: str) -> PersonaSpec:
        for p in self.personas:
            if p.display_name.lower() == name.lower():
                return p
        known = ", ".join(p.display_name for p in self.personas)
        raise KeyError(f"display_name {name!r} not in fleet (have: {known})")


def load_fleet(fleet_yaml: Path) -> Fleet:
    """Load + validate a fleet.yaml. ``fleet_yaml`` is an absolute path.

    Per-persona ``ref_audio`` / ``ref_text`` paths default to
    ``<fleet_dir>/<voice_id>/{ref.wav,ref.txt}`` if the YAML doesn't
    specify them. They're resolved relative to the fleet directory.
    """
    fleet_yaml = Path(fleet_yaml).expanduser().resolve()
    if not fleet_yaml.is_file():
        raise FileNotFoundError(f"fleet config not found: {fleet_yaml}")
    root = fleet_yaml.parent
    raw = yaml.safe_load(fleet_yaml.read_text()) or {}
    persona_rows = raw.get("personas") or []
    if not isinstance(persona_rows, list):
        raise ValueError(f"{fleet_yaml}: 'personas' must be a list")

    specs: list[PersonaSpec] = []
    seen_ids: set[str] = set()
    for i, row in enumerate(persona_rows):
        if not isinstance(row, dict):
            raise ValueError(
                f"{fleet_yaml}: personas[{i}] must be a mapping; got {type(row).__name__}"
            )
        voice_id = row.get("voice_id")
        if not voice_id:
            raise ValueError(f"{fleet_yaml}: personas[{i}] missing required 'voice_id'")
        if voice_id in seen_ids:
            raise ValueError(f"{fleet_yaml}: duplicate voice_id {voice_id!r}")
        seen_ids.add(voice_id)
        display_name = row.get("display_name") or voice_id
        eleven_id = row.get("elevenlabs_voice_id")
        # Treat the home-lab placeholder sentinel as "not yet auditioned"
        # for compatibility with old fleet snapshots imported as-is.
        if isinstance(eleven_id, str) and eleven_id.startswith("PLACEHOLDER"):
            eleven_id = None
        engineering = row.get("voice_engineering") or {}
        persona = row.get("persona") or {}
        sample = row.get("sample_text") or ""
        ref_audio_rel = row.get("ref_audio") or f"{voice_id}/ref.wav"
        ref_text_rel = row.get("ref_text") or f"{voice_id}/ref.txt"
        specs.append(
            PersonaSpec(
                voice_id=str(voice_id),
                display_name=str(display_name),
                elevenlabs_voice_id=eleven_id,
                voice_engineering={str(k): str(v) for k, v in engineering.items()},
                persona={str(k): str(v) for k, v in persona.items()},
                sample_text=str(sample),
                ref_audio=(root / ref_audio_rel).resolve(),
                ref_text=(root / ref_text_rel).resolve(),
                extra={
                    k: v
                    for k, v in row.items()
                    if k
                    not in {
                        "voice_id",
                        "display_name",
                        "elevenlabs_voice_id",
                        "voice_engineering",
                        "persona",
                        "sample_text",
                        "ref_audio",
                        "ref_text",
                    }
                },
            )
        )

    return Fleet(root=root, personas=specs)
