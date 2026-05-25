"""XTTS-v2 backend.

Coqui XTTS-v2 cloning + multilingual TTS via the idiap fork
[`coqui-tts`](https://github.com/idiap/coqui-ai-TTS) (library is **MPL-2.0**,
file-level copyleft — safe to depend on for an Apache-2 project).

**LICENSE NOTE: the model weights are NOT MPL-2.** XTTS-v2 weights are
distributed under the [Coqui Public Model License (CPML)](https://coqui.ai/cpml) —
NON-COMMERCIAL use only unless you purchase a commercial license from
Coqui (licensing@coqui.ai). The PyPI library wrapper is MPL-2; the model
weights are a separate licensing question. voice-forge does not ship the
weights — they're downloaded from Hugging Face on first use, and the user
implicitly accepts the CPML by downloading. This backend's ``load()``
requires ``COQUI_TOS_AGREED=1`` in the environment to confirm the user
has read and accepted the CPML.

Voice paradigm
--------------
Cloning via reference WAV (3-15s recommended). XTTS-v2 differs from NeuTTS
and F5 in that it does NOT require an accompanying transcript — the model
runs its own internal encoding on the speaker WAV directly. ``ref_text`` is
ignored (but kept in the registry for cross-backend voice reuse).

XTTS-v2 IS multilingual. Each synth call needs a language code; we read it
from ``ref.metadata['language']`` (default ``'en'``). Supported codes:
en, es, fr, de, it, pt, pl, tr, ru, nl, cs, ar, zh-cn, ja, hu, ko, hi.

Streaming
---------
XTTS exposes ``tts_stream()`` internally but the public ``TTS.tts()`` API
returns the whole waveform. v0.2 degrades ``synthesize_stream`` to a single
chunk. Native streaming is a queued follow-up if/when needed.

Device pick on Apple Silicon
----------------------------
**CPU is faster than MPS for XTTS-v2 on M-series.** Smoke test on M2 Ultra
(2026-05-25): CPU RTF 1.57, MPS RTF 8.18 — MPS is 5× slower because Coqui's
codebase hits unsupported MPS ops mid-graph and falls back to CPU per-op,
which adds round-trip overhead per layer. The default ``device=None``
(CPU) is the right choice. Only set ``device="mps"`` if upstream coqui-tts
fixes the MPS fallback churn in a future release.

Transformers pin
----------------
``coqui-tts==0.27.5`` depends on ``transformers.pytorch_utils.isin_mps_friendly``
which was removed in transformers v5.0. The ``xtts`` optional extra pins
``transformers<5`` to keep the import path live. When upstream coqui-tts
catches up to transformers 5.x, lift the pin.
"""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import Iterator
from typing import Any

import numpy as np

from . import VoiceRef, register_backend
from ._chunking import chunk_text

logger = logging.getLogger("voice_forge.backends.xtts")

DEFAULT_MODEL = "tts_models/multilingual/multi-dataset/xtts_v2"
DEFAULT_LANGUAGE = "en"
DEFAULT_STREAM_CHUNK_CHARS = 600  # medium default; XTTS quality holds well per-sentence
SAMPLE_RATE = 24_000  # XTTS-v2 native output


class XTTSBackend:
    """Coqui XTTS-v2 cloning backend (MPL-2, multilingual)."""

    name = "xtts"

    def __init__(self) -> None:
        self._tts: Any = None
        self._config: dict[str, Any] = {}
        # XTTS holds PyTorch state; serialize inference calls.
        self._lock = threading.Lock()

    # ----- TTSBackend Protocol -----

    def load(self, config: dict) -> None:
        """Construct the TTS object. First call downloads weights (~1.8 GB from HF).

        Config keys (all optional):
            model: Coqui model name. Default ``tts_models/multilingual/multi-dataset/xtts_v2``.
            device: ``"cpu"`` / ``"mps"`` / ``"cuda"``. Default ``None`` → CPU.
                    **On Apple Silicon, leave as CPU** — MPS is 5× slower than CPU
                    for XTTS-v2 due to unsupported-op fallback churn (smoke test
                    2026-05-25: CPU RTF 1.57, MPS RTF 8.18).

        Raises:
            RuntimeError: ``COQUI_TOS_AGREED`` env var not set. XTTS-v2 weights
                are CPML-licensed (non-commercial unless you've purchased a
                commercial license from Coqui). voice-forge can't accept the
                license on your behalf — set ``COQUI_TOS_AGREED=1`` in the
                process environment to confirm.
        """
        if os.environ.get("COQUI_TOS_AGREED") != "1":
            raise RuntimeError(
                "XTTS-v2 model weights are licensed under the Coqui Public Model "
                "License (CPML — https://coqui.ai/cpml), which is NON-COMMERCIAL "
                "unless you have purchased a commercial license from Coqui. "
                "voice-forge cannot accept the license on your behalf. To proceed, "
                "set the env var `COQUI_TOS_AGREED=1` after reading the CPML. "
                "If you intend to use XTTS commercially, contact "
                "licensing@coqui.ai before proceeding."
            )
        from TTS.api import TTS  # lazy import — heavy torch + coqui deps

        self._config = {
            "model": config.get("model", DEFAULT_MODEL),
            "device": config.get("device"),
        }
        logger.info(
            "loading XTTS(model=%r, device=%r)",
            self._config["model"],
            self._config["device"] or "cpu",
        )
        self._tts = TTS(model_name=self._config["model"], progress_bar=False)
        if self._config["device"]:
            self._tts.to(self._config["device"])

    def encode_reference(self, ref_audio_path: str) -> list | None:
        """XTTS encodes the reference internally on every ``tts()`` call.

        Returning ``None`` is the Protocol's "no pre-encode exposed" signal.
        Caching the speaker latent is technically possible (XTTS internals
        compute a conditioning latent + speaker embedding) but the public API
        doesn't surface it.
        """
        return None

    def synthesize(self, text: str, ref: VoiceRef) -> np.ndarray:
        """Batch synth: returns float32 PCM at 24 kHz.

        Honors ``ref.metadata['sampling']`` overrides per voice:
        - ``temperature`` (float): sampling temperature
        - ``top_k`` (int) / ``top_p`` (float): nucleus / top-k sampling
        - ``speed`` (float): playback-rate; >1 = faster, <1 = slower
        - ``repetition_penalty`` (float): XTTS-specific repeat suppression
        - ``length_penalty`` (float): XTTS-specific length bias
        """
        if self._tts is None:
            raise RuntimeError("XTTSBackend not loaded; call load() first")
        if not ref.ref_audio_path:
            raise ValueError(f"xtts requires ref_audio_path; voice {ref.voice_id!r} has none")
        # XTTS doesn't need ref_text — model does its own internal encoding.
        # Pull language from registry metadata (default 'en').
        language = ref.metadata.get("language", DEFAULT_LANGUAGE)

        sampling = ref.metadata.get("sampling") or {}
        tts_kwargs: dict[str, Any] = {}
        for key in ("speed", "temperature", "top_p", "length_penalty", "repetition_penalty"):
            if key in sampling:
                tts_kwargs[key] = float(sampling[key])
        if "top_k" in sampling:
            tts_kwargs["top_k"] = int(sampling["top_k"])

        with self._lock:
            wav = self._tts.tts(
                text=text,
                speaker_wav=ref.ref_audio_path,
                language=language,
                **tts_kwargs,
            )
        return np.asarray(wav, dtype=np.float32)

    def synthesize_stream(self, text: str, ref: VoiceRef) -> Iterator[np.ndarray]:
        """Streaming via sentence-boundary text-chunking.

        XTTS-v2's underlying GPT supports per-token streaming via
        ``model.inference_stream()`` (not exposed through ``TTS.api``), so
        v0.2 streams at the sentence level instead: split input at sentence
        boundaries, call ``tts()`` per chunk, yield. First-audio latency
        drops from full-utterance-time to first-sentence-time. Wiring the
        token-level stream is a v0.3 follow-up.

        Chunk size defaults to ``DEFAULT_STREAM_CHUNK_CHARS`` (600 chars);
        per-voice tunable via ``ref.metadata['sampling']['stream_chunk_chars']``.
        """
        sampling = ref.metadata.get("sampling") or {}
        chunk_chars = int(sampling.get("stream_chunk_chars", DEFAULT_STREAM_CHUNK_CHARS))
        chunks = chunk_text(text, chunk_chars)
        if not chunks:
            return
        for chunk in chunks:
            yield self.synthesize(chunk, ref)

    def health(self) -> dict:
        return {
            "name": self.name,
            "loaded": self._tts is not None,
            "model": self._config.get("model", DEFAULT_MODEL),
            "device": self._config.get("device") or "cpu",
            "default_language": DEFAULT_LANGUAGE,
        }


# Auto-register at import time.
register_backend("xtts", XTTSBackend)
