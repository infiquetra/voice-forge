"""MeloTTS backend (subprocess-isolated).

MIT-licensed multilingual TTS (English / Spanish / French / Chinese /
Japanese / Korean). Preset-voice only — no cloning. Subprocess-isolated
because MeloTTS pulls in a constrained transformers + torch combination
that would conflict with the main voice-forge venv.

Provision once with ``voice-forge backend install melotts``.

Voice paradigm: preset (EN-US, EN-BR, EN-INDIA, EN-AU, ES, FR, ZH, JP,
KR speakers ship with the model). Cloning is not supported.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterator

import numpy as np

from . import VoiceRef, register_backend
from ._presets import MELOTTS_PRESETS
from ._subprocess import SubprocessBackend

logger = logging.getLogger("voice_forge.backends.melotts")


class MeloTTSBackend(SubprocessBackend):
    """MeloTTS multilingual subprocess backend."""

    name = "melotts"

    KNOWN_PRESETS = MELOTTS_PRESETS

    KNOWN_TUNABLES = {
        "speed": {
            "type": "float",
            "min": 0.5,
            "max": 2.0,
            "default": 1.0,
            "description": "Playback rate multiplier.",
        },
        "sdp_ratio": {
            "type": "float",
            "min": 0.0,
            "max": 1.0,
            "default": 0.2,
            "description": "Stochastic duration predictor weight.",
        },
        "noise_scale": {
            "type": "float",
            "min": 0.0,
            "max": 1.0,
            "default": 0.6,
            "description": "Sampling noise scale.",
        },
        "noise_scale_w": {
            "type": "float",
            "min": 0.0,
            "max": 1.0,
            "default": 0.8,
            "description": "Stochastic duration noise scale.",
        },
    }


# Child-venv in-process impl.
if os.environ.get("VOICE_FORGE_SUBPROCESS_CHILD") == "1":
    from melo.api import TTS  # noqa: PLC0415 — child-only

    class _MeloTTSInProcess:
        """In-process implementation used inside the child venv."""

        name = "melotts"
        KNOWN_TUNABLES = MeloTTSBackend.KNOWN_TUNABLES

        def __init__(self) -> None:
            self._model: TTS | None = None
            self._speaker_ids: dict[str, int] = {}

        def load(self, config: dict) -> None:
            language = config.get("language", "EN")
            # MeloTTS's TTS() accepts a torch device string. "auto" works in
            # newer versions but not the 0.1.x line currently installable;
            # resolve explicitly for safety.
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
            self._model = TTS(language=language, device=device)
            self._speaker_ids = self._model.hps.data.spk2id
            logger.info(
                "melotts child loaded (language=%s, device=%s, speakers=%s)",
                language,
                device,
                list(self._speaker_ids),
            )

        def encode_reference(self, _ref_audio_path: str) -> list | None:
            return None

        def synthesize(self, text: str, ref: VoiceRef) -> np.ndarray:
            if self._model is None:
                raise RuntimeError("melotts not loaded")
            preset = ref.preset_id or list(self._speaker_ids)[0]
            speaker_id = self._speaker_ids.get(preset)
            if speaker_id is None:
                raise ValueError(
                    f"melotts: unknown preset {preset!r}; " f"available: {list(self._speaker_ids)}"
                )
            sampling = ref.metadata.get("sampling") or {}
            wav = self._model.tts_to_file(
                text,
                speaker_id,
                None,  # output_path=None → return array
                speed=float(sampling.get("speed", 1.0)),
                sdp_ratio=float(sampling.get("sdp_ratio", 0.2)),
                noise_scale=float(sampling.get("noise_scale", 0.6)),
                noise_scale_w=float(sampling.get("noise_scale_w", 0.8)),
                quiet=True,
            )
            return np.asarray(wav, dtype=np.float32)

        def synthesize_stream(self, text: str, ref: VoiceRef) -> Iterator[np.ndarray]:
            yield self.synthesize(text, ref)

        def unload(self) -> None:
            import gc

            self._model = None
            self._speaker_ids = {}
            gc.collect()

        def health(self) -> dict:
            return {
                "name": self.name,
                "loaded": self._model is not None,
                "speakers": list(self._speaker_ids),
            }

    register_backend("melotts", _MeloTTSInProcess)
else:
    register_backend("melotts", MeloTTSBackend)
