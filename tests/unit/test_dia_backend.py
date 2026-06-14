"""Body tests for DiaBackend using monkey-patched transformers Dia classes.

Dia is a cloning backend with one key difference from NeuTTS / F5 / XTTS:
the prompt format requires the reference transcript prepended to the
generation text in a specific `[S1] {ref} [S1] {gen}` shape. These tests
lock that in.
"""

from __future__ import annotations

import numpy as np
import pytest

# The fake dia lib + the Dia backend import torch; CI installs no backend extras,
# so skip the whole module when torch is absent rather than erroring at collection.
pytest.importorskip("torch")

from tests._stubs.fake_dialib import install as install_fake_dia  # noqa: E402


@pytest.fixture
def dia_backend(monkeypatch, tmp_path):
    install_fake_dia(monkeypatch)
    from voice_forge.backends.dia import DiaBackend

    backend = DiaBackend()
    backend.load({"device": "cpu"})  # explicit CPU to avoid hitting real torch MPS detect
    return backend


@pytest.fixture
def tiny_ref_wav(tmp_path):
    """Create a tiny valid WAV at 24 kHz (will be resampled to Dia's 44.1)."""
    import wave

    wav_path = tmp_path / "ref.wav"
    with wave.open(str(wav_path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(24000)
        f.writeframes(b"\x00" * (24000 * 2))  # 1s of silence
    return wav_path


def _voice_ref(tiny_ref_wav, **overrides):
    from voice_forge.backends import VoiceRef

    defaults = dict(
        voice_id="dia-test",
        backend="dia",
        ref_audio_path=str(tiny_ref_wav),
        ref_text="This is the reference transcript.",
        metadata={"language": "en"},
    )
    defaults.update(overrides)
    return VoiceRef(**defaults)


def test_load_sets_model_and_device(dia_backend):
    assert dia_backend._model is not None
    assert dia_backend._processor is not None
    assert dia_backend._device == "cpu"
    assert dia_backend._config["model"] == "nari-labs/Dia-1.6B-0626"


def test_load_default_sampling_params(dia_backend):
    """Upstream Dia README's default sampling params should be threaded through."""
    assert dia_backend._config["max_new_tokens"] == 3072
    assert dia_backend._config["guidance_scale"] == 3.0
    assert dia_backend._config["temperature"] == 1.8
    assert dia_backend._config["top_p"] == 0.90
    assert dia_backend._config["top_k"] == 45


def test_load_respects_explicit_sampling_overrides(monkeypatch):
    install_fake_dia(monkeypatch)
    from voice_forge.backends.dia import DiaBackend

    backend = DiaBackend()
    backend.load(
        {
            "device": "cpu",
            "max_new_tokens": 1024,
            "guidance_scale": 2.0,
            "temperature": 1.0,
            "top_p": 0.95,
            "top_k": 50,
        }
    )
    assert backend._config["max_new_tokens"] == 1024
    assert backend._config["guidance_scale"] == 2.0
    assert backend._config["temperature"] == 1.0


def test_encode_reference_returns_none(dia_backend):
    assert dia_backend.encode_reference("/anything.wav") is None


def test_health_shape(dia_backend):
    h = dia_backend.health()
    assert h["name"] == "dia"
    assert h["loaded"] is True
    assert h["model"] == "nari-labs/Dia-1.6B-0626"
    assert h["device"] == "cpu"
    assert h["max_new_tokens"] == 3072


def test_synthesize_returns_float32_24khz(dia_backend, tiny_ref_wav):
    """Even though Dia outputs 44.1 kHz, the backend resamples to voice-forge's 24 kHz."""
    audio = dia_backend.synthesize("Hello.", _voice_ref(tiny_ref_wav))
    assert isinstance(audio, np.ndarray)
    assert audio.dtype == np.float32
    # FakeDiaProcessor.batch_decode returns 0.5s at 44.1 kHz = 22050 samples.
    # Resampled to 24 kHz: ~12000 samples. Allow a small tolerance for resampler.
    assert 11000 <= len(audio) <= 13000


def test_synthesize_builds_correct_dia_prompt(dia_backend, tiny_ref_wav):
    """The text passed to the processor must be `[S1] {ref_text} [S1] {gen_text}`."""
    ref = _voice_ref(tiny_ref_wav, ref_text="Reference says hello.")
    dia_backend.synthesize("Now say something else.", ref)
    last_text = dia_backend._processor.last_call_text
    assert last_text == ["[S1] Reference says hello. [S1] Now say something else."]


def test_synthesize_passes_resampled_audio_to_processor(dia_backend, tiny_ref_wav):
    """The ref WAV at 24 kHz must be resampled to Dia's 44.1 kHz before processing."""
    dia_backend.synthesize("text", _voice_ref(tiny_ref_wav))
    audio_arg = dia_backend._processor.last_call_audio
    # FakeDiaProcessor records audio= as a list with one np.ndarray.
    assert isinstance(audio_arg, list)
    assert len(audio_arg) == 1
    # 1s of 24 kHz resampled to 44.1 kHz ≈ 44100 samples (allow rounding).
    assert 43000 <= len(audio_arg[0]) <= 45000


def test_synthesize_stream_single_sentence_one_chunk(dia_backend, tiny_ref_wav):
    chunks = list(dia_backend.synthesize_stream("Hello.", _voice_ref(tiny_ref_wav)))
    assert len(chunks) == 1
    assert chunks[0].dtype == np.float32


def test_synthesize_stream_multi_sentence_yields_per_chunk(dia_backend, tiny_ref_wav):
    ref = _voice_ref(tiny_ref_wav)
    ref.metadata["sampling"] = {"stream_chunk_chars": 15}
    long = "First sentence here. Second sentence. Third one here."
    chunks = list(dia_backend.synthesize_stream(long, ref))
    assert len(chunks) >= 2
    for c in chunks:
        assert c.dtype == np.float32


def test_synthesize_stream_empty_text_yields_nothing(dia_backend, tiny_ref_wav):
    chunks = list(dia_backend.synthesize_stream("", _voice_ref(tiny_ref_wav)))
    assert chunks == []


def test_missing_ref_audio_raises(dia_backend, tiny_ref_wav):
    bad = _voice_ref(tiny_ref_wav, ref_audio_path=None)
    with pytest.raises(ValueError, match="requires ref_audio_path"):
        dia_backend.synthesize("text", bad)


def test_missing_ref_text_raises(dia_backend, tiny_ref_wav):
    bad = _voice_ref(tiny_ref_wav, ref_text=None)
    with pytest.raises(ValueError, match="requires ref_text"):
        dia_backend.synthesize("text", bad)


def test_synthesize_without_load_raises(monkeypatch, tiny_ref_wav):
    install_fake_dia(monkeypatch)
    from voice_forge.backends.dia import DiaBackend

    backend = DiaBackend()  # no .load() call
    with pytest.raises(RuntimeError, match="not loaded"):
        backend.synthesize("text", _voice_ref(tiny_ref_wav))


def test_sampling_params_thread_to_generate(dia_backend, tiny_ref_wav):
    """Custom sampling params threaded through load() should reach model.generate()."""
    dia_backend._config["temperature"] = 0.5  # override post-load for test brevity
    dia_backend._config["top_k"] = 10
    dia_backend.synthesize("text", _voice_ref(tiny_ref_wav))
    kw = dia_backend._model.last_generate_kwargs
    assert kw["temperature"] == 0.5
    assert kw["top_k"] == 10
    assert kw["max_new_tokens"] == 3072  # unchanged default


# ---- per-voice sampling overrides (QUEUED P2 feature) ----


def test_voice_sampling_max_new_tokens_overrides_default(dia_backend, tiny_ref_wav):
    """Per-voice max_new_tokens fixes the documented Dia long-form truncation."""
    ref = _voice_ref(tiny_ref_wav)
    ref.metadata["sampling"] = {"max_new_tokens": 8192}
    dia_backend.synthesize("long story text", ref)
    kw = dia_backend._model.last_generate_kwargs
    assert kw["max_new_tokens"] == 8192


def test_voice_sampling_temperature_overrides_default(dia_backend, tiny_ref_wav):
    ref = _voice_ref(tiny_ref_wav)
    ref.metadata["sampling"] = {"temperature": 0.7}
    dia_backend.synthesize("text", ref)
    kw = dia_backend._model.last_generate_kwargs
    assert kw["temperature"] == 0.7


def test_voice_sampling_combined_dia_overrides(dia_backend, tiny_ref_wav):
    ref = _voice_ref(tiny_ref_wav)
    ref.metadata["sampling"] = {
        "max_new_tokens": 4096,
        "guidance_scale": 4.0,
        "temperature": 1.5,
        "top_p": 0.85,
        "top_k": 30,
    }
    dia_backend.synthesize("text", ref)
    kw = dia_backend._model.last_generate_kwargs
    assert kw["max_new_tokens"] == 4096
    assert kw["guidance_scale"] == 4.0
    assert kw["temperature"] == 1.5
    assert kw["top_p"] == 0.85
    assert kw["top_k"] == 30


def test_voice_sampling_partial_overrides_use_defaults_for_rest(dia_backend, tiny_ref_wav):
    """A voice that only overrides max_new_tokens keeps backend defaults for the rest."""
    ref = _voice_ref(tiny_ref_wav)
    ref.metadata["sampling"] = {"max_new_tokens": 8192}
    dia_backend.synthesize("text", ref)
    kw = dia_backend._model.last_generate_kwargs
    assert kw["max_new_tokens"] == 8192
    # Other keys use backend defaults from DiaBackend.load()
    assert kw["guidance_scale"] == 3.0
    assert kw["temperature"] == 1.8
    assert kw["top_p"] == 0.90
    assert kw["top_k"] == 45


def test_no_sampling_block_uses_dia_defaults(dia_backend, tiny_ref_wav):
    """Voices without metadata['sampling'] get all backend defaults."""
    ref = _voice_ref(tiny_ref_wav)
    assert "sampling" not in ref.metadata
    dia_backend.synthesize("text", ref)
    kw = dia_backend._model.last_generate_kwargs
    assert kw["max_new_tokens"] == 3072
    assert kw["guidance_scale"] == 3.0
    assert kw["temperature"] == 1.8
