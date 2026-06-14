"""Higgs Audio V2 backend (subprocess-isolated).

Boson AI's open-weights multimodal audio foundation model. Audio is a
first-class modality in the same representation space as text → the
model can in-context-learn voice characteristics (including accent)
from a short reference clip with high fidelity. Native voice cloning.

Provision once with ``voice-forge backend install higgs``.

Sibling to ``orpheus`` — both are LLM-backbone TTS models added to
voice-forge in response to F5/diffusion-based backends not preserving
heavy non-default accents on certain voice profiles. Higgs uses a
different architectural lineage (multimodal audio foundation, not
Llama-finetune) so they should produce different artifacts when tuning
or when one of them fails; having both available lets the operator
pick per voice.

Voice paradigm: clone. Same VoiceRef shape as F5 / NeuTTS / Orpheus.

Streaming: v1 is single-batch fallback. Upstream's
HiggsAudioModelClient generates the whole audio token stream then
decodes it via the codec; true streaming would require an
AsyncStreamer-style hook (their `serve_engine` module has one but is
not packaged on PyPI as of 2026-05-26).

Resources: ~3-4 GB fp16 on Apple Silicon MPS; ~1-2 GB int4 quantized.
Cold load ~15-25s. Inference ~0.7-1x realtime on M2 Ultra.

HF model: ``bosonai/higgs-audio-v2-generation-3B-base``. Pulled lazily on
first synth call.

Architecture note (2026-05-26 rewrite)
======================================

The first version of this backend imported ``HiggsAudioServeEngine`` from
``boson_multimodal.serve.serve_engine`` and let the upstream ServeEngine
handle the entire model+tokenizer+ChatML lifecycle. Then we discovered
that the wheel built from ``git+https://github.com/boson-ai/higgs-audio.git``
silently drops both the ``serve/`` and ``audio_processing/`` subdirectories
because they ship without ``__init__.py`` markers and setuptools' default
``find_packages`` walks them off the manifest. The ServeEngine import
fails at runtime; voice cloning is impossible without
``audio_processing.higgs_audio_tokenizer``.

The rewrite mirrors the upstream reference inference script
(``examples/generation.py``) which uses a custom ``HiggsAudioModelClient``
that talks DIRECTLY to ``HiggsAudioModel.generate()`` + the audio
tokenizer's ``encode/decode`` methods + the chatml dataset collator. That
path uses only modules the wheel actually ships — plus the
``audio_processing/`` subtree, which we materialise via
``_higgs_post_install.run()`` at provision time.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterator
from typing import Any

import numpy as np

from . import VoiceRef, register_backend
from ._subprocess import SubprocessBackend

logger = logging.getLogger("voice_forge.backends.higgs")

DEFAULT_MODEL = "bosonai/higgs-audio-v2-generation-3B-base"
DEFAULT_TOKENIZER = "bosonai/higgs-audio-v2-tokenizer"
# Both the model and the tokenizer's `main` branches got a `trfms-support`
# rewrite on 2026-04-04 that swapped to a transformers-style nested config
# schema. The open-source `HiggsAudioModel` / `HiggsAudioTokenizer` classes
# in the same repo's source tree still expect the OLDER flat-config schema
# (issue #176 — open as of 2026-05-26). Pin BOTH repos to the last revision
# before the breakage so the installed Python classes can deserialize their
# own checkpoints. When upstream synchronises class signatures with the
# new configs (or ships v3 artefacts), unpin and bump.
DEFAULT_TOKENIZER_REVISION = "9d4988fbd4ad07b4cac3a5fa462741a41810dbec"
DEFAULT_MODEL_REVISION = "10840182ca4ad5d9d9113b60b9bb3c1ef1ba3f84"
SAMPLE_RATE = 24_000


class HiggsBackend(SubprocessBackend):
    """Higgs Audio V2 subprocess backend (parent-side wrapper)."""

    name = "higgs"

    KNOWN_TUNABLES = {
        "temperature": {
            "type": "float",
            "min": 0.1,
            "max": 1.5,
            "default": 0.3,
            "description": "Sampling temperature. Lower = more faithful to reference.",
        },
        "top_p": {
            "type": "float",
            "min": 0.1,
            "max": 1.0,
            "default": 0.95,
            "description": "Nucleus sampling.",
        },
        "top_k": {
            "type": "int",
            "min": 1,
            "max": 200,
            "default": 50,
            "description": "Top-k filter for token selection.",
        },
        "max_new_tokens": {
            "type": "int",
            "min": 256,
            "max": 8192,
            "default": 2048,
            "description": "Max new audio tokens. Higher supports longer utterances.",
        },
        "ras_win_len": {
            "type": "int",
            "min": 0,
            "max": 32,
            "default": 7,
            "description": (
                "Repetition-Avoidance Sampling window length. 0 disables RAS. "
                "Upstream default is 7; tightens prosody at long utterances."
            ),
        },
        "ras_win_max_num_repeat": {
            "type": "int",
            "min": 1,
            "max": 8,
            "default": 2,
            "description": "Max RAS repeats inside the window.",
        },
        "seed": {
            "type": "int",
            "min": 0,
            "max": 2_147_483_647,
            "default": 123,
            "description": "Generation seed for reproducibility.",
        },
    }


if os.environ.get("VOICE_FORGE_SUBPROCESS_CHILD") == "1":
    # ----- Child-only heavy imports -----
    #
    # Mirrors upstream's `examples/generation.py:HiggsAudioModelClient`. We
    # talk directly to HiggsAudioModel (no ServeEngine wrapper) because
    # the wheel doesn't ship `boson_multimodal.serve` — see this module's
    # top-level docstring for the full root-cause writeup.
    import queue  # noqa: PLC0415
    import threading  # noqa: PLC0415
    from dataclasses import asdict  # noqa: PLC0415

    import torch  # noqa: PLC0415
    from boson_multimodal.audio_processing.higgs_audio_tokenizer import (  # noqa: PLC0415
        load_higgs_audio_tokenizer,
    )
    from boson_multimodal.data_collator.higgs_audio_collator import (  # noqa: PLC0415
        HiggsAudioSampleCollator,
    )
    from boson_multimodal.data_types import (  # noqa: PLC0415
        AudioContent,
        ChatMLSample,
        Message,
    )
    from boson_multimodal.dataset.chatml_dataset import (  # noqa: PLC0415
        ChatMLDatasetSample,
        prepare_chatml_sample,
    )
    from boson_multimodal.model.higgs_audio import HiggsAudioModel  # noqa: PLC0415
    from boson_multimodal.model.higgs_audio.utils import revert_delay_pattern  # noqa: PLC0415
    from huggingface_hub import snapshot_download  # noqa: PLC0415
    from transformers import AutoConfig, AutoTokenizer  # noqa: PLC0415
    from transformers.generation.streamers import BaseStreamer  # noqa: PLC0415

    # ------------------------------------------------------------------
    # Streaming knobs
    # ------------------------------------------------------------------
    # How many audio frames to buffer before yielding the first PCM chunk.
    # Each frame is 1 / FRAME_RATE = 40 ms at the audio tokenizer's 25 Hz
    # frame rate, so STREAM_FIRST_CHUNK_FRAMES=10 means we wait for ~0.4 s
    # of audio tokens before we first decode + yield. On M2 Ultra MPS this
    # gives a first-audio latency of ~2.5–3.5 s (model takes ~100 ms per
    # token to generate at this seq_len, plus a one-shot CPU decode).
    #
    # Subsequent yields happen every STREAM_CHUNK_FRAMES frames thereafter.
    # Larger chunks → fewer re-decodes (each re-decode is O(N_total_frames)
    # because we decode the full accumulated token stream each time to
    # avoid codec-edge artifacts), smaller chunks → finer-grained playback
    # cadence at the cost of more total decode wall time.
    #
    # On M2 Ultra the per-token generation rate is ~0.4× realtime, so the
    # stream falls behind playback if the consumer reads in realtime — but
    # for hermes-agent's "start playing as soon as audio is available" use
    # case the metric that matters is first-audio latency, not total
    # throughput. See LEARNINGS file for the full perf investigation.
    STREAM_FIRST_CHUNK_FRAMES = 10  # 0.4 s — minimise first-audio latency
    STREAM_CHUNK_FRAMES = 25  # 1.0 s — balance overhead vs cadence
    STREAM_FRAME_RATE = 25  # matches HiggsAudioTokenizer.frame_rate

    class _SyncAudioStreamer(BaseStreamer):
        """Sync-queue streamer that collects per-step audio token columns.

        ``HiggsAudioModel.generate()`` calls ``put()`` once per generation
        step. In audio-generation mode the value is shape
        ``[audio_num_codebooks]`` (the codes for ONE frame). In text mode
        the value is shape ``[1]`` (a single text token). We discriminate
        by shape and enqueue only audio frames; text tokens are dropped
        because we never need them on the streaming path.

        The queue is a stdlib ``queue.Queue``; the generator thread blocks
        on ``put()`` if the consumer is slow, and the consumer blocks on
        ``get()`` if the generator is still running — natural backpressure.
        """

        def __init__(self, audio_num_codebooks: int) -> None:
            self._audio_num_codebooks = audio_num_codebooks
            self._queue: queue.Queue = queue.Queue()
            self._STOP = object()

        def put(self, value: torch.Tensor) -> None:  # noqa: F821
            # `next_audio_tokens` arrives as a 1-D tensor of length
            # num_codebooks. `next_tokens` (text) arrives as a 1-D tensor
            # of length 1 (or batch). Use the shape to discriminate.
            if value.shape[0] == self._audio_num_codebooks:
                self._queue.put(value)
            # else: text tokens, discard for the streaming path

        def end(self) -> None:
            self._queue.put(self._STOP)

        def __iter__(self):
            return self

        def __next__(self):
            item = self._queue.get()
            if item is self._STOP:
                raise StopIteration
            return item

    class _HiggsInProcess:
        """In-process implementation used inside the child venv.

        Direct port of upstream's HiggsAudioModelClient adapted to the
        voice_forge backend Protocol. Loads the model + audio tokenizer +
        text tokenizer + collator once at ``load()``; reuses them across
        synth calls.
        """

        name = "higgs"
        KNOWN_TUNABLES = HiggsBackend.KNOWN_TUNABLES

        def __init__(self) -> None:
            # These hold fully-untyped 3rd-party objects (HiggsAudioModel,
            # transformers tokenizer/config, the audio tokenizer) loaded lazily in
            # load(); typed Any so attribute access on the untyped stack is honest
            # to mypy without per-line ignores.
            self._model: Any = None  # HiggsAudioModel
            self._audio_tokenizer: Any = None  # HiggsAudioTokenizer
            self._tokenizer: Any = None  # transformers tokenizer
            self._config_obj: Any = None  # transformers AutoConfig
            self._collator: HiggsAudioSampleCollator | None = None
            self._device: str = "cpu"
            self._config: dict = {}

        # ----- lifecycle -----

        def load(self, config: dict) -> None:
            requested = config.get("device") or "auto"
            if requested == "auto":
                if torch.cuda.is_available():
                    device = "cuda:0"
                elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                    device = "mps"
                else:
                    device = "cpu"
            else:
                device = requested
            self._device = device

            model_name = config.get("model", DEFAULT_MODEL)
            tokenizer_name = config.get("tokenizer", DEFAULT_TOKENIZER)
            tokenizer_revision = config.get("tokenizer_revision", DEFAULT_TOKENIZER_REVISION)
            model_revision = config.get("model_revision", DEFAULT_MODEL_REVISION)
            logger.info(
                "higgs child loading %s @ %s on device=%s",
                model_name,
                model_revision or "main",
                device,
            )

            # Resolve the audio tokenizer to a LOCAL snapshot pinned at the
            # pre-`trfms-support` revision. load_higgs_audio_tokenizer's
            # snapshot_download() call doesn't accept a revision arg, but if
            # we hand it a local path it bypasses the network entirely.
            # See DEFAULT_TOKENIZER_REVISION for the upstream issue context.
            if tokenizer_revision and not os.path.isdir(tokenizer_name):
                tokenizer_local = snapshot_download(tokenizer_name, revision=tokenizer_revision)
                logger.info(
                    "higgs pinned tokenizer to revision %s at %s",
                    tokenizer_revision,
                    tokenizer_local,
                )
            else:
                tokenizer_local = tokenizer_name

            # The audio tokenizer can't run its semantic backbone on MPS
            # cleanly (upstream's reference forces CPU there). Pin the
            # tokenizer's device to CPU when the model is on MPS; the
            # model still runs on MPS for the big forward pass.
            audio_tok_device = "cpu" if device == "mps" else device
            self._audio_tokenizer = load_higgs_audio_tokenizer(
                tokenizer_local,
                device=audio_tok_device,
            )

            # bfloat16 keeps the 3B model in ~3 GB on MPS. fp32 is
            # ~12 GB which is fine on a 128 GB M2 Ultra but wasteful.
            # `revision` pins to the pre-`trfms-support` model — see
            # DEFAULT_MODEL_REVISION docstring for the version-skew context.
            from_pretrained_kwargs: dict = {
                "device_map": device,
                "torch_dtype": torch.bfloat16,
            }
            if model_revision:
                from_pretrained_kwargs["revision"] = model_revision
            self._model = HiggsAudioModel.from_pretrained(  # nosec B615 — model pinned
                model_name, **from_pretrained_kwargs
            )
            # Put the model into inference mode (no dropout, frozen BN, etc.).
            self._model.eval()  # noqa: B018 — torch.nn.Module.eval(), not Python eval

            text_tok_kwargs: dict = {}
            if model_revision:
                text_tok_kwargs["revision"] = model_revision
            # nosec B615 — same pinned model repo as the model load above; revision
            # rides text_tok_kwargs when model_revision is configured.
            self._tokenizer = AutoTokenizer.from_pretrained(  # nosec B615
                model_name, **text_tok_kwargs
            )
            self._config_obj = AutoConfig.from_pretrained(  # nosec B615
                model_name, **text_tok_kwargs
            )
            self._collator = HiggsAudioSampleCollator(
                whisper_processor=None,
                audio_in_token_id=self._config_obj.audio_in_token_idx,
                audio_out_token_id=self._config_obj.audio_out_token_idx,
                audio_stream_bos_id=self._config_obj.audio_stream_bos_id,
                audio_stream_eos_id=self._config_obj.audio_stream_eos_id,
                encode_whisper_embed=self._config_obj.encode_whisper_embed,
                pad_token_id=self._config_obj.pad_token_id,
                return_audio_in_tokens=self._config_obj.encode_audio_in_tokens,
                use_delay_pattern=self._config_obj.use_delay_pattern,
                round_to=1,
                audio_num_codebooks=self._config_obj.audio_num_codebooks,
            )

            self._config = {
                "model": model_name,
                "device": device,
                "tokenizer": tokenizer_name,
            }
            logger.info("higgs child ready")

        def unload(self) -> None:
            import gc  # noqa: PLC0415

            self._model = None
            self._audio_tokenizer = None
            self._tokenizer = None
            self._config_obj = None
            self._collator = None
            gc.collect()
            try:
                if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                    torch.mps.empty_cache()
                elif torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except (AttributeError, RuntimeError):
                pass

        def encode_reference(self, _ref_audio_path: str) -> list | None:
            """Higgs encodes the reference at synth time via the audio tokenizer."""
            return None

        def health(self) -> dict:
            return {
                "name": self.name,
                "loaded": self._model is not None,
                "model": self._config.get("model"),
                "device": self._config.get("device"),
                "sample_rate": SAMPLE_RATE,
            }

        # ----- synth -----

        def _build_messages(self, ref: VoiceRef) -> tuple[list, list]:
            """Construct the conversational priming for voice cloning.

            Follows upstream's `prepare_generation_context` shape for the
            single-speaker, ref-not-in-system-message variant:
              [system] → "Generate audio following instruction."
              [user]   → the reference transcript text
              [assistant] → the reference audio (placeholder for tokens
                            from the audio tokenizer, materialised in
                            `audio_ids`)
              [user]   → (appended later) the target text to read

            Returns:
                Tuple of (priming-messages, audio_ids list). The audio
                tokens for the reference are baked into `audio_ids`; the
                model client wires them into the collator sample.
            """
            if not ref.ref_audio_path or not ref.ref_text:
                raise ValueError("higgs requires ref_audio_path + ref_text for cloning")
            system_message = Message(
                role="system",
                content="Generate audio following instruction.",
            )
            # encode() returns a torch.LongTensor of VQ codes; we collect
            # one per reference speaker. Single-speaker for v1.
            ref_audio_tokens = self._audio_tokenizer.encode(ref.ref_audio_path)
            user_ref = Message(role="user", content=ref.ref_text)
            assistant_ref = Message(
                role="assistant",
                content=AudioContent(audio_url=ref.ref_audio_path),
            )
            return [system_message, user_ref, assistant_ref], [ref_audio_tokens]

        # ------------------------------------------------------------------
        # Generation helpers (shared by sync + streaming paths)
        # ------------------------------------------------------------------

        def _resolve_sampling(self, ref: VoiceRef) -> dict:
            """Extract sampling knobs from the VoiceRef + tunable defaults."""
            sampling = ref.metadata.get("sampling") or {}
            ras_win_len_raw = int(sampling.get("ras_win_len", 7))
            return {
                "temperature": float(sampling.get("temperature", 0.3)),
                "top_p": float(sampling.get("top_p", 0.95)),
                "top_k": int(sampling.get("top_k", 50)),
                "max_new_tokens": int(sampling.get("max_new_tokens", 2048)),
                "ras_win_len": ras_win_len_raw if ras_win_len_raw > 0 else None,
                "ras_win_max_num_repeat": int(sampling.get("ras_win_max_num_repeat", 2)),
                "seed": int(sampling.get("seed", 123)),
            }

        def _build_batch(self, text: str, ref: VoiceRef) -> dict:
            """Build the device-resident batch dict consumed by generate().

            Hoisted out of ``_generate_audio`` so both the blocking and
            streaming synthesise paths share the same ChatML construction.
            """
            assert self._tokenizer is not None  # nosec B101 — narrowing
            assert self._collator is not None  # nosec B101 — narrowing

            priming, audio_ids = self._build_messages(ref)
            target_msg = Message(role="user", content=text)
            chatml_sample = ChatMLSample(messages=[*priming, target_msg])

            input_tokens, _, _, _ = prepare_chatml_sample(chatml_sample, self._tokenizer)
            postfix = self._tokenizer.encode(
                "<|start_header_id|>assistant<|end_header_id|>\n\n",
                add_special_tokens=False,
            )
            input_tokens = list(input_tokens) + list(postfix)

            sample = ChatMLDatasetSample(
                input_ids=torch.LongTensor(input_tokens),
                label_ids=None,
                audio_ids_concat=torch.concat([a.cpu() for a in audio_ids], dim=1),
                audio_ids_start=torch.cumsum(
                    torch.tensor([0] + [a.shape[1] for a in audio_ids], dtype=torch.long),
                    dim=0,
                ),
                audio_waveforms_concat=None,
                audio_waveforms_start=None,
                audio_sample_rate=None,
                audio_speaker_indices=None,
            )

            batch_data = self._collator([sample])
            batch = asdict(batch_data)
            for k, v in batch.items():
                if isinstance(v, torch.Tensor):
                    batch[k] = v.contiguous().to(self._device)
            return batch

        def _decode_audio_tokens(self, audio_out_ids: torch.Tensor) -> np.ndarray:  # noqa: F821
            """Decode a [num_codebooks, num_frames] tensor to float32 PCM.

            Handles the standard upstream post-processing: optional
            delay-pattern reversion, clip into the codebook range, and a
            move to the audio tokenizer's device (CPU on MPS). The caller
            is responsible for stripping BOS/EOS sentinels appropriately
            for their use case — the non-streaming path strips both, the
            streaming path strips BOS only at the start and EOS only at
            the final flush.
            """
            assert self._audio_tokenizer is not None  # nosec B101 — narrowing
            if audio_out_ids.shape[1] == 0:
                return np.zeros(0, dtype=np.float32)
            if audio_out_ids.device.type == "mps":
                audio_out_ids = audio_out_ids.detach().cpu()
            wave = self._audio_tokenizer.decode(audio_out_ids.unsqueeze(0))
            return np.asarray(wave[0, 0], dtype=np.float32)

        @torch.inference_mode()
        def _generate_audio(
            self,
            text: str,
            ref: VoiceRef,
        ) -> np.ndarray:
            """Core generation. Returns float32 PCM in [-1, 1] at 24 kHz."""
            if self._model is None or self._audio_tokenizer is None:
                raise RuntimeError("higgs not loaded")
            assert self._config_obj is not None  # nosec B101 — narrowing

            samp = self._resolve_sampling(ref)
            batch = self._build_batch(text, ref)

            outputs = self._model.generate(
                **batch,
                max_new_tokens=samp["max_new_tokens"],
                use_cache=True,
                do_sample=True,
                temperature=samp["temperature"],
                top_k=samp["top_k"],
                top_p=samp["top_p"],
                past_key_values_buckets=None,  # static KV cache off (MPS-incompatible)
                ras_win_len=samp["ras_win_len"],
                ras_win_max_num_repeat=samp["ras_win_max_num_repeat"],
                stop_strings=["<|end_of_text|>", "<|eot_id|>"],
                tokenizer=self._tokenizer,
                seed=samp["seed"],
            )

            # outputs[1] is the per-codebook audio token tensor list. Apply
            # the delay-pattern reversion when the model config requires it,
            # then clip to the codebook range, strip the BOS/EOS markers,
            # and decode through the audio tokenizer's VQ decoder.
            codebook_size = int(self._audio_tokenizer.codebook_size)
            step_audio_out_ids = []
            for ele in outputs[1]:
                ids = ele
                if self._config_obj.use_delay_pattern:
                    ids = revert_delay_pattern(ids)
                # The [:, 1:-1] strip removes the audio_stream_bos /
                # audio_stream_eos sentinels — mirrors upstream exactly.
                step_audio_out_ids.append(ids.clip(0, codebook_size - 1)[:, 1:-1])
            audio_out_ids = torch.concat(step_audio_out_ids, dim=1)
            return self._decode_audio_tokens(audio_out_ids)

        def synthesize(self, text: str, ref: VoiceRef) -> np.ndarray:
            return self._generate_audio(text, ref)

        def synthesize_stream(self, text: str, ref: VoiceRef) -> Iterator[np.ndarray]:
            """Stream PCM as the model produces audio tokens.

            Implementation
            --------------

            ``HiggsAudioModel.generate()`` accepts a ``streamer`` keyword
            (the upstream pattern lifted from ``AsyncHiggsAudioStreamer``
            in the unshipped ``boson_multimodal.serve.serve_engine`` —
            we ported the queue protocol but use a stdlib threading
            ``Queue`` instead of asyncio so it composes cleanly with the
            ``Iterator[np.ndarray]`` Protocol the rest of voice-forge uses).
            We run ``generate()`` in a worker thread and consume audio
            token frames from the queue here, decoding + yielding PCM
            chunks every ``STREAM_CHUNK_FRAMES`` frames.

            Why decode the full accumulated tokens each yield?
            --------------------------------------------------

            The audio tokenizer's decoder is a stack of strided
            convolutions (descript-audio-codec ``dac2.Decoder``) with
            non-trivial receptive field. Decoding each new chunk in
            isolation produces audible clicks at chunk boundaries.
            Re-decoding the full token stream each yield and slicing out
            only the new samples gives a click-free stream at the cost of
            O(N²) total decode work — for typical conversational
            sentences (<10 s of audio) this overhead is ~5–10 s wall time
            and acceptable.

            First-audio latency
            -------------------

            On M2 Ultra MPS we measured ~3 s from synth start to first
            non-empty PCM yield (the model generates ~10 audio tokens in
            ~2.5 s, plus ~50 ms for the first decode). After the first
            chunk, per-chunk wall time is ~1.4 s per 0.4 s of audio —
            the stream cannot keep up with realtime playback on this
            hardware, but the first-audio drop is enough to feel
            conversational at the sentence-pump granularity hermes-agent
            uses. See the LEARNINGS journal entry from 2026-05-26 for
            the full perf-investigation context.
            """
            if self._model is None or self._audio_tokenizer is None:
                raise RuntimeError("higgs not loaded")
            assert self._config_obj is not None  # nosec B101 — narrowing
            assert self._tokenizer is not None  # nosec B101 — narrowing

            samp = self._resolve_sampling(ref)
            batch = self._build_batch(text, ref)

            audio_num_codebooks = int(self._config_obj.audio_num_codebooks)
            streamer = _SyncAudioStreamer(audio_num_codebooks=audio_num_codebooks)
            codebook_size = int(self._audio_tokenizer.codebook_size)
            use_delay_pattern = bool(self._config_obj.use_delay_pattern)
            # When the model uses delay-pattern coding the token buffer
            # carries `num_codebooks - 1` extra leading "delay" columns
            # that ``revert_delay_pattern`` consumes — they don't map to
            # audible frames. The effective audio frame count for a
            # buffer of length L is therefore L - delay_pad. Without
            # delay pattern, all columns are real frames.
            delay_pad = (audio_num_codebooks - 1) if use_delay_pattern else 0

            # Worker thread runs generate() blocking; main thread consumes
            # the streamer queue. inference_mode is set on the worker side
            # because the model's forward + sample loops both need it.
            generate_kwargs = dict(
                **batch,
                max_new_tokens=samp["max_new_tokens"],
                use_cache=True,
                do_sample=True,
                temperature=samp["temperature"],
                top_k=samp["top_k"],
                top_p=samp["top_p"],
                past_key_values_buckets=None,
                ras_win_len=samp["ras_win_len"],
                ras_win_max_num_repeat=samp["ras_win_max_num_repeat"],
                stop_strings=["<|end_of_text|>", "<|eot_id|>"],
                tokenizer=self._tokenizer,
                seed=samp["seed"],
                streamer=streamer,
            )

            # Capture exceptions from the worker so we can re-raise on
            # the main thread; otherwise a generation crash would just
            # silently end the iterator.
            worker_exc: list[BaseException] = []

            def _worker() -> None:
                try:
                    with torch.inference_mode():
                        self._model.generate(**generate_kwargs)
                except BaseException as e:  # noqa: BLE001 — re-raised below
                    worker_exc.append(e)
                    streamer.end()  # unblock the consumer

            thread = threading.Thread(target=_worker, daemon=True)
            thread.start()

            try:
                cols: list[torch.Tensor] = []  # noqa: F821 — torch.Tensor
                yielded_samples = 0
                first_chunk_done = False

                def _decode_accumulated(strip_eos: bool) -> np.ndarray:
                    """Decode the full token buffer to PCM with proper sentinel stripping.

                    Always strips the leading BOS sentinel (frame 0).
                    Strips the trailing EOS sentinel iff ``strip_eos`` —
                    only true on the final flush after the generator
                    thread signalled end-of-stream.
                    """
                    if not cols:
                        return np.zeros(0, dtype=np.float32)
                    ids = torch.stack(cols, dim=1)
                    if use_delay_pattern:
                        ids = revert_delay_pattern(ids)
                    ids = ids.clip(0, codebook_size - 1)
                    end = ids.shape[1] - 1 if strip_eos else ids.shape[1]
                    ids = ids[:, 1:end]  # strip BOS always, EOS conditionally
                    return self._decode_audio_tokens(ids)

                while True:
                    try:
                        item = next(streamer)
                    except StopIteration:
                        break
                    cols.append(item)

                    # Effective audible frames available so far:
                    #   len(cols) - delay_pad   (delay-pattern padding)
                    #                  - 1      (audio_stream_bos sentinel)
                    # Once divided into how many we've already shipped
                    # (yielded_samples / 960), the remainder is the new
                    # frames waiting to be yielded.
                    samples_per_frame = SAMPLE_RATE // STREAM_FRAME_RATE
                    usable_frames = max(0, len(cols) - delay_pad - 1)
                    yielded_frames = yielded_samples // samples_per_frame
                    threshold = (
                        STREAM_FIRST_CHUNK_FRAMES if not first_chunk_done else STREAM_CHUNK_FRAMES
                    )
                    if usable_frames - yielded_frames < threshold:
                        continue

                    # Decode without EOS strip (we haven't seen EOS yet).
                    pcm = _decode_accumulated(strip_eos=False)
                    new_pcm = pcm[yielded_samples:]
                    if new_pcm.size == 0:
                        continue
                    yielded_samples = pcm.size
                    first_chunk_done = True
                    yield new_pcm

                # Re-raise worker exceptions surfaced via worker_exc.
                if worker_exc:
                    raise worker_exc[0]

                # Final flush with EOS-strip so the assembled stream
                # matches the non-streaming output to within sample
                # rounding.
                final_pcm = _decode_accumulated(strip_eos=True)
                new_pcm = final_pcm[yielded_samples:]
                if new_pcm.size > 0:
                    yield new_pcm
            finally:
                thread.join(timeout=30.0)

    register_backend("higgs", _HiggsInProcess)
else:
    register_backend("higgs", HiggsBackend)
