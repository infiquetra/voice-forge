"""NeuTTS Air backend.

Ports the working v6 daemon from infiquetra/home-lab's neutts-investigation
into the voice-forge TTSBackend Protocol. Key patches preserved:

  - n_ctx=8192 (override NeuTTS's hardcoded 2048 via _load_backbone monkey-patch)
  - repeat_penalty=1.05 (applied via Llama.__call__ wrap so both batch + stream get it)
  - Watermarker disabled (per-chunk artifact source on stream)

Phase D fills out the actual implementation. This file is a skeleton.
"""

from __future__ import annotations

from typing import Iterator

import numpy as np

from . import TTSBackend, VoiceRef, register_backend


class NeuTTSBackend:
    """NeuTTS Air backend — instant voice cloning from 3-15s ref WAV."""

    name = "neutts"

    def __init__(self) -> None:
        self._tts = None
        self._config: dict = {}

    def load(self, config: dict) -> None:
        """Load model (default Q8 GGUF) + apply our patches."""
        # TODO Phase D: port the v6 daemon's NeuTTS construction here.
        # Specifically:
        #   1. Monkey-patch NeuTTS._load_backbone to override max_context with N_CTX (8192 default)
        #   2. Wrap Llama.__call__ to inject repeat_penalty=1.05 when missing
        #   3. Construct NeuTTS(backbone_repo=model, backbone_device=device, ...)
        #   4. Disable tts.watermarker after construction (per-chunk artifact fix)
        self._config = config
        raise NotImplementedError("NeuTTSBackend.load — Phase D")

    def encode_reference(self, ref_audio_path: str) -> list | None:
        """Encode ref WAV to speech-token codes for priming."""
        # TODO Phase D: self._tts.encode_reference(ref_audio_path) -> list[int]
        raise NotImplementedError

    def synthesize(self, text: str, ref: VoiceRef) -> np.ndarray:
        """Batch synth: chunk text at sentence boundaries, infer each chunk, concatenate."""
        # TODO Phase D: port the daemon's chunk_text() + tts.infer() loop
        raise NotImplementedError

    def synthesize_stream(self, text: str, ref: VoiceRef) -> Iterator[np.ndarray]:
        """Streaming synth via tts.infer_stream() — yields PCM chunks progressively.

        NOTE (from home-lab investigation): NeuTTS streaming mode drops 15-21% of
        content vs batch on long inputs. v0 default is batch (called via synthesize()).
        Streaming is opt-in for use cases where perceived latency matters more than
        content completeness.
        """
        # TODO Phase D: port the daemon's stream_worker loop
        raise NotImplementedError

    def health(self) -> dict:
        return {
            "name": self.name,
            "loaded": self._tts is not None,
            "model": self._config.get("model"),
            "device": self._config.get("device"),
        }


# Auto-register on import (Phase D will uncomment when implementation is real)
# register_backend("neutts", NeuTTSBackend)
