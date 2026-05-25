"""F5-TTS backend.

Diffusion-based voice cloning. Apache-2 model weights from
[SWivid/F5-TTS](https://github.com/SWivid/F5-TTS); MIT Python wrapper on PyPI
(``pip install f5-tts``). Targets the **NeuTTS replacement** use case: cloning
backend that doesn't show the 30-second narrative coherence cliff.

Voice paradigm
--------------
Same as NeuTTS: each voice is registered with a reference WAV (3-15s) and a
matching transcript. The reference is encoded internally by F5 each call;
there is no pre-encode hook in F5's public API (so unlike NeuTTS, we can't
cache ``encoded_codes`` in the registry — see ``encode_reference`` below).

Streaming
---------
F5's ``F5TTS.infer()`` returns the full waveform in one call. ``cross_fade_duration``
parameter suggests internal chunking with crossfades, but no per-chunk yield is
exposed. ``synthesize_stream`` degrades to a single batch chunk.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterator
from typing import Any

import numpy as np

from . import VoiceRef, register_backend
from ._chunking import chunk_text

logger = logging.getLogger("voice_forge.backends.f5")

DEFAULT_MODEL = "F5TTS_v1_Base"
DEFAULT_NFE_STEP = 32  # diffusion steps; lower → faster + lower quality
DEFAULT_STREAM_CHUNK_CHARS = (
    1000  # large default; F5's quality benefits from longer context per call
)
SAMPLE_RATE = 24_000  # F5 native output


class F5Backend:
    """F5-TTS cloning backend."""

    name = "f5"

    def __init__(self) -> None:
        self._tts: Any = None
        self._config: dict[str, Any] = {}
        # F5TTS holds PyTorch state; serialize concurrent inference calls.
        self._lock = threading.Lock()

    # ----- TTSBackend Protocol -----

    def load(self, config: dict) -> None:
        """Construct the F5TTS object. First call downloads weights (~1.5 GB from HF).

        Config keys (all optional):
            model: F5 model variant (default ``F5TTS_v1_Base``).
            device: ``"cpu"``, ``"mps"``, ``"cuda"``, or ``None`` for autodetect
                    (F5's default — picks CUDA → MPS → CPU in order).
            nfe_step: diffusion function-eval count (default 32). Lower trades
                      quality for speed; 16 is the practical floor.
        """
        from f5_tts.api import F5TTS  # lazy import — heavy torch deps

        self._config = {
            "model": config.get("model", DEFAULT_MODEL),
            "device": config.get("device"),  # None → f5_tts autodetect
            "nfe_step": int(config.get("nfe_step", DEFAULT_NFE_STEP)),
        }
        logger.info(
            "loading F5TTS(model=%r, device=%r)",
            self._config["model"],
            self._config["device"] or "auto",
        )
        self._tts = F5TTS(model=self._config["model"], device=self._config["device"])

    def encode_reference(self, ref_audio_path: str) -> list | None:
        """F5 has no public pre-encode API; encoding happens inside ``infer()``.

        Returning ``None`` here is the Protocol's documented "this backend
        doesn't expose pre-encoding" signal. Caching could be added in a
        future revision once F5 exposes it (the model internally builds a
        mel-spectrogram + text-conditioned latent; cacheable in principle).
        """
        return None

    def synthesize(self, text: str, ref: VoiceRef) -> np.ndarray:
        """Batch synth: returns float32 PCM at 24 kHz.

        Honors ``ref.metadata['sampling']`` overrides per voice:
        - ``nfe_step`` (int): diffusion-step count; lower = faster, lower quality
        - ``cfg_strength`` (float): classifier-free guidance; higher = stronger
          adherence to the reference. Useful when a voice drifts (e.g. Heid).
        - ``seed`` (int): RNG seed for reproducibility / consistent regenerations
        - ``speed`` (float): playback-rate multiplier; 1.0 = natural, >1 = faster
        - ``cross_fade_duration`` (float): seconds of crossfade between chunks
        - ``sway_sampling_coef`` (float): sampling-schedule param; F5 default -1
        - ``target_rms`` (float): output volume normalization; F5 default 0.1
        - ``remove_silence`` (bool): post-process silence trim
        """
        if self._tts is None:
            raise RuntimeError("F5Backend not loaded; call load() first")
        if not ref.ref_audio_path:
            raise ValueError(f"f5 requires ref_audio_path; voice {ref.voice_id!r} has none")
        if not ref.ref_text:
            raise ValueError(f"f5 requires ref_text; voice {ref.voice_id!r} has none")

        sampling = ref.metadata.get("sampling") or {}
        # Recognized per-voice tunables for F5; other keys are silently ignored.
        infer_kwargs: dict[str, Any] = {
            "nfe_step": int(sampling.get("nfe_step", self._config["nfe_step"])),
        }
        for key in (
            "cfg_strength",
            "speed",
            "cross_fade_duration",
            "sway_sampling_coef",
            "target_rms",
        ):
            if key in sampling:
                infer_kwargs[key] = float(sampling[key])
        if "seed" in sampling:
            infer_kwargs["seed"] = int(sampling["seed"])
        if "remove_silence" in sampling:
            infer_kwargs["remove_silence"] = bool(sampling["remove_silence"])

        with self._lock:
            wav, _sr, _spec = self._tts.infer(
                ref_file=ref.ref_audio_path,
                ref_text=ref.ref_text,
                gen_text=text,
                show_info=lambda *_a, **_k: None,  # silence F5's print() calls
                **infer_kwargs,
            )
        return np.asarray(wav, dtype=np.float32)

    def synthesize_stream(self, text: str, ref: VoiceRef) -> Iterator[np.ndarray]:
        """Streaming via sentence-boundary text-chunking.

        F5's public API doesn't expose per-token streaming, but we can split
        the input at sentence boundaries and call ``infer()`` per chunk,
        yielding each chunk's audio as soon as it's ready. First-audio
        latency drops from full-utterance-time to first-sentence-time.

        Chunk size defaults to ``DEFAULT_STREAM_CHUNK_CHARS`` (1000 chars,
        big-enough to preserve F5's quality) but is per-voice tunable via
        ``ref.metadata['sampling']['stream_chunk_chars']``.
        """
        sampling = ref.metadata.get("sampling") or {}
        chunk_chars = int(sampling.get("stream_chunk_chars", DEFAULT_STREAM_CHUNK_CHARS))
        chunks = chunk_text(text, chunk_chars)
        if not chunks:
            return
        # Per-chunk synth uses the same code path as batch synthesize()
        # — including its sampling overrides — so quality stays consistent.
        for chunk in chunks:
            yield self.synthesize(chunk, ref)

    def health(self) -> dict:
        return {
            "name": self.name,
            "loaded": self._tts is not None,
            "model": self._config.get("model", DEFAULT_MODEL),
            "device": self._config.get("device") or "auto",
            "nfe_step": self._config.get("nfe_step", DEFAULT_NFE_STEP),
        }


# Auto-register at import time.
register_backend("f5", F5Backend)
