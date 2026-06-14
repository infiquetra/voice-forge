"""Higgs Audio V2 - MLX backend (subprocess-isolated, Apple Silicon only).

Sibling to ``higgs.py``. Same Boson AI Higgs Audio v2 model, but the
weights are the community MLX port at
``mlx-community/higgs-audio-v2-3B-mlx-q6`` driven by the
``mlx_audio.tts.models.higgs_audio.HiggsAudioServer`` API from the
``kaioct-labs/mlx-audio`` fork (``higgs-overlap-add-streaming`` branch,
pending merge into ``Blaizzy/mlx-audio``).

Why a separate backend instead of replacing ``higgs.py``?
=========================================================

The transformers-based Higgs backend in ``higgs.py`` runs at ~2.45-3x
slower than realtime on M2 Ultra MPS - bfloat16, no MPS-optimised
matmul kernels for the codec, KV-cache reshuffles that MPS can't fuse.
The MLX port lands at ~0.33x RTF on M5 Max (model card benchmark) and
should be sub-realtime on M2 Ultra too. That's the perf win the
prior perf review flagged as needing an MLX port; the community
already did the port.

Keeping the two side-by-side lets:

- Apple-Silicon hosts pick ``higgs-mlx`` for production.
- Non-Apple-Silicon hosts (Linux CUDA, x86 Mac, CI runners on Linux)
  fall back to ``higgs``.
- The transformers backend stay a known-good reference whenever an
  MLX-side discrepancy needs A/B comparison.

Provision once with ``voice-forge backend install higgs-mlx``.

Voice paradigm: clone. Same VoiceRef shape as ``higgs``.

Streaming
=========

The MLX server exposes three generation entry points:

- ``generate()``                 - blocking, full-utterance.
- ``generate_stream()``          - full-generate-then-chunk (no TTFB win
                                   over ``generate()``; yields 640 ms
                                   slices after the whole utterance is
                                   decoded).
- ``generate_stream_overlap_add()`` - mid-generation overlap-add.

The natural choice is ``generate_stream_overlap_add`` for the
``synthesize_stream`` Protocol. We do NOT use it. Reason:

MLX's GPU stream context is thread-local - ``mx.eval()`` only works on
the thread that loaded the model. The ``synthesize_stream`` generator
is consumed inside FastAPI's worker thread pool when the subprocess
shim wraps it in a ``StreamingResponse``, which calls
``anyio.to_thread.run_sync`` to drive the iterator. The overlap-add
path's mid-generation ``mx.eval`` crashes with
``RuntimeError: There is no Stream(gpu, 1) in current thread``.

The workaround is full-generate-then-chunk: ``synthesize_stream`` calls
the blocking ``generate()`` on the load thread, then yields 640 ms PCM
slices from the materialised buffer. The Protocol shape stays correct
(consumer sees a multi-chunk iterator) but TTFB equals total synth
time. For voices that synthesise at 0.31x RTF this is fine for
sentence-pump streaming; for long monologues with strict TTFB needs,
use the transformers ``higgs`` backend's true-streaming path instead.

Apple Silicon guard
===================

MLX is Apple-Silicon only. The backend's ``load()`` raises a clear
``RuntimeError`` on non-arm64 / non-Darwin hosts rather than letting
the venv installer fail mid-way through pulling MLX wheels.

Resources
=========

- q8 model (default): ~6.18 GB on disk, fits in ~7 GB unified memory at
  runtime.
- q6 model: ~4.75 GB; not the default - see DEFAULT_MODEL comment for
  the rationale.
- Cold load: HF cache cold first run pulls ~6 GB of weights; warm-cache
  load is ~1-2 seconds.
- Inference: ~0.31x RTF on M2 Ultra at q8 (measured 2026-05-26 against
  the 47s Yggdrasil prompt with the Mimir reference).

HF models:
  ``mlx-community/higgs-audio-v2-3B-mlx-q4``   - smallest
  ``mlx-community/higgs-audio-v2-3B-mlx-q6``   - speed/size winner
  ``mlx-community/higgs-audio-v2-3B-mlx-q8``   - default (most robust)
  ``mlx-community/higgs-audio-v2-3B-mlx-bf16`` - reference precision
Codec: ``mlx-community/higgs-audio-v2-tokenizer`` (shared across
quantization variants).

Known limitations
=================

- **Natural EOS is unreliable for some voices.** The Llama-backbone
  HiggsAudioModel does not always emit an audio_stream_eos token at
  the end of the target text - especially for distribution-edge
  references (deep timbre, heavy accent, unusual cadence). Practical
  consequence: `max_new_frames` is a hard ceiling that may be reached
  before generation finishes naturally, with trailing silence
  appearing in the output. Trim trailing silence at the consumer
  (most consumers do this anyway).

- **Silence-collapse on some seeds.** With q6 or q4 quantization +
  distribution-edge references, the model can lock into an
  audio-token trajectory that decodes to ~0 amplitude. The
  ``sampling_warmup_frames`` knob (default 8) mitigates this by
  pinning the first N frames to greedy decode. If you see silent
  outputs, raise that or switch to q8/bf16 weights. The bundled
  en_woman voice does not exhibit the issue at any quantization;
  edge-case voices may.

- **No reproducibility seed.** The MLX RNG is process-global, not
  per-call. The transformers ``higgs`` backend's ``seed`` knob does
  not have an equivalent here. If reproducibility matters,
  pre-generate to a cache.
"""

from __future__ import annotations

import logging
import os
import platform
from collections.abc import Iterator

import numpy as np

from . import VoiceRef, register_backend
from ._subprocess import SubprocessBackend

logger = logging.getLogger("voice_forge.backends.higgs_mlx")

# DEFAULT_MODEL chosen as q8 (not q6) after empirical testing on M2 Ultra
# 2026-05-26: q6 collapses to silence with distribution-edge reference
# voices (e.g. Mimir's deep Nordic-tinged English). q8 is more robust on
# the same references with negligible RTF cost (0.31x vs 0.27x on the
# 47s Yggdrasil prompt). The model card's q6 benchmark used the bundled
# en_woman sample which is well inside the training distribution. Set
# `voice_forge.backends.higgs-mlx.model` env override to opt into q6
# for tight memory budgets where the speed bump is worth the
# distribution-edge risk:
#   `mlx-community/higgs-audio-v2-3B-mlx-q4` — 4-bit, smallest
#   `mlx-community/higgs-audio-v2-3B-mlx-q6` — 6-bit, ~4.75 GB
#   `mlx-community/higgs-audio-v2-3B-mlx-q8` — 8-bit, ~6.18 GB (default)
#   `mlx-community/higgs-audio-v2-3B-mlx-bf16` — full bf16, ~6.8 GB
DEFAULT_MODEL = "mlx-community/higgs-audio-v2-3B-mlx-q8"
DEFAULT_CODEC = "mlx-community/higgs-audio-v2-tokenizer"
SAMPLE_RATE = 24_000


def _require_apple_silicon() -> None:
    """Raise RuntimeError unless we're on arm64 macOS.

    Called by both the parent-side ``HiggsMlxBackend.load()`` (so the
    operator sees the failure at backend startup, not when the shim's
    pip install eventually fails) and the child-side
    ``_HiggsMlxInProcess.load()`` (so the failure is consistent
    regardless of which path triggers it).
    """
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        raise RuntimeError(
            "higgs-mlx requires Apple Silicon macOS (arm64 Darwin); "
            f"detected {platform.system()}/{platform.machine()}. "
            "Use the 'higgs' backend on non-Apple-Silicon hosts."
        )


class HiggsMlxBackend(SubprocessBackend):
    """Higgs Audio V2 MLX subprocess backend (parent-side wrapper)."""

    name = "higgs-mlx"

    # Mirrors HiggsAudioServer.generate() kwargs. Names that differ from
    # the transformers backend:
    #   max_new_tokens   -> max_new_frames        (MLX exposes audio FRAMES
    #                                             directly, not codebook
    #                                             tokens. 25 Hz frame rate.)
    #   ras_win_max_num_repeat -> ras_max_repeat
    # ``top_p`` / ``top_k`` / ``temperature`` carry over with the same
    # semantics. ``seed`` is not part of HiggsAudioServer.generate() -
    # MLX RNG seeding happens at the mlx.core level, not per-call.
    KNOWN_TUNABLES = {
        "temperature": {
            "type": "float",
            "min": 0.1,
            "max": 1.5,
            "default": 0.7,
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
            "min": 0,
            "max": 200,
            "default": 0,
            "description": "Top-k filter for token selection. 0 disables top-k.",
        },
        "max_new_frames": {
            "type": "int",
            "min": 64,
            "max": 4096,
            "default": 1200,
            "description": (
                "Max new audio frames. 1 frame = 40 ms at the codec's 25 Hz "
                "frame rate, so 1200 frames = ~48 s of audio."
            ),
        },
        "ras_win_len": {
            "type": "int",
            "min": 0,
            "max": 32,
            "default": 7,
            "description": ("Repetition-Avoidance Sampling window length. 0 disables RAS."),
        },
        "ras_max_repeat": {
            "type": "int",
            "min": 1,
            "max": 8,
            "default": 2,
            "description": "Max RAS repeats inside the window.",
        },
        "sampling_warmup_frames": {
            "type": "int",
            "min": 0,
            "max": 32,
            "default": 8,
            "description": (
                "Use greedy sampling for the first N frames to pin the "
                "low-context ramp-in trajectory. Helps distribution-edge "
                "reference voices (e.g. heavily accented, atypical timbre) "
                "avoid silence-collapse from quantization noise. 0 disables."
            ),
        },
        "fade_in_ms": {
            "type": "float",
            "min": 0.0,
            "max": 100.0,
            "default": 30.0,
            "description": (
                "Linear fade-in over the leading N ms to mask first-frame "
                "transient artefacts on quantized variants."
            ),
        },
        "fade_out_ms": {
            "type": "float",
            "min": 0.0,
            "max": 100.0,
            "default": 15.0,
            "description": "Linear fade-out over the trailing N ms.",
        },
    }

    def load(self, config: dict) -> None:
        # Fail fast on the wrong host before spawning the child shim.
        # The child would die at MLX import time anyway, but raising here
        # gives a clearer error message + skips the venv-spawn round trip.
        _require_apple_silicon()
        super().load(config)


if os.environ.get("VOICE_FORGE_SUBPROCESS_CHILD") == "1":
    # ----- Child-only heavy imports -----
    #
    # The MLX runtime + the higgs_audio fork's transformers pin live in
    # the per-backend venv (~/.voice-forge/backends/higgs-mlx/.venv/) and
    # are never imported by the parent voice-forge process.

    import gc  # noqa: PLC0415
    from concurrent.futures import ThreadPoolExecutor  # noqa: PLC0415

    from mlx_audio.tts.models.higgs_audio import (  # noqa: PLC0415
        HiggsAudioServer,
    )

    class _HiggsMlxInProcess:
        """In-process implementation used inside the child venv.

        Wraps ``HiggsAudioServer`` with the voice-forge backend Protocol.
        The server already composes the model + codec + tokenizer + the
        prompt-assembly pipeline; the work here is parameter routing +
        reference-clip caching + PCM dtype/shape coercion to voice-forge's
        ``float32 in [-1, 1] @ 24 kHz mono`` contract.
        """

        name = "higgs-mlx"
        KNOWN_TUNABLES = HiggsMlxBackend.KNOWN_TUNABLES

        def __init__(self) -> None:
            self._server: HiggsAudioServer | None = None
            self._cached_ref_voice_id: str | None = None
            self._cached_ref_text: str | None = None
            self._config: dict = {}
            # MLX has thread-local GPU stream state: the model's KV-cache
            # objects (and many intermediate mx.array allocations) are
            # bound to whatever thread instantiated them. If load() runs
            # on thread A and synthesize() runs on thread B (which is
            # what happens inside the subprocess shim's FastAPI worker
            # pool), MLX raises ``RuntimeError: There is no Stream(gpu,
            # 1) in current thread`` from the next ``mx.eval`` on the
            # cache state. The robust fix is to pin ALL MLX work to a
            # dedicated single-threaded executor; the FastAPI worker
            # submits jobs to it and blocks for the result. The
            # executor is created in load() so it runs on the same
            # thread for the lifetime of the backend instance.
            self._mlx_executor: ThreadPoolExecutor | None = None

        # ----- lifecycle -----

        def load(self, config: dict) -> None:
            _require_apple_silicon()

            model_path = config.get("model", DEFAULT_MODEL)
            codec_path = config.get("codec", DEFAULT_CODEC)
            tokenizer_path = config.get("tokenizer_path") or None

            logger.info(
                "higgs-mlx child loading model=%s codec=%s tokenizer=%s",
                model_path,
                codec_path,
                tokenizer_path or "(model_dir)",
            )

            # Spin up the dedicated single-threaded MLX executor BEFORE
            # the from_pretrained call so the model + its KV-cache state
            # are born on the executor thread. Every subsequent MLX call
            # routes through ``self._run_on_mlx_thread`` and therefore
            # sees the same thread-local GPU stream context.
            self._mlx_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mlx-higgs")

            def _do_load() -> HiggsAudioServer:
                # HiggsAudioServer.from_pretrained pulls + materialises the
                # quantized weights, the codec, and the HF tokenizer. The
                # quantization block in the model's config.json drives an
                # automatic in-place quantize before weight load - we
                # don't call nn.quantize explicitly here.
                return HiggsAudioServer.from_pretrained(
                    model_path=model_path,
                    codec_path=codec_path,
                    tokenizer_path=tokenizer_path,
                )

            self._server = self._run_on_mlx_thread(_do_load)
            self._config = {
                "model": model_path,
                "codec": codec_path,
                "tokenizer": tokenizer_path or model_path,
            }
            logger.info("higgs-mlx child ready")

        def _run_on_mlx_thread(self, fn):
            """Submit a callable to the dedicated MLX worker and block.

            All MLX-touching code must go through here. Outside the
            executor's thread, MLX raises about missing thread-local
            GPU streams. See the ``_mlx_executor`` docstring on the
            class init.
            """
            if self._mlx_executor is None:
                raise RuntimeError("higgs-mlx executor not initialised")
            return self._mlx_executor.submit(fn).result()

        def unload(self) -> None:
            # Drop server state on the MLX thread so its tensors GC'd in
            # the right thread context, then shut the executor down.
            if self._mlx_executor is not None and self._server is not None:

                def _drop():
                    pass  # server ref is dropped below; this just forces
                    # the executor to run something on its thread.

                try:
                    self._run_on_mlx_thread(_drop)
                except RuntimeError:
                    pass
            self._server = None
            self._cached_ref_voice_id = None
            self._cached_ref_text = None
            if self._mlx_executor is not None:
                self._mlx_executor.shutdown(wait=True)
                self._mlx_executor = None
            gc.collect()
            # MLX doesn't expose an empty_cache; allocations live in the
            # unified memory pool and are released when the Python objects
            # are GC'd. The subprocess-level unload that kills this child
            # is the real reclaim path for the parent.

        def encode_reference(self, _ref_audio_path: str) -> list | None:
            # HiggsAudioServer encodes the reference at synth time (or via
            # its own prepare_reference cache, which we manage in
            # _ensure_reference_cached). Returning None matches the
            # transformers backend's contract.
            return None

        def health(self) -> dict:
            return {
                "name": self.name,
                "loaded": self._server is not None,
                "model": self._config.get("model"),
                "codec": self._config.get("codec"),
                "sample_rate": SAMPLE_RATE,
                "cached_voice_id": self._cached_ref_voice_id,
            }

        # ----- synth -----

        def _resolve_sampling(self, ref: VoiceRef) -> dict:
            """Extract sampling knobs from the VoiceRef metadata + defaults."""
            sampling = ref.metadata.get("sampling") or {}
            ras_win_len_raw = int(sampling.get("ras_win_len", 7))
            top_k_raw = int(sampling.get("top_k", 0))
            return {
                "temperature": float(sampling.get("temperature", 0.7)),
                "top_p": float(sampling.get("top_p", 0.95)),
                "top_k": top_k_raw if top_k_raw > 0 else None,
                "max_new_frames": int(sampling.get("max_new_frames", 1200)),
                "ras_win_len": ras_win_len_raw if ras_win_len_raw > 0 else None,
                "ras_max_repeat": int(sampling.get("ras_max_repeat", 2)),
                "sampling_warmup_frames": int(sampling.get("sampling_warmup_frames", 8)),
                "fade_in_ms": float(sampling.get("fade_in_ms", 30.0)),
                "fade_out_ms": float(sampling.get("fade_out_ms", 15.0)),
            }

        def _ensure_reference_cached(self, ref: VoiceRef) -> bool:
            """Pre-encode the reference clip on the server if it changed.

            HiggsAudioServer.prepare_reference() bakes the codec.encode +
            delay-pattern + prefix-text embedding into a ReferenceContext
            that subsequent generate() calls reuse. This is ~300-500 ms of
            work per synth call avoided, and matters disproportionately for
            short utterances where TTS overhead dominates.

            Cache key is ``(voice_id, ref_text)`` - voice_id alone is not
            sufficient because the same persona row can have its
            reference text edited via the voice lab and we don't want
            stale prefix embeddings. Returns True if we used (or just
            populated) the cache, False if the call must re-encode
            from scratch (e.g. ref_audio_path or ref_text missing).
            """
            if self._server is None:
                raise RuntimeError("higgs-mlx not loaded")
            if not ref.ref_audio_path or not ref.ref_text:
                # Smart-voice (no reference) is technically allowed but is
                # outside voice-forge's clone contract; require a reference
                # so the failure is loud instead of silently producing a
                # different voice.
                raise ValueError("higgs-mlx requires ref_audio_path + ref_text for cloning")
            cache_key = (ref.voice_id or "", ref.ref_text or "")
            current = (self._cached_ref_voice_id or "", self._cached_ref_text or "")
            if cache_key != current:
                logger.info(
                    "higgs-mlx preparing reference for voice_id=%s",
                    ref.voice_id,
                )
                # prepare_reference does codec.encode + delay-pattern +
                # prefix embedding lookup - all of which touch MLX
                # arrays bound to the executor thread's GPU stream.
                # Route via the executor.
                ref_audio_path = ref.ref_audio_path
                ref_text_val = ref.ref_text
                server = self._server
                self._run_on_mlx_thread(
                    lambda: server.prepare_reference(ref_audio_path, ref_text_val)
                )
                self._cached_ref_voice_id = ref.voice_id
                self._cached_ref_text = ref.ref_text
            return True

        def synthesize(self, text: str, ref: VoiceRef) -> np.ndarray:
            """Blocking synth. Returns float32 PCM in [-1, 1] @ 24 kHz."""
            if self._server is None:
                raise RuntimeError("higgs-mlx not loaded")
            self._ensure_reference_cached(ref)
            samp = self._resolve_sampling(ref)
            # When the reference is cached, generate() picks it up from
            # self._server._reference_cache automatically - passing
            # reference_audio_path=None routes to the cached path. We
            # explicitly pass None so the server's _build_prompt dispatch
            # uses the cached ReferenceContext instead of re-encoding.
            server = self._server
            result = self._run_on_mlx_thread(
                lambda: server.generate(
                    target_text=text,
                    reference_audio_path=None,
                    reference_text=None,
                    max_new_frames=samp["max_new_frames"],
                    temperature=samp["temperature"],
                    top_p=samp["top_p"],
                    top_k=samp["top_k"],
                    ras_win_len=samp["ras_win_len"],
                    ras_max_repeat=samp["ras_max_repeat"],
                    sampling_warmup_frames=samp["sampling_warmup_frames"],
                    fade_in_ms=samp["fade_in_ms"],
                    fade_out_ms=samp["fade_out_ms"],
                )
            )
            # HiggsAudioServer returns float32 in [-1, 1] at 24 kHz mono
            # by contract (see HiggsAudioGenerationResult). Defensive
            # coercion in case a future upstream version changes dtype.
            pcm = np.asarray(result.pcm, dtype=np.float32).reshape(-1)
            if result.sampling_rate != SAMPLE_RATE:
                # Should never happen for Higgs v2; raise loudly rather
                # than silently desync the parent's PCM math.
                raise RuntimeError(
                    f"higgs-mlx returned sr={result.sampling_rate}, " f"expected {SAMPLE_RATE}"
                )
            return pcm

        # Chunk size for the post-generation streaming yield path. 640 ms
        # matches the upstream demo's default chunk_ms; small enough that
        # Pipecat / hermes-agent style consumers can pump it through their
        # audio queue without overlong silence stalls, large enough to
        # amortise the per-chunk asyncio yield overhead.
        _STREAM_CHUNK_MS = 640.0

        def synthesize_stream(self, text: str, ref: VoiceRef) -> Iterator[np.ndarray]:
            """Stream PCM chunks.

            Implementation: full-generate-then-chunk. Yields ~640 ms slices
            after the whole utterance is decoded. This is the same shape as
            HiggsAudioServer.generate_stream() upstream.

            Why not generate_stream_overlap_add?
            ------------------------------------

            MLX's GPU stream context is thread-local: ``mx.eval(...)`` only
            works on the thread that the model was loaded on. The
            ``synthesize_stream`` Protocol is consumed by the
            ``voice_forge.subprocess_shim`` FastAPI shim via
            ``StreamingResponse``, which runs the generator on a worker
            thread (``anyio.to_thread.run_sync``). The overlap-add path
            calls ``mx.eval`` inside the generator and crashes with
            ``RuntimeError: There is no Stream(gpu, 1) in current thread.``
            in that worker.

            The fix is to run the entire blocking generation on a single
            thread (the load thread or a queue-pumped worker), then yield
            PCM slices from the already-materialised numpy buffer. We get
            ZERO TTFB benefit from "streaming" in this configuration, but
            the contract is correct: the consumer sees a multi-chunk
            iterator regardless. If voice-forge later moves to a true
            asyncio MLX-aware backend, swap this body for the overlap-add
            path and the consumer doesn't need to change.

            Trade-off accepted 2026-05-26: the M2 Ultra synthesise wall
            time at 0.31x RTF is already well below realtime for
            typical conversational utterances, so the lack of TTFB win
            doesn't block the use case the perf review flagged. The
            higgs (transformers) backend's true-streaming
            implementation is preserved for cases where TTFB matters
            more than throughput.
            """
            pcm = self.synthesize(text, ref)
            samples_per_chunk = int(self._STREAM_CHUNK_MS * SAMPLE_RATE / 1000.0)
            for i in range(0, pcm.size, samples_per_chunk):
                yield pcm[i : i + samples_per_chunk]

    register_backend("higgs-mlx", _HiggsMlxInProcess)
else:
    register_backend("higgs-mlx", HiggsMlxBackend)
