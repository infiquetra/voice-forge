"""TTS backend abstractions.

The TTSBackend Protocol is the contract any backend must implement.
The VoiceRef union dataclass carries the variance between backends
(ref WAV for NeuTTS/F5/XTTS/Dia vs preset_id for Kokoro/Kitten).

See docs/ARCHITECTURE.md § "Core abstractions" for the full design.
"""

from __future__ import annotations

import importlib
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Literal, Protocol, TypedDict, runtime_checkable

import numpy as np


class TunableSpec(TypedDict, total=False):
    """Schema for one per-voice sampling parameter.

    A backend exposes its tunables via ``KNOWN_TUNABLES: dict[str, TunableSpec]``
    so callers (CLI, REST clients, the demo page) can render a config UI without
    hardcoded per-backend knowledge. Values picked from this schema flow into
    ``VoiceRef.metadata['sampling'][<key>]`` and through to the backend's
    ``synthesize()`` call.
    """

    type: Literal["int", "float", "bool", "string"]
    min: float | int
    max: float | int
    default: float | int | bool | str
    description: str


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

    ``persona`` is the human-meaningful identity that may be shared by
    multiple voice rows under different backends (e.g. ``saga-comms``
    and ``saga-comms-f5`` are the same persona "Saga" rendered through
    NeuTTS and F5 respectively). Optional — the demo picker derives a
    fallback by stripping known backend suffixes when None.
    """

    voice_id: str
    backend: str
    ref_audio_path: str | None = None
    ref_text: str | None = None
    preset_id: str | None = None
    encoded_codes: list | None = None
    metadata: dict = field(default_factory=dict)
    persona: str | None = None


@runtime_checkable
class TTSBackend(Protocol):
    """Protocol any TTS backend implements.

    Backends can live anywhere (this package or a third-party); they just need
    to expose these methods. Use @runtime_checkable so isinstance(x, TTSBackend)
    works for plugin loading.
    """

    name: str
    # KNOWN_TUNABLES advertises which sampling overrides the backend honors.
    # Used by GET /v1/backends to drive the demo page's conditional knob panel.
    # Each value should follow the TunableSpec shape; we type the outer dict
    # loosely here to keep plain-dict-literal class attributes compatible.
    # Empty {} is valid (NeuTTS has no per-voice tunables today).
    KNOWN_TUNABLES: dict

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


# Registry of installed backend classes, populated by register_backend()
# at import time of each backend module.
_REGISTRY: dict[str, type[TTSBackend]] = {}

# Name → module-path map. Adding a new backend means: drop a module under
# this package, call register_backend(name, cls) at module top-level, and
# add an entry here. Kept explicit (not entry-points) so the supported set
# is grep-able from the source tree.
_BACKEND_MODULES: dict[str, str] = {
    "neutts": "voice_forge.backends.neutts",
    "kokoro": "voice_forge.backends.kokoro",
    "f5": "voice_forge.backends.f5",
    "xtts": "voice_forge.backends.xtts",
    "dia": "voice_forge.backends.dia",
}


def register_backend(name: str, backend_cls: type[TTSBackend]) -> None:
    """Register a backend class. Called by each backend module at import time."""
    _REGISTRY[name] = backend_cls


def get_backend(name: str) -> type[TTSBackend]:
    """Look up a backend class by name. Raises KeyError if not registered."""
    return _REGISTRY[name]


def available_backends() -> list[str]:
    """List names of registered backends."""
    return sorted(_REGISTRY.keys())


def known_backends() -> list[str]:
    """List names of backends voice-forge knows about (even if not yet imported)."""
    return sorted(_BACKEND_MODULES.keys())


def load_backend_module(name: str) -> None:
    """Import a known backend module to trigger its ``register_backend()`` side effect.

    Raises:
        KeyError: ``name`` is not in ``_BACKEND_MODULES``.
        ImportError: the module exists in the map but its optional deps are
            not installed (e.g. ``pip install voice-forge-tts[kokoro]`` not run).
    """
    if name not in _BACKEND_MODULES:
        raise KeyError(f"unknown backend: {name!r}; known backends: {sorted(_BACKEND_MODULES)}")
    importlib.import_module(_BACKEND_MODULES[name])
