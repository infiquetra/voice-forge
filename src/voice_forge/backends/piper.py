"""Piper TTS backend (subprocess-isolated).

GPL-3 licensed; runs in its own venv to keep voice-forge's main process
Apache-2 hygiene clean. Voice paradigm: preset (Piper ships pre-trained
single-speaker voices per language). 30+ languages supported.

Provision once with ``voice-forge backend install piper``.

The shim entrypoint (running inside the child venv) imports
``piper.PiperVoice`` and synthesizes; the parent never touches piper-tts.
"""

from __future__ import annotations

import io
import logging
import os
import wave
from collections.abc import Iterator

import numpy as np

from . import VoiceRef, register_backend
from ._presets import PIPER_PRESETS
from ._subprocess import SubprocessBackend

logger = logging.getLogger("voice_forge.backends.piper")


class PiperBackend(SubprocessBackend):
    """Piper-TTS subprocess backend."""

    name = "piper"

    KNOWN_PRESETS = PIPER_PRESETS

    KNOWN_TUNABLES = {
        "length_scale": {
            "type": "float",
            "min": 0.5,
            "max": 2.0,
            "default": 1.0,
            "description": "Phoneme duration multiplier — higher = slower speech.",
        },
        "noise_scale": {
            "type": "float",
            "min": 0.0,
            "max": 1.0,
            "default": 0.667,
            "description": "Audio-noise variation; raises naturalness at cost of consistency.",
        },
        "noise_w": {
            "type": "float",
            "min": 0.0,
            "max": 1.0,
            "default": 0.8,
            "description": "Phoneme-noise width; controls prosody variation.",
        },
        "sentence_silence": {
            "type": "float",
            "min": 0.0,
            "max": 2.0,
            "default": 0.2,
            "description": "Seconds of silence between sentences.",
        },
    }


# When this module is imported INSIDE the child venv by the subprocess shim,
# we want the backend to use piper-tts directly (no recursive subprocess).
# The shim sets VOICE_FORGE_SUBPROCESS_CHILD=1 in the child env; if we detect
# that, swap in an in-process PiperVoice impl. The parent never enters this
# branch because the env var is unset there.
if os.environ.get("VOICE_FORGE_SUBPROCESS_CHILD") == "1":
    # Imports defer here so the parent never tries to load piper-tts.
    from piper.voice import PiperVoice  # noqa: PLC0415 — child-only

    class _PiperInProcess:
        """In-process implementation used inside the child venv."""

        name = "piper"
        KNOWN_TUNABLES = PiperBackend.KNOWN_TUNABLES

        def __init__(self) -> None:
            self._voice: PiperVoice | None = None
            self._config: dict = {}

        def load(self, config: dict) -> None:
            model_path = config.get("model_path")
            if not model_path:
                raise RuntimeError(
                    "piper backend (child) requires config.model_path "
                    "(set VOICE_FORGE_BACKEND_CONFIG_MODEL_PATH on parent side)"
                )
            self._config = dict(config)
            self._voice = PiperVoice.load(model_path)
            logger.info("piper child loaded model from %s", model_path)

        def encode_reference(self, _ref_audio_path: str) -> list | None:
            return None

        def synthesize(self, text: str, ref: VoiceRef) -> np.ndarray:
            if self._voice is None:
                raise RuntimeError("piper not loaded")
            sampling = ref.metadata.get("sampling") or {}
            buf = io.BytesIO()
            with wave.open(buf, "wb") as wav:
                self._voice.synthesize(
                    text,
                    wav,
                    length_scale=float(sampling.get("length_scale", 1.0)),
                    noise_scale=float(sampling.get("noise_scale", 0.667)),
                    noise_w=float(sampling.get("noise_w", 0.8)),
                    sentence_silence=float(sampling.get("sentence_silence", 0.2)),
                )
            buf.seek(0)
            with wave.open(buf, "rb") as wav:
                pcm_int16 = np.frombuffer(wav.readframes(wav.getnframes()), dtype=np.int16)
            return (pcm_int16.astype(np.float32) / 32768.0).astype(np.float32)

        def synthesize_stream(self, text: str, ref: VoiceRef) -> Iterator[np.ndarray]:
            # Piper synth is already fast; one chunk per call is fine.
            yield self.synthesize(text, ref)

        def health(self) -> dict:
            return {"name": self.name, "loaded": self._voice is not None}

        def unload(self) -> None:
            import gc

            self._voice = None
            gc.collect()

    register_backend("piper", _PiperInProcess)
else:
    # Parent process — register the subprocess-driving wrapper.
    register_backend("piper", PiperBackend)
