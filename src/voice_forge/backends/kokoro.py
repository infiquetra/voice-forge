"""Kokoro-82M TTS backend.

Lightweight TTS (~82M params, ~330MB model weight). PyTorch-backed; MPS-capable
on Apple Silicon. Validates the ``preset_id`` arm of ``VoiceRef`` — NeuTTS uses
``(encoded_codes, ref_text)``, Kokoro uses a named preset (or a blended voice
tensor for mixes).

System prerequisite
-------------------
Kokoro depends transitively on ``misaki[en]`` for grapheme-to-phoneme, which
requires the ``espeak-ng`` binary on the host PATH for English OOD fallback.
Install:

    # macOS
    brew install espeak-ng

    # Linux
    apt-get install espeak-ng

``load()`` runs a pre-flight ``shutil.which("espeak-ng")`` check and raises
``RuntimeError`` with the install hint if the binary is missing — better than
the cryptic error you'd otherwise see at first synth.

Voice mixing
------------
The syntax is parsed by ``_mixing.parse_mix``. Single-voice specs map directly
to a string voice name passed to ``KPipeline(..., voice=name)``. Multi-voice
mixes are *parsed* in v0.2 but currently degrade to picking the highest-weight
voice — full tensor blending requires HF-cache path discovery for the
per-voice ``.pt`` files which we haven't pinned down yet. Tracked for v0.2.x.
"""

from __future__ import annotations

import logging
import shutil
from collections.abc import Iterator
from typing import Any

import numpy as np

from . import VoiceRef, register_backend
from ._mixing import parse_mix

logger = logging.getLogger("voice_forge.backends.kokoro")

DEFAULT_LANG_CODE = "a"  # American English; see KPipeline locale list for others


class KokoroBackend:
    """Kokoro-82M backend — preset-voice synthesis with optional mix syntax."""

    name = "kokoro"

    def __init__(self) -> None:
        self._pipeline: Any = None
        self._config: dict[str, Any] = {}

    # ----- TTSBackend Protocol -----

    def load(self, config: dict) -> None:
        """Construct a ``KPipeline``. First call downloads the model from HF (~330MB).

        Config keys (all optional):
            lang_code: KPipeline locale code (default ``"a"`` — American English).
                Valid codes per upstream: a/b (English), e (Spanish), f (French),
                h (Hindi), i (Italian), j (Japanese), p (Brazilian Portuguese),
                z (Mandarin Chinese).
        """
        if shutil.which("espeak-ng") is None:
            raise RuntimeError(
                "Kokoro requires the espeak-ng system binary on PATH. "
                "Install it: `brew install espeak-ng` (Mac) or "
                "`apt-get install espeak-ng` (Linux), then re-run."
            )
        from kokoro import KPipeline  # lazy import — heavy torch deps

        lang_code = config.get("lang_code", DEFAULT_LANG_CODE)
        self._config = {"lang_code": lang_code}
        logger.info("loading kokoro KPipeline(lang_code=%r)", lang_code)
        self._pipeline = KPipeline(lang_code=lang_code)

    def encode_reference(self, ref_audio_path: str) -> list | None:
        """Preset-voice backend — no ref-audio encoding needed."""
        return None

    def synthesize(self, text: str, ref: VoiceRef) -> np.ndarray:
        """Concatenate all audio chunks the pipeline yields into a single array."""
        voice = self._resolve_voice(ref)
        chunks: list[np.ndarray] = []
        for _gs, _ps, audio in self._pipeline(text, voice=voice, speed=1.0):
            chunks.append(np.asarray(audio, dtype=np.float32))
        if not chunks:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(chunks)

    def synthesize_stream(self, text: str, ref: VoiceRef) -> Iterator[np.ndarray]:
        """Native streaming: ``KPipeline`` yields per-segment so we forward."""
        voice = self._resolve_voice(ref)
        for _gs, _ps, audio in self._pipeline(text, voice=voice, speed=1.0):
            yield np.asarray(audio, dtype=np.float32)

    def health(self) -> dict:
        return {
            "name": self.name,
            "loaded": self._pipeline is not None,
            "lang_code": self._config.get("lang_code"),
            "model": "kokoro-82M",
        }

    # ----- internals -----

    def _resolve_voice(self, ref: VoiceRef) -> str:
        """Return the voice string to pass to KPipeline.

        Single-voice specs return the bare name. Multi-voice mixes log a
        degradation warning and return the highest-weight voice — tensor
        blending is a v0.2.x follow-up (we haven't pinned the upstream
        per-voice tensor access pattern yet).
        """
        if self._pipeline is None:
            raise RuntimeError("KokoroBackend not loaded; call load() first")
        if not ref.preset_id:
            raise ValueError(f"kokoro requires preset_id; voice {ref.voice_id!r} has none")
        mix = parse_mix(ref.preset_id)
        if len(mix) == 1:
            return mix[0][0]
        # Multi-voice mix: pick highest-weight voice as a fallback. Future
        # work (v0.2.x) loads each voice's .pt tensor from the HF cache,
        # weighted-averages them, and passes the resulting tensor.
        winner = max(mix, key=lambda nw: nw[1])
        logger.warning(
            "voice-mix degradation: %r → using highest-weight voice %r "
            "(tensor-blending not yet implemented, tracked for v0.2.x)",
            ref.preset_id,
            winner[0],
        )
        return winner[0]


# Auto-register at import time.
register_backend("kokoro", KokoroBackend)
