"""NeuTTS Air backend.

Ports the v6 daemon from infiquetra/home-lab (commit ``61ffa6c``) into the
voice-forge ``TTSBackend`` Protocol. Key patches preserved verbatim:

1. ``n_ctx=8192`` override (monkey-patches NeuTTS._load_backbone before
   the underlying Llama is constructed; NeuTTS hardcodes 2048, way below
   what the underlying model trained at 32768 supports).
2. ``repeat_penalty=1.05`` injection via Llama.__call__ wrap (applies to
   BOTH batch and streaming paths; NeuTTS's _infer_stream_ggml omits this
   parameter, which caused ~21% content loss in streaming mode).
3. ``tts.watermarker = None`` post-construction (the Perth implicit
   watermarker introduces per-chunk noise that produces audible cracks
   at streaming chunk boundaries — disabling it cut streaming clicks 15x
   in empirical testing).

See the home-lab engineering journal for the discovery story:
- ``infiquetra/home-lab/docs/engineering-journal/narratives/2026-05-24-voice-forge-spin-out.md``
- ``infiquetra/home-lab/docs/engineering-journal/LEARNINGS.md`` § 2026-05-24
"""

from __future__ import annotations

import re
import threading
from collections.abc import Iterator
from typing import Any

import numpy as np

from . import VoiceRef, register_backend

DEFAULT_MODEL = "neuphonic/neutts-air-q8-gguf"
DEFAULT_DEVICE = "cpu"
DEFAULT_N_CTX = 8192
DEFAULT_REPEAT_PENALTY = 1.05
DEFAULT_CHUNK_CHARS = 600
SAMPLE_RATE = 24_000


def _apply_neutts_patches(n_ctx: int, repeat_penalty: float) -> None:
    """Idempotently apply our three NeuTTS patches.

    Safe to call multiple times — uses module-level flags so re-patching
    doesn't compound (would happen if we re-instantiated NeuTTSBackend).
    """
    from llama_cpp import Llama
    from neutts import NeuTTS

    if not getattr(NeuTTS._load_backbone, "_voice_forge_patched", False):
        _original_load_backbone = NeuTTS._load_backbone

        def _patched_load_backbone(self, backbone_repo, backbone_device):
            self.max_context = n_ctx
            return _original_load_backbone(self, backbone_repo, backbone_device)

        _patched_load_backbone._voice_forge_patched = True  # type: ignore[attr-defined]
        NeuTTS._load_backbone = _patched_load_backbone

    if not getattr(Llama.__call__, "_voice_forge_patched", False):
        _original_llama_call = Llama.__call__

        def _patched_llama_call(self, *args, **kwargs):
            if "repeat_penalty" not in kwargs:
                kwargs["repeat_penalty"] = repeat_penalty
            return _original_llama_call(self, *args, **kwargs)

        _patched_llama_call._voice_forge_patched = True  # type: ignore[attr-defined]
        Llama.__call__ = _patched_llama_call


def _chunk_text(text: str, max_chars: int) -> list[str]:
    """Split text at sentence boundaries, respecting max_chars per chunk.

    Sentences are detected by ``.!?`` followed by whitespace. A single
    sentence longer than max_chars goes into its own chunk (we don't
    split mid-sentence — that causes cloning quality drift).
    """
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for sentence in sentences:
        if current and current_len + len(sentence) + 1 > max_chars:
            chunks.append(" ".join(current))
            current = [sentence]
            current_len = len(sentence)
        else:
            current.append(sentence)
            current_len += len(sentence) + 1
    if current:
        chunks.append(" ".join(current))
    return chunks


class NeuTTSBackend:
    """NeuTTS Air backend — instant voice cloning from 3-15s reference WAV."""

    name = "neutts"

    def __init__(self) -> None:
        self._tts: Any = None
        self._config: dict[str, Any] = {}
        # NeuTTS / llama-cpp are not thread-safe on the same instance.
        # Serialize per-instance synthesis to avoid races.
        self._lock = threading.Lock()

    # ----- TTSBackend Protocol -----

    def load(self, config: dict) -> None:
        """Load NeuTTS model + apply our patches. Idempotent.

        Config keys (all optional):
            model: HuggingFace repo (default neuphonic/neutts-air-q8-gguf)
            device: "cpu" or "mps" (default "cpu" — counterintuitively
                    fastest on Apple Silicon for this model size; see
                    home-lab LEARNINGS 2026-05-24)
            n_ctx: context window size (default 8192)
            repeat_penalty: loop-suppression (default 1.05)
            chunk_chars: text chunker boundary (default 600)
        """
        self._config = {
            "model": config.get("model", DEFAULT_MODEL),
            "device": config.get("device", DEFAULT_DEVICE),
            "n_ctx": int(config.get("n_ctx", DEFAULT_N_CTX)),
            "repeat_penalty": float(config.get("repeat_penalty", DEFAULT_REPEAT_PENALTY)),
            "chunk_chars": int(config.get("chunk_chars", DEFAULT_CHUNK_CHARS)),
        }

        _apply_neutts_patches(
            n_ctx=self._config["n_ctx"],
            repeat_penalty=self._config["repeat_penalty"],
        )

        from neutts import NeuTTS

        self._tts = NeuTTS(
            backbone_repo=self._config["model"],
            backbone_device=self._config["device"],
            codec_repo="neuphonic/neucodec",
            codec_device=self._config["device"],
        )

        # Disable Perth watermarker — it causes per-chunk artifacts in stream.
        # See home-lab LEARNINGS 2026-05-24 § "Perth watermarker is a per-chunk artifact source".
        if getattr(self._tts, "watermarker", None) is not None:
            self._tts.watermarker = None

    def encode_reference(self, ref_audio_path: str) -> list | None:
        """Encode ref WAV into NeuTTS speech-token codes for priming."""
        if self._tts is None:
            raise RuntimeError("NeuTTSBackend not loaded; call load() first")
        return self._tts.encode_reference(ref_audio_path)

    def synthesize(self, text: str, ref: VoiceRef) -> np.ndarray:
        """Batch synthesis: chunk text, infer each chunk, concatenate PCM samples."""
        if self._tts is None:
            raise RuntimeError("NeuTTSBackend not loaded; call load() first")
        codes, ref_text = self._resolve_ref(ref)
        chunks = _chunk_text(text, self._config["chunk_chars"])
        audio_parts: list[np.ndarray] = []
        with self._lock:
            for chunk in chunks:
                audio_parts.append(self._tts.infer(chunk, codes, ref_text))
        if not audio_parts:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(audio_parts) if len(audio_parts) > 1 else audio_parts[0]

    def synthesize_stream(self, text: str, ref: VoiceRef) -> Iterator[np.ndarray]:
        """Streaming synthesis: yield PCM chunks as they're produced.

        WARNING (from home-lab investigation 2026-05-24): NeuTTS streaming
        mode produces ~15-21% less audio than batch mode for identical input
        on long content. The cause is somewhere in NeuTTS's _infer_stream_ggml
        chunk-stitching logic. The Llama.__call__ wrap (applied via
        _apply_neutts_patches) recovers ~12s of a 34s gap on a 1991-char
        test, but does not fully close it.

        For content-completeness, callers should default to ``synthesize()``.
        Streaming is opt-in for low-latency use cases where partial-content
        is acceptable.
        """
        if self._tts is None:
            raise RuntimeError("NeuTTSBackend not loaded; call load() first")
        codes, ref_text = self._resolve_ref(ref)
        chunks = _chunk_text(text, self._config["chunk_chars"])
        with self._lock:
            for chunk in chunks:
                yield from self._tts.infer_stream(chunk, codes, ref_text)

    def health(self) -> dict:
        """Diagnostics for /health endpoint."""
        return {
            "name": self.name,
            "loaded": self._tts is not None,
            "model": self._config.get("model"),
            "device": self._config.get("device"),
            "n_ctx": self._config.get("n_ctx"),
            "repeat_penalty": self._config.get("repeat_penalty"),
            "chunk_chars": self._config.get("chunk_chars"),
            "watermarker_disabled": True,
        }

    # ----- internals -----

    def _resolve_ref(self, ref: VoiceRef) -> tuple[list, str]:
        """Get (codes, ref_text) for synthesis, encoding ref_audio on the fly if needed."""
        if ref.ref_text is None:
            raise ValueError(f"NeuTTS backend requires ref_text for voice {ref.voice_id!r}")
        if ref.encoded_codes is not None:
            return ref.encoded_codes, ref.ref_text
        if ref.ref_audio_path is None:
            raise ValueError(
                f"NeuTTS backend requires ref_audio_path or encoded_codes for"
                f" voice {ref.voice_id!r}"
            )
        # Cold encode each call. If you want this cached, pre-encode at registry
        # load time and stuff into ref.encoded_codes.
        codes = self.encode_reference(ref.ref_audio_path)
        # encode_reference is `list | None` in the Protocol because preset-voice
        # backends return None; NeuTTS's implementation always returns the codes
        # (or raises). Narrow for the type checker.
        assert codes is not None, "NeuTTS.encode_reference returned None unexpectedly"
        return codes, ref.ref_text


# Auto-register at import time.
register_backend("neutts", NeuTTSBackend)
