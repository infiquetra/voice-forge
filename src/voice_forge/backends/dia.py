"""Dia-1.6B backend (Nari Labs).

Apache-2 multi-speaker dialogue model from [nari-labs/dia](https://github.com/nari-labs/dia),
~1.6B parameters, SoundStorm-style architecture. Accessed via the **native
HuggingFace Transformers integration** — no separate pip install needed
(``transformers>=4.46`` ships ``DiaForConditionalGeneration`` directly).

Why Dia is interesting
----------------------
- Multi-speaker dialogue via ``[S1]`` / ``[S2]`` speaker tags inline in text.
  voice-forge's first backend that can produce more than one voice in a single
  synthesis call. (v0.2 ships single-speaker mode; multi-speaker is a follow-up
  audition.)
- Voice cloning via audio prompt: pass a 5-10s reference WAV alongside the
  text, model conditions output on that voice. Same VoiceRef shape as NeuTTS
  / F5: ``ref_audio_path`` + ``ref_text``.
- Native nonverbal tags: ``(laughs)``, ``(coughs)``, ``(clears throat)`` etc.
  Not exposed in v0.2 audition prompts but works at the model level.
- First community service wrapper — no PyPI package existed prior to this.

Generation guidelines (from upstream README, encoded in our defaults)
---------------------------------------------------------------------
- Text must begin with ``[S1]``.
- Single-speaker monologue uses just ``[S1]``.
- Two-speaker dialogue alternates ``[S1]`` and ``[S2]``.
- When using audio prompts: include the reference transcript BEFORE the
  generation text, in the format ``[S1] {ref_text} [S1] {gen_text}``. The
  model uses the ref transcript to align with the audio prompt.
- 5-10 seconds of ref audio works best (more or less degrades quality).
- Input length: under 5 s of expected output = unnatural; over 20 s =
  unnaturally fast speech. voice-forge doesn't chunk yet — long inputs may
  hit this. Worth queuing a text chunker for Dia.

Sample rate
-----------
Dia outputs at **44.1 kHz** natively. voice-forge's convention is 24 kHz
mono float32. The backend resamples to 24 kHz before returning, using
``librosa.resample`` (already in our venv via F5/Coqui transitive deps).

Device pick on Apple Silicon
----------------------------
1.6B parameters is the largest backend voice-forge ships in v0.2. On M2
Ultra with 128 GB unified memory, MPS should be viable. We default to
autodetect (``device=None``) which prefers MPS over CPU. Bench numbers
captured in [LEARNINGS § Dia resource profile](../../docs/engineering-journal/LEARNINGS.md).
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterator
from typing import Any

import numpy as np
import soundfile as sf

from . import VoiceRef, register_backend

logger = logging.getLogger("voice_forge.backends.dia")

DEFAULT_MODEL = "nari-labs/Dia-1.6B-0626"
DEFAULT_SAMPLE_RATE = 24_000  # voice-forge output convention
DIA_NATIVE_RATE = 44_100  # Dia model output rate

# Default generation parameters from upstream README. These are reasonable
# starting points; per-voice tuning (QUEUED P2) will let users override.
DEFAULT_MAX_NEW_TOKENS = 3072
DEFAULT_GUIDANCE_SCALE = 3.0
DEFAULT_TEMPERATURE = 1.8
DEFAULT_TOP_P = 0.90
DEFAULT_TOP_K = 45


def _autodetect_device() -> str:
    """Pick the best torch device available: cuda > mps > cpu."""
    import torch

    if torch.cuda.is_available():
        return "cuda"
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def _resample_to_24khz(audio: np.ndarray, src_rate: int) -> np.ndarray:
    """Resample a float32 PCM array to 24 kHz. No-op if already 24 kHz."""
    if src_rate == DEFAULT_SAMPLE_RATE:
        return audio.astype(np.float32, copy=False)
    # librosa is already in the venv as a transitive dep of f5/coqui.
    import librosa

    resampled = librosa.resample(
        audio.astype(np.float32, copy=False),
        orig_sr=src_rate,
        target_sr=DEFAULT_SAMPLE_RATE,
    )
    return resampled.astype(np.float32, copy=False)


class DiaBackend:
    """Dia-1.6B cloning + multi-speaker backend (Apache-2, via HF Transformers)."""

    name = "dia"

    def __init__(self) -> None:
        self._model: Any = None
        self._processor: Any = None
        self._device: str = "cpu"
        self._config: dict[str, Any] = {}
        # Transformer model is not thread-safe; serialize inference.
        self._lock = threading.Lock()

    # ----- TTSBackend Protocol -----

    def load(self, config: dict) -> None:
        """Construct Dia processor + model. First call downloads ~3 GB from HF.

        Config keys (all optional):
            model: HF model name. Default ``nari-labs/Dia-1.6B-0626``.
            device: ``"cpu"`` / ``"mps"`` / ``"cuda"`` / ``None`` (autodetect).
                    On Apple Silicon: autodetect picks MPS, which works on
                    M2 Ultra with 128 GB unified memory. Smaller hosts should
                    explicitly set ``"cpu"``.
        """
        from transformers import AutoProcessor, DiaForConditionalGeneration

        model_name = config.get("model", DEFAULT_MODEL)
        device = config.get("device") or _autodetect_device()
        self._device = device
        self._config = {
            "model": model_name,
            "device": device,
            "max_new_tokens": int(config.get("max_new_tokens", DEFAULT_MAX_NEW_TOKENS)),
            "guidance_scale": float(config.get("guidance_scale", DEFAULT_GUIDANCE_SCALE)),
            "temperature": float(config.get("temperature", DEFAULT_TEMPERATURE)),
            "top_p": float(config.get("top_p", DEFAULT_TOP_P)),
            "top_k": int(config.get("top_k", DEFAULT_TOP_K)),
        }
        logger.info("loading Dia(model=%r, device=%r)", model_name, device)
        self._processor = AutoProcessor.from_pretrained(model_name)
        self._model = DiaForConditionalGeneration.from_pretrained(model_name).to(device)

    def encode_reference(self, ref_audio_path: str) -> list | None:
        """Dia encodes audio prompts internally; no pre-encode hook exposed."""
        return None

    def synthesize(self, text: str, ref: VoiceRef) -> np.ndarray:
        """Single-speaker cloning synth: returns float32 PCM at 24 kHz.

        Multi-speaker dialogue (alternating ``[S1]``/``[S2]``) works at the
        model level but isn't exercised through voice-forge in v0.2. To use
        it, pre-format the input text with the speaker tags and pass to a
        Dia-backed voice with a multi-speaker reference. Future work could
        expose this via VoiceRef.metadata.
        """
        if self._model is None or self._processor is None:
            raise RuntimeError("DiaBackend not loaded; call load() first")
        if not ref.ref_audio_path:
            raise ValueError(f"dia requires ref_audio_path; voice {ref.voice_id!r} has none")
        if not ref.ref_text:
            raise ValueError(
                f"dia requires ref_text (transcript of ref audio); "
                f"voice {ref.voice_id!r} has none"
            )

        # Load the reference WAV at Dia's native rate.
        ref_audio, ref_sr = sf.read(ref.ref_audio_path, dtype="float32", always_2d=False)
        if ref_audio.ndim > 1:
            # Collapse to mono if stereo.
            ref_audio = ref_audio.mean(axis=1)
        if ref_sr != DIA_NATIVE_RATE:
            import librosa

            ref_audio = librosa.resample(ref_audio, orig_sr=ref_sr, target_sr=DIA_NATIVE_RATE)

        # Format the prompt per Dia's guidelines: ref transcript + gen text,
        # both prefixed with [S1] for single-speaker cloning.
        prompt = f"[S1] {ref.ref_text.strip()} [S1] {text.strip()}"

        with self._lock:
            inputs = self._processor(
                text=[prompt],
                audio=[ref_audio],
                padding=True,
                return_tensors="pt",
            ).to(self._device)

            outputs = self._model.generate(
                **inputs,
                max_new_tokens=self._config["max_new_tokens"],
                guidance_scale=self._config["guidance_scale"],
                temperature=self._config["temperature"],
                top_p=self._config["top_p"],
                top_k=self._config["top_k"],
            )

            audio_prompt_len = self._processor.get_audio_prompt_len(inputs.decoder_attention_mask)
            decoded = self._processor.batch_decode(outputs, audio_prompt_len=audio_prompt_len)

        # decoded is a list of torch.Tensor at 44.1 kHz; take the first and resample.
        wav_44k = decoded[0].cpu().numpy().astype(np.float32)
        return _resample_to_24khz(wav_44k, DIA_NATIVE_RATE)

    def synthesize_stream(self, text: str, ref: VoiceRef) -> Iterator[np.ndarray]:
        """Dia has no exposed streaming through HF Transformers; degrade to batch.

        The underlying SoundStorm architecture is autoregressive over audio
        codes, so streaming is theoretically possible at the token level —
        but not yet exposed through the public ``generate()`` surface.
        """
        yield self.synthesize(text, ref)

    def health(self) -> dict:
        return {
            "name": self.name,
            "loaded": self._model is not None,
            "model": self._config.get("model", DEFAULT_MODEL),
            "device": self._device,
            "max_new_tokens": self._config.get("max_new_tokens"),
        }


# Auto-register at import time.
register_backend("dia", DiaBackend)
