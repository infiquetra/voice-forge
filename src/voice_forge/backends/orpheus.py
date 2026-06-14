"""Orpheus TTS backend (subprocess-isolated).

Apache-2.0 Llama-3 3B-backbone autoregressive TTS from Canopy Labs. Native
voice cloning + streaming. Subprocess-isolated because the model pulls in
its own pinned ``transformers`` + ``torch`` + ``snac`` versions that we
don't want polluting the main voice-forge venv.

Provision once with ``voice-forge backend install orpheus``.

Why this backend exists when we already have F5 / NeuTTS / XTTS / Chatterbox:
F5 is diffusion-based and phonetically aligns to the target text's language
defaults — it consistently strips strong non-default accents (e.g. heavy
Norwegian English) regardless of reference content. NeuTTS is Llama-based
and DOES preserve such accents but has a 30-second narrative-coherence
cliff. Orpheus combines the Llama-backbone accent fidelity with newer-
training that's reported to lack NeuTTS's length cliff. See LEARNINGS
2026-05-26 for the F5-can't-do-male-Nordic experimental result that drove
this addition.

Voice paradigm: clone. Same VoiceRef shape as F5 / NeuTTS — reference WAV
+ reference text. The Llama backbone in-context-learns the speaker token
sequence from the reference audio's SNAC codes, then continues the
sequence for the target text.

Audio codec: SNAC (Multi-Scale Neural Audio Codec) — Orpheus emits SNAC
token streams; we decode to 24 kHz mono PCM via SNAC's decoder. The
``snac`` PyPI package is pulled into the per-backend venv directly (no
vendor inference wrapper).

Apple Silicon path: child-only code uses raw ``transformers`` +
``snac`` against ``torch.device("mps")`` when available — no ``vllm``
(CUDA-only). Streaming degrades to a single-batch yield for v1; the
SNAC layout (7 tokens/frame) makes incremental decoding feasible as a
follow-up.

Resources: ~6 GB fp16 / ~2 GB int4 quantized, ~0.8-1.2x realtime on M2
Ultra MPS. Comparable footprint to Chatterbox.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterator
from typing import Any

import numpy as np

from . import VoiceRef, register_backend
from ._subprocess import SubprocessBackend

logger = logging.getLogger("voice_forge.backends.orpheus")

# Default model — Canopy Labs's official English finetune.
#
# We default to ``audo/orpheus-3b-0.1-ft``, an ungated mirror of the
# identical safetensors checkpoint that canopylabs hosts at
# ``canopylabs/orpheus-3b-0.1-ft`` (verified same vocab_size=156940 and
# Llama-3.2-3B base). The canopylabs repo is HuggingFace-gated even
# though it ships an Apache-2.0 license, which blocks cold-start in
# unattended provisioning. Override via ``config['model']`` if you've
# accepted the canopylabs gate on the host's HF account.
DEFAULT_MODEL = "audo/orpheus-3b-0.1-ft"
SAMPLE_RATE = 24_000  # Orpheus / SNAC native output rate

# Orpheus's audio-extended Llama vocab is laid out as:
#   tokens [0, 128255]              — text vocab
#   token  128256                   — start-of-audio marker
#   tokens [128257, 128261]         — control / end-of-stream markers
#   token  128259                   — start-of-human marker
#   tokens [128266, 156937]         — audio codes
#     For frame slot i in [0, 6] and codebook value v in [0, 4095]:
#       audio_token_id(i, v) = 128266 + (i * 4096) + v
#     Inverse (decoder side):
#       v = (token_id - 128266) - (i * 4096)   when 0 <= v < 4096
#
# These constants match canopyai/Orpheus-TTS' engine_class.py + decoder.py
# (verified 2026-05-26). Keep in sync if upstream renumbers.
AUDIO_TOKEN_OFFSET = 128266
AUDIO_TOKENS_PER_FRAME = 7
AUDIO_CODEBOOK_SIZE = 4096
START_OF_HUMAN_ID = 128259
END_TEXT_IDS = (128009, 128260, 128261, 128257)
START_OF_AUDIO_ID = 128257  # also serves as EOS stop token for generation
STOP_TOKEN_IDS = (128258,)  # end-of-audio sentinel — Orpheus emits this to halt


class OrpheusBackend(SubprocessBackend):
    """Orpheus-TTS subprocess backend (parent-side wrapper)."""

    name = "orpheus"

    KNOWN_TUNABLES = {
        "temperature": {
            "type": "float",
            "min": 0.1,
            "max": 1.5,
            "default": 0.6,
            "description": "Sampling temperature for the Llama backbone. Lower = "
            "more faithful to reference voice; higher = more variation.",
        },
        "top_p": {
            "type": "float",
            "min": 0.1,
            "max": 1.0,
            "default": 0.95,
            "description": "Nucleus sampling. 0.95 is a sensible default for cloning.",
        },
        "top_k": {
            "type": "int",
            "min": 1,
            "max": 200,
            "default": 50,
            "description": "Top-k token filter. Trade-off variety vs stability.",
        },
        "repetition_penalty": {
            "type": "float",
            "min": 1.0,
            "max": 2.0,
            "default": 1.1,
            "description": "Penalty for repeated tokens - prevents loops at long lengths.",
        },
        "max_tokens": {
            "type": "int",
            "min": 256,
            "max": 8192,
            "default": 2048,
            "description": "Max output tokens. Higher = supports longer utterances.",
        },
    }


# Inside the child venv, swap in the in-process impl. Sentinel env var
# (VOICE_FORGE_SUBPROCESS_CHILD=1) is set by _spawn_child in the parent and
# avoids the heavy import in the parent process.
if os.environ.get("VOICE_FORGE_SUBPROCESS_CHILD") == "1":
    # All heavy ML imports are child-only. The orpheus-speech vllm wrapper
    # is intentionally NOT imported — we drive raw transformers + snac so
    # the closure installs cleanly on Apple Silicon (vllm is CUDA-only).
    import soundfile as _sf  # noqa: PLC0415 — child-only

    class _OrpheusInProcess:
        """In-process implementation used inside the child venv.

        Loads:
          * ``AutoModelForCausalLM`` from the Orpheus HF repo (Llama-3 3B
            with an audio-extended vocab — see AUDIO_TOKEN_OFFSET above).
          * ``AutoTokenizer`` from the same repo.
          * ``SNAC`` from ``hubertsiuzdak/snac_24khz`` for audio
            encoding (reference WAV → codes) and decoding (model output
            tokens → PCM samples).

        Reference encoding happens per-call: a 12-15s reference produces
        ~360-450 audio tokens, negligible vs the Llama prefill.
        """

        name = "orpheus"
        KNOWN_TUNABLES = OrpheusBackend.KNOWN_TUNABLES

        def __init__(self) -> None:
            self._model: Any = None
            self._tokenizer: Any = None
            self._snac: Any = None
            self._device: str = "cpu"
            self._dtype: Any = None
            self._config: dict = {}

        # ----- TTSBackend Protocol -----

        def load(self, config: dict) -> None:
            import torch  # noqa: PLC0415
            from snac import SNAC  # noqa: PLC0415
            from transformers import AutoModelForCausalLM, AutoTokenizer  # noqa: PLC0415

            requested = config.get("device") or "auto"
            if requested == "auto":
                if torch.cuda.is_available():
                    device = "cuda"
                elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                    device = "mps"
                else:
                    device = "cpu"
            else:
                device = requested

            # On MPS, fp16 is the right call (matches Llama's bf16-pretrained
            # weights closely enough at inference). On CPU we fall back to
            # fp32 to avoid Llama matmul accuracy loss in fp16-emulation paths.
            if device == "cuda":
                dtype = torch.bfloat16
            elif device == "mps":
                dtype = torch.float16
            else:
                dtype = torch.float32

            model_name = config.get("model", DEFAULT_MODEL)
            snac_name = config.get("snac_model", "hubertsiuzdak/snac_24khz")
            logger.info(
                "orpheus child loading model=%s snac=%s on device=%s dtype=%s",
                model_name,
                snac_name,
                device,
                dtype,
            )

            self._tokenizer = AutoTokenizer.from_pretrained(model_name)  # nosec B615 — pinned repo
            self._model = AutoModelForCausalLM.from_pretrained(  # nosec B615 — pinned repo
                model_name,
                torch_dtype=dtype,
            )
            self._model.to(device)
            # Put into inference mode (PyTorch's .eval() — disables dropout,
            # NOT Python's eval() builtin).
            self._model = self._model.eval()  # noqa: S307 — torch eval-mode, not exec

            self._snac = SNAC.from_pretrained(snac_name)  # nosec B615 — pinned repo
            self._snac = self._snac.to(device)
            self._snac = self._snac.eval()  # noqa: S307 — torch eval-mode

            self._device = device
            self._dtype = dtype
            self._config = {"model": model_name, "device": device, "snac_model": snac_name}
            logger.info("orpheus child ready")

        def encode_reference(self, _ref_audio_path: str) -> list | None:
            """Orpheus encodes the reference at synth time; no pre-encode API."""
            return None

        def synthesize(self, text: str, ref: VoiceRef) -> np.ndarray:
            import torch  # noqa: PLC0415

            if self._model is None or self._tokenizer is None or self._snac is None:
                raise RuntimeError("orpheus not loaded")
            if not ref.ref_audio_path:
                raise ValueError("orpheus requires ref_audio_path for cloning")
            if not ref.ref_text:
                raise ValueError("orpheus requires ref_text for cloning")

            sampling = ref.metadata.get("sampling") or {}
            temperature = float(sampling.get("temperature", 0.6))
            top_p = float(sampling.get("top_p", 0.95))
            top_k = int(sampling.get("top_k", 50))
            repetition_penalty = float(sampling.get("repetition_penalty", 1.1))
            max_new_tokens = int(sampling.get("max_tokens", 2048))

            # 1. SNAC-encode the reference audio into 3-stream codes, then
            #    interleave to Orpheus's 7-tokens-per-frame layout.
            ref_audio_tokens = self._encode_reference_to_tokens(ref.ref_audio_path)

            # 2. Build the prompt: combine ref_text + ref_audio_tokens +
            #    target_text into the Orpheus prompt template, in-context-
            #    priming the speaker.
            input_ids = self._build_cloning_prompt(
                ref_text=ref.ref_text,
                ref_audio_tokens=ref_audio_tokens,
                target_text=text,
            )
            input_ids = input_ids.to(self._device)

            # 3. Generate. Stop on either Orpheus's end-of-audio sentinel
            #    or the tokenizer's natural EOS; the model can pick either.
            stop_ids = list(STOP_TOKEN_IDS)
            eos_id = getattr(self._tokenizer, "eos_token_id", None)
            if eos_id is not None and eos_id not in stop_ids:
                stop_ids.append(int(eos_id))

            with torch.inference_mode():
                output = self._model.generate(
                    input_ids=input_ids,
                    max_new_tokens=max_new_tokens,
                    do_sample=True,
                    temperature=temperature,
                    top_p=top_p,
                    top_k=top_k,
                    repetition_penalty=repetition_penalty,
                    eos_token_id=stop_ids,
                    pad_token_id=(eos_id if eos_id is not None else stop_ids[0]),
                )

            # 4. Strip the prompt prefix, extract emitted audio token IDs,
            #    decode via SNAC.
            generated_ids = output[0, input_ids.shape[1] :].tolist()
            return self._decode_audio_tokens(generated_ids)

        def synthesize_stream(self, text: str, ref: VoiceRef) -> Iterator[np.ndarray]:
            """Single-batch streaming fallback for v1.

            True incremental decoding would require streaming the
            ``generate()`` output through a buffer that flushes every
            7 audio tokens to SNAC.decode (one SNAC frame). Plumbing
            that through transformers' streamer requires extra wiring;
            for v1 we yield the full batch.
            """
            yield self.synthesize(text, ref)

        def health(self) -> dict:
            return {
                "name": self.name,
                "loaded": self._model is not None,
                "model": self._config.get("model"),
                "device": self._config.get("device"),
                "snac_model": self._config.get("snac_model"),
                "sample_rate": SAMPLE_RATE,
            }

        def unload(self) -> None:
            import gc  # noqa: PLC0415

            self._model = None
            self._tokenizer = None
            self._snac = None
            gc.collect()
            try:
                import torch  # noqa: PLC0415

                if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                    torch.mps.empty_cache()
                elif torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except (ImportError, AttributeError):
                pass

        # ----- internals -----

        def _encode_reference_to_tokens(self, ref_audio_path: str) -> list[int]:
            """Load ref WAV, resample to 24 kHz mono, SNAC-encode, interleave.

            Returns a flat list of Orpheus audio-token IDs (one per slot
            in the 7-tokens-per-frame layout) ready to splice into a
            prompt for in-context speaker priming.
            """
            import torch  # noqa: PLC0415

            audio, sr = _sf.read(ref_audio_path, dtype="float32", always_2d=False)
            if audio.ndim == 2:
                # multi-channel → mono mix-down
                audio = audio.mean(axis=1)
            if sr != SAMPLE_RATE:
                # Lazy resample with librosa if needed; we expect the
                # registry to keep refs at 24 kHz, but tolerate 44.1/48
                # for ad-hoc paths.
                import librosa  # noqa: PLC0415

                audio = librosa.resample(audio, orig_sr=sr, target_sr=SAMPLE_RATE)
            wav = torch.tensor(audio, dtype=torch.float32, device=self._device).unsqueeze(0)
            # SNAC expects (B, 1, T) — add channel dim.
            wav = wav.unsqueeze(0)

            with torch.inference_mode():
                codes = self._snac.encode(wav)
            # codes: list of three tensors:
            #   codes[0]: (B, F)        — coarse, 1 code/frame
            #   codes[1]: (B, 2F)       — mid,    2 codes/frame
            #   codes[2]: (B, 4F)       — fine,   4 codes/frame
            return self._interleave_snac_codes(codes)

        @staticmethod
        def _interleave_snac_codes(codes: list[Any]) -> list[int]:
            """Pack the 3 SNAC streams into Orpheus's 7-tokens-per-frame layout.

            Mirrors the inverse of decoder.convert_to_audio in canopyai/
            Orpheus-TTS, which scatters streams as:

                frame j:
                  slot 0 = codes_0[j]
                  slot 1 = codes_1[2j]
                  slot 2 = codes_2[4j]
                  slot 3 = codes_2[4j+1]
                  slot 4 = codes_1[2j+1]
                  slot 5 = codes_2[4j+2]
                  slot 6 = codes_2[4j+3]

            Each slot's audio-token ID is offset by ``slot * 4096`` plus
            the global ``AUDIO_TOKEN_OFFSET``.
            """
            c0 = codes[0][0].tolist()  # (F,)
            c1 = codes[1][0].tolist()  # (2F,)
            c2 = codes[2][0].tolist()  # (4F,)
            num_frames = len(c0)
            tokens: list[int] = []
            for j in range(num_frames):
                slot_values = [
                    c0[j],
                    c1[2 * j],
                    c2[4 * j],
                    c2[4 * j + 1],
                    c1[2 * j + 1],
                    c2[4 * j + 2],
                    c2[4 * j + 3],
                ]
                for slot_idx, value in enumerate(slot_values):
                    tokens.append(
                        AUDIO_TOKEN_OFFSET + (slot_idx * AUDIO_CODEBOOK_SIZE) + int(value)
                    )
            return tokens

        def _build_cloning_prompt(
            self,
            ref_text: str,
            ref_audio_tokens: list[int],
            target_text: str,
        ) -> Any:
            """Build the input_ids tensor for in-context voice cloning.

            Layout follows canopyai/Orpheus-TTS' train.py speech/text pair
            convention, adapted for inference-time priming:

              [START_OF_HUMAN] ref_text [END_TEXT] ref_audio_tokens
              [START_OF_HUMAN] target_text [END_TEXT]
              <model continues here with target speech tokens>

            Where:
              START_OF_HUMAN     = 128259
              END_TEXT...        = (128009, 128260, 128261, 128257) — the
                                   four-token closer used by engine_class.py
                                   (terminates the text turn; the audio that
                                   follows is what the model generates).

            We keep this simple — the upstream cloning recipe is still
            evolving (see canopyai README checklist: "Fix voice cloning
            Colab notebook implementation"). The structure here is a
            close mirror of train.py's training-time concatenation.
            """
            import torch  # noqa: PLC0415

            ref_text_ids = self._tokenizer(ref_text, return_tensors="pt").input_ids[0].tolist()
            tgt_text_ids = self._tokenizer(target_text, return_tensors="pt").input_ids[0].tolist()

            sequence: list[int] = []
            sequence.append(START_OF_HUMAN_ID)
            sequence.extend(ref_text_ids)
            sequence.extend(END_TEXT_IDS)
            sequence.extend(ref_audio_tokens)
            sequence.append(START_OF_HUMAN_ID)
            sequence.extend(tgt_text_ids)
            sequence.extend(END_TEXT_IDS)

            return torch.tensor([sequence], dtype=torch.long)

        def _decode_audio_tokens(self, generated_ids: list[int]) -> np.ndarray:
            """Decode emitted audio token IDs → 24 kHz mono float32 PCM.

            1. Filter to audio-vocab range, dropping any control/text IDs.
            2. Reassemble the 7-token frame structure → 3 SNAC streams.
            3. SNAC.decode → PCM.
            """
            import torch  # noqa: PLC0415

            # Strip non-audio token IDs (control markers, surprise text).
            # An audio token ID is in [AUDIO_TOKEN_OFFSET, AUDIO_TOKEN_OFFSET +
            # 7 * AUDIO_CODEBOOK_SIZE). Anything else is a control / non-audio
            # token — drop it without panicking.
            audio_max = AUDIO_TOKEN_OFFSET + AUDIO_TOKENS_PER_FRAME * AUDIO_CODEBOOK_SIZE
            audio_ids = [t for t in generated_ids if AUDIO_TOKEN_OFFSET <= t < audio_max]

            # Truncate to a whole-frame multiple of 7. Stragglers (model
            # cut off mid-frame) get discarded rather than crashing decode.
            frame_count = len(audio_ids) // AUDIO_TOKENS_PER_FRAME
            if frame_count == 0:
                logger.warning(
                    "orpheus: generated %d total tokens but no complete audio frames",
                    len(generated_ids),
                )
                return np.zeros(0, dtype=np.float32)
            audio_ids = audio_ids[: frame_count * AUDIO_TOKENS_PER_FRAME]

            # Reverse the interleave to recover SNAC streams.
            c0: list[int] = []
            c1: list[int] = []
            c2: list[int] = []
            for j in range(frame_count):
                base = j * AUDIO_TOKENS_PER_FRAME
                # Each slot's raw codebook value comes from
                # (token_id - AUDIO_TOKEN_OFFSET) - slot_idx * 4096
                slot_vals: list[int] = []
                for slot_idx in range(AUDIO_TOKENS_PER_FRAME):
                    raw = audio_ids[base + slot_idx] - AUDIO_TOKEN_OFFSET
                    val = raw - slot_idx * AUDIO_CODEBOOK_SIZE
                    if not (0 <= val < AUDIO_CODEBOOK_SIZE):
                        # Token landed outside its slot's range. Skip the
                        # whole frame — partial frames cause SNAC to emit
                        # noise bursts.
                        slot_vals = []
                        break
                    slot_vals.append(val)
                if not slot_vals:
                    continue
                c0.append(slot_vals[0])
                c1.extend([slot_vals[1], slot_vals[4]])
                c2.extend([slot_vals[2], slot_vals[3], slot_vals[5], slot_vals[6]])

            if not c0:
                logger.warning("orpheus: all frames rejected during de-interleave; empty audio")
                return np.zeros(0, dtype=np.float32)

            codes = [
                torch.tensor([c0], dtype=torch.int32, device=self._device),
                torch.tensor([c1], dtype=torch.int32, device=self._device),
                torch.tensor([c2], dtype=torch.int32, device=self._device),
            ]
            with torch.inference_mode():
                audio_hat = self._snac.decode(codes)
            # audio_hat shape: (1, 1, T) → squeeze to (T,)
            audio = audio_hat.squeeze().detach().cpu().numpy().astype(np.float32)
            return audio

    register_backend("orpheus", _OrpheusInProcess)
else:
    register_backend("orpheus", OrpheusBackend)
