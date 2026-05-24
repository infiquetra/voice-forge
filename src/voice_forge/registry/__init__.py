"""FS-backed voice registry.

Each voice lives at ~/.voice-forge/voices/<voice_id>/ with:
  - ref.wav        (reference audio for cloning backends; absent for preset-voice backends)
  - ref.txt        (matching transcript; absent for preset-voice backends)
  - metadata.json  ({backend, model, language, description, source, ...})

Phase D fills out the implementation. This file is a skeleton.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from ..backends import VoiceRef


DEFAULT_REGISTRY_DIR = Path(os.environ.get("VOICE_FORGE_REGISTRY", "~/.voice-forge/voices")).expanduser()


class Registry:
    """FS-backed voice registry."""

    def __init__(self, root: Path | str = DEFAULT_REGISTRY_DIR) -> None:
        self.root = Path(root).expanduser()
        self.root.mkdir(parents=True, exist_ok=True)

    def list(self) -> list[VoiceRef]:
        """List all registered voices."""
        # TODO Phase D
        raise NotImplementedError

    def get(self, voice_id: str) -> VoiceRef:
        """Look up a voice by ID. Raises KeyError if not found."""
        # TODO Phase D
        raise NotImplementedError

    def register(
        self,
        voice_id: str,
        ref_audio_path: str | None,
        ref_text: str | None,
        backend: str,
        metadata: dict,
    ) -> VoiceRef:
        """Add a new voice. Raises FileExistsError if voice_id already registered."""
        # TODO Phase D: copy ref_audio + write metadata.json
        raise NotImplementedError

    def delete(self, voice_id: str) -> None:
        """Remove a voice from registry. Idempotent."""
        # TODO Phase D
        raise NotImplementedError
