"""Auto-register persona × cloning-backend coverage at startup.

The voice-lab UI (`/lab`) wants every persona present in every installed
cloning backend so the comparison matrix is complete. Manually registering
N personas × M backends = N*M `voice add` invocations gets old fast, and is
the same operation every time: take the persona's canonical ref WAV +
transcript, register it under a backend-suffixed voice_id.

This module reads ``tests/functional/fleet.yaml`` (when present), iterates
the personas, and creates any missing ``<canonical_voice>-<backend>`` entries
in the registry. Idempotent — running it twice creates nothing new.

**Opt-in by file presence.** When fleet.yaml is absent (the case for any
voice-forge install outside our home-lab dev environment), ``ensure_full_coverage``
is a no-op. Voice-forge runtime never imports anything home-lab-specific;
fleet.yaml itself is just a JSON list of personas that, if it exists,
voice-forge consumes. The sync script that writes it (`scripts/sync_fleet_from_home_lab.py`)
is a personal dev tool, not a voice-forge feature.

**Cloning backends only.** Preset-voice backends (kokoro, piper, melotts) get
their voices via the preset sampler / explicit `voice add --preset ...`,
not via persona cloning.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from .backends import known_backends, load_backend_module
from .registry import Registry

logger = logging.getLogger("voice_forge.persona_coverage")

# Backends that accept a ref WAV + transcript. Preset backends (kokoro/piper/melotts)
# are explicitly excluded — they use the preset sampler surface instead.
CLONING_BACKENDS: tuple[str, ...] = ("f5", "neutts", "xtts", "dia", "chatterbox")


def _is_backend_installed(name: str) -> bool:
    """Try to import the backend module; True iff successful.

    We don't load the model — just check that the Python package is importable.
    Cheap (a few hundred ms first call, cached afterwards).
    """
    try:
        load_backend_module(name)
    except (ImportError, KeyError):
        return False
    return True


def ensure_full_coverage(registry: Registry, fleet_path: Path | str | None = None) -> dict:
    """Register any missing persona × cloning-backend combos in the registry.

    Args:
        registry: a voice_forge Registry instance bound to the target root.
        fleet_path: path to ``tests/functional/fleet.yaml`` or equivalent.
            When ``None`` OR the file doesn't exist, the call is a no-op and
            returns ``{"skipped": "no fleet.yaml at <path>"}``.

    Returns:
        Summary dict with keys:
            ``created``        — list of new voice_ids that were registered
            ``skipped_existing`` — list of voice_ids that already existed
            ``skipped_missing_ref`` — list of (persona, backend) tuples we
                couldn't register because the persona's canonical voice
                had no ref.wav on disk
            ``skipped_backend_not_installed`` — list of backend names that
                aren't installed in this environment (no pip extra)
            ``skipped``         — present iff the whole call was a no-op

    Behaviour notes:
        - The "canonical voice" for a persona is the ``voice_id`` field in
          fleet.yaml — e.g., ``saga-comms`` for persona ``saga``. That's the
          NeuTTS-default voice; the per-other-backend variants are
          ``<canonical_voice>-<backend>``.
        - Idempotent: if ``<canonical_voice>-<backend>`` already exists in
          the registry, nothing happens for that pair.
        - The canonical voice itself is NOT auto-created; if it's missing,
          all per-backend variants for that persona land in
          ``skipped_missing_ref``.
    """
    summary: dict[str, Any] = {
        "created": [],
        "skipped_existing": [],
        "skipped_missing_ref": [],
        "skipped_backend_not_installed": [],
    }

    if fleet_path is None:
        summary["skipped"] = "no fleet_path provided"
        return summary
    fleet_path = Path(fleet_path).expanduser()
    if not fleet_path.is_file():
        summary["skipped"] = f"fleet.yaml not found at {fleet_path}"
        return summary

    try:
        fleet = yaml.safe_load(fleet_path.read_text())
    except (yaml.YAMLError, OSError) as exc:
        summary["skipped"] = f"fleet.yaml unreadable: {exc!r}"
        return summary

    if not isinstance(fleet, list):
        summary["skipped"] = f"fleet.yaml top-level is not a list (got {type(fleet).__name__})"
        return summary

    # Precompute which backends are actually installed so we can short-circuit
    # the inner loop. Backends known but not installed go in their own bucket
    # so the caller can surface "install [chatterbox] to fill these rows".
    installed = {b: _is_backend_installed(b) for b in CLONING_BACKENDS if b in known_backends()}
    for backend_name, ok in installed.items():
        if not ok:
            summary["skipped_backend_not_installed"].append(backend_name)

    for persona_entry in fleet:
        if not isinstance(persona_entry, dict):
            continue
        canonical_voice_id = persona_entry.get("voice_id")
        if not canonical_voice_id:
            continue
        try:
            canonical = registry.get(canonical_voice_id)
        except KeyError:
            # Persona has no canonical voice in registry — record one
            # skipped-missing per backend and move on
            for backend_name, ok in installed.items():
                if ok:
                    summary["skipped_missing_ref"].append((canonical_voice_id, backend_name))
            continue
        if not canonical.ref_audio_path or not Path(canonical.ref_audio_path).is_file():
            for backend_name, ok in installed.items():
                if ok:
                    summary["skipped_missing_ref"].append((canonical_voice_id, backend_name))
            continue

        for backend_name, ok in installed.items():
            if not ok:
                continue
            # If the canonical voice ALREADY uses this backend, don't create
            # a redundant ``<canonical>-<backend>`` row. Example: saga-comms
            # is the neutts canonical; we don't want a saga-comms-neutts twin.
            if canonical.backend == backend_name:
                summary["skipped_existing"].append(canonical_voice_id)
                continue
            variant_voice_id = f"{canonical_voice_id}-{backend_name}"
            if registry.exists(variant_voice_id):
                summary["skipped_existing"].append(variant_voice_id)
                continue
            try:
                registry.register(
                    voice_id=variant_voice_id,
                    ref_audio_path=canonical.ref_audio_path,
                    ref_text=canonical.ref_text,
                    backend=backend_name,
                    metadata={
                        "language": canonical.metadata.get("language", "en"),
                        "description": (
                            f"Auto-registered from {canonical_voice_id} "
                            f"for /lab persona × backend coverage"
                        ),
                        "persona": canonical.metadata.get("persona", canonical_voice_id),
                    },
                )
                summary["created"].append(variant_voice_id)
            except Exception as exc:
                logger.warning(
                    "ensure_full_coverage: failed to register %r: %r",
                    variant_voice_id,
                    exc,
                )

    return summary
