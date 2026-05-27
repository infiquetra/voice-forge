"""Chatterbox-Turbo TTS backend (subprocess-isolated).

MIT-licensed, sub-200ms latency cloning. Subprocess-isolated because of
hostile dep pins (``torch==2.6.0``, ``transformers==5.2.0``) that cannot
coexist with voice-forge's main F5/Kokoro/XTTS/Dia closure.

Provision once with ``voice-forge backend install chatterbox``.

Cloning fidelity verdict (from the 2026-05-25 audition documented in
LEARNINGS.md): pitch+gender adapter only — does NOT preserve source
accent on the Asgard sister refs. Useful for low-latency
single-speaker pipelines, NOT a drop-in replacement for F5 on
identity-preserving cloning.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterator

import numpy as np

from . import VoiceRef, register_backend
from ._subprocess import SubprocessBackend

logger = logging.getLogger("voice_forge.backends.chatterbox")


class ChatterboxBackend(SubprocessBackend):
    """Chatterbox-Turbo subprocess backend."""

    name = "chatterbox"

    KNOWN_TUNABLES = {
        "cfg_weight": {
            "type": "float",
            "min": 0.0,
            "max": 5.0,
            "default": 0.5,
            "description": "Classifier-free guidance weight.",
        },
        "temperature": {
            "type": "float",
            "min": 0.1,
            "max": 1.5,
            "default": 0.8,
            "description": "Sampling temperature.",
        },
        "exaggeration": {
            "type": "float",
            "min": 0.0,
            "max": 2.0,
            "default": 0.5,
            "description": "Style exaggeration multiplier.",
        },
    }


# Inside the child venv, swap in the in-process impl (uses chatterbox-tts directly).
# Sentinel env var avoids accidental import in the parent.
if os.environ.get("VOICE_FORGE_SUBPROCESS_CHILD") == "1":
    # Workaround: resemble-perth's API drifted such that the
    # ``PerthImplicitWatermarker`` symbol is now ``None`` (the import-time
    # initialization fails silently in some chatterbox-tts/perth versions).
    # chatterbox.tts:125 calls ``perth.PerthImplicitWatermarker()`` →
    # ``TypeError: 'NoneType' object is not callable``. Patch it to
    # DummyWatermarker (same interface, no-op watermark) BEFORE importing
    # chatterbox.tts. We don't need watermarking for voice-forge use.
    # Documented in LEARNINGS 2026-05-25 § "Chatterbox audition".
    import perth as _perth  # noqa: PLC0415

    if _perth.PerthImplicitWatermarker is None:
        _perth.PerthImplicitWatermarker = _perth.DummyWatermarker
    from chatterbox.tts import ChatterboxTTS  # noqa: PLC0415 — child-only

    class _ChatterboxInProcess:
        """In-process implementation used inside the child venv."""

        name = "chatterbox"
        KNOWN_TUNABLES = ChatterboxBackend.KNOWN_TUNABLES

        def __init__(self) -> None:
            self._model: ChatterboxTTS | None = None

        def load(self, config: dict) -> None:
            # ChatterboxTTS dispatches to torch's .to(device), which doesn't
            # accept "auto" — must be one of cpu/cuda/mps/etc. Resolve here
            # so the caller can still pass "auto" as a UX shortcut.
            requested = config.get("device") or "auto"
            if requested == "auto":
                import torch

                if torch.cuda.is_available():
                    device = "cuda"
                elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                    device = "mps"
                else:
                    device = "cpu"
            else:
                device = requested
            self._model = ChatterboxTTS.from_pretrained(
                device=device
            )  # nosec B615 — revision pin queued
            logger.info("chatterbox child loaded (device=%s, requested=%s)", device, requested)

        def encode_reference(self, _ref_audio_path: str) -> list | None:
            return None

        def synthesize(self, text: str, ref: VoiceRef) -> np.ndarray:
            if self._model is None:
                raise RuntimeError("chatterbox not loaded")
            if not ref.ref_audio_path:
                raise ValueError("chatterbox requires ref_audio_path")
            sampling = ref.metadata.get("sampling") or {}
            wav = self._model.generate(
                text,
                audio_prompt_path=ref.ref_audio_path,
                cfg_weight=float(sampling.get("cfg_weight", 0.5)),
                temperature=float(sampling.get("temperature", 0.8)),
                exaggeration=float(sampling.get("exaggeration", 0.5)),
            )
            return np.asarray(wav, dtype=np.float32)

        def synthesize_stream(self, text: str, ref: VoiceRef) -> Iterator[np.ndarray]:
            yield self.synthesize(text, ref)

        def health(self) -> dict:
            return {"name": self.name, "loaded": self._model is not None}

        def unload(self) -> None:
            import gc

            self._model = None
            gc.collect()

    register_backend("chatterbox", _ChatterboxInProcess)
else:
    register_backend("chatterbox", ChatterboxBackend)
