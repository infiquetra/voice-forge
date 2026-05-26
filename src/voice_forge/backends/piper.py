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
from pathlib import Path

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
    from piper import SynthesisConfig  # noqa: PLC0415 — child-only
    from piper.voice import PiperVoice  # noqa: PLC0415 — child-only

    class _PiperInProcess:
        """In-process implementation used inside the child venv.

        Voices are resolved + downloaded per-call from ``ref.preset_id``
        (the Piper voice name like ``en_US-amy-medium``). Each loaded voice
        is cached so subsequent samples reuse it. ``load()`` itself is a
        no-op — Piper's ~50 MB ONNX files download lazily, on demand.
        """

        name = "piper"
        KNOWN_TUNABLES = PiperBackend.KNOWN_TUNABLES

        def __init__(self) -> None:
            self._config: dict = {}
            self._voice_cache: dict[str, PiperVoice] = {}
            # Default voice for when a caller passes no preset_id (the
            # /v1/audio/speech path with a registered Piper voice that
            # somehow has no preset metadata). Lazy-loaded.
            self._default_preset = "en_US-amy-medium"

        def load(self, config: dict) -> None:
            """Lazy — no model fetch at load time. First synth() resolves
            the voice from ref.preset_id + downloads on first hit."""
            self._config = dict(config)
            logger.info("piper child ready (lazy load: each preset_id downloads on first use)")

        def _get_voice(self, preset_id: str | None) -> PiperVoice:
            """Resolve a Piper voice from ``preset_id``, downloading if absent.

            ``preset_id`` like ``en_US-amy-medium``. piper-tts 1.4+ ships
            ``piper.download_voices.download_voice(voice, download_dir)``
            which fetches the .onnx + .onnx.json from
            huggingface.co/rhasspy/piper-voices into ``download_dir``.
            We cache the loaded PiperVoice per preset so repeated samples
            don't re-disk-read the model.
            """
            preset = preset_id or self._default_preset
            if preset not in self._voice_cache:
                from piper.download_voices import download_voice  # noqa: PLC0415

                cache_dir = Path("~/.voice-forge/piper-voices").expanduser()
                cache_dir.mkdir(parents=True, exist_ok=True)
                model_path = cache_dir / f"{preset}.onnx"
                if not model_path.is_file():
                    logger.info(
                        "piper: downloading voice %r into %s (first use; ~30-50 MB)",
                        preset,
                        cache_dir,
                    )
                    download_voice(preset, cache_dir)
                logger.info("piper: loading %s", model_path)
                self._voice_cache[preset] = PiperVoice.load(str(model_path))
            return self._voice_cache[preset]

        def encode_reference(self, _ref_audio_path: str) -> list | None:
            return None

        def synthesize(self, text: str, ref: VoiceRef) -> np.ndarray:
            voice = self._get_voice(ref.preset_id)
            sampling = ref.metadata.get("sampling") or {}
            # piper-tts 1.4+ API: PiperVoice.synthesize_wav(text, wav_file,
            # syn_config=SynthesisConfig(...)). Older versions took
            # length_scale/noise_scale/noise_w as direct kwargs to
            # synthesize() — that's been replaced by the SynthesisConfig
            # bundle. sentence_silence is no longer a tunable in the new
            # API (sentence boundaries handled internally).
            syn_config = SynthesisConfig(
                length_scale=float(sampling.get("length_scale", 1.0)),
                noise_scale=float(sampling.get("noise_scale", 0.667)),
                noise_w_scale=float(sampling.get("noise_w", 0.8)),
            )
            buf = io.BytesIO()
            with wave.open(buf, "wb") as wav:
                voice.synthesize_wav(text, wav, syn_config=syn_config)
            buf.seek(0)
            with wave.open(buf, "rb") as wav:
                pcm_int16 = np.frombuffer(wav.readframes(wav.getnframes()), dtype=np.int16)
            return (pcm_int16.astype(np.float32) / 32768.0).astype(np.float32)

        def synthesize_stream(self, text: str, ref: VoiceRef) -> Iterator[np.ndarray]:
            yield self.synthesize(text, ref)

        def health(self) -> dict:
            return {
                "name": self.name,
                "loaded": True,  # Piper is "loaded" once the shim is up; voices download lazily.
                "voices_cached": list(self._voice_cache.keys()),
            }

        def unload(self) -> None:
            import gc

            self._voice_cache = {}
            gc.collect()

    register_backend("piper", _PiperInProcess)
else:
    # Parent process — register the subprocess-driving wrapper.
    register_backend("piper", PiperBackend)
