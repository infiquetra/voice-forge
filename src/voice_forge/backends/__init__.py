"""TTS backend abstractions.

The TTSBackend Protocol is the contract any backend must implement.
The VoiceRef union dataclass carries the variance between backends
(ref WAV for NeuTTS/F5/XTTS/Dia vs preset_id for Kokoro/Kitten).

See docs/ARCHITECTURE.md § "Core abstractions" for the full design.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

import numpy as np


@dataclass
class VoiceRef:
    """Describes a voice to a backend.

    Different backends use different fields:
    - NeuTTS:  (encoded_codes or encode_reference(ref_audio_path), ref_text)
    - XTTS:    ref_audio_path
    - F5-TTS:  ref_audio_path
    - Kokoro:  preset_id
    - Kitten:  preset_id
    - Dia:     ref_audio_path (audio prompt)
    """

    voice_id: str
    backend: str
    ref_audio_path: str | None = None
    ref_text: str | None = None
    preset_id: str | None = None
    encoded_codes: list | None = None
    metadata: dict = field(default_factory=dict)


@runtime_checkable
class TTSBackend(Protocol):
    """Protocol any TTS backend implements.

    Backends can live anywhere (this package or a third-party); they just need
    to expose these methods. Use @runtime_checkable so isinstance(x, TTSBackend)
    works for plugin loading.
    """

    name: str

    def load(self, config: dict) -> None:
        """Load model weights + warm up. Called once per backend instance."""
        ...

    def encode_reference(self, ref_audio_path: str) -> list | None:
        """For cloning backends: encode ref WAV to model-native codes.

        Return None for preset-voice backends (Kokoro, Kitten) that don't use ref audio.
        """
        ...

    def synthesize(self, text: str, ref: VoiceRef) -> np.ndarray:
        """Batch synth: return full PCM (float32 in [-1, 1], 24kHz mono by convention)."""
        ...

    def synthesize_stream(self, text: str, ref: VoiceRef) -> Iterator[np.ndarray]:
        """Streaming synth: yield PCM chunks as produced.

        Backends without native streaming should yield a single chunk
        (degrades to batch behavior).
        """
        ...

    def health(self) -> dict:
        """Return diagnostics. Suggested keys: model, device, loaded (bool), warm (bool)."""
        ...


# Registry of installed backends. Phase D populates this with actual classes.
_REGISTRY: dict[str, type[TTSBackend]] = {}


def register_backend(name: str, backend_cls: type[TTSBackend]) -> None:
    """Register a backend class. Called by each backend module at import time."""
    _REGISTRY[name] = backend_cls


def get_backend(name: str) -> type[TTSBackend]:
    """Look up a backend class by name. Raises KeyError if not registered."""
    return _REGISTRY[name]


def available_backends() -> list[str]:
    """List names of registered backends."""
    return sorted(_REGISTRY.keys())
