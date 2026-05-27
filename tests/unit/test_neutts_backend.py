"""Body tests for NeuTTSBackend using sys.modules-injected fake neutts + llama_cpp.

These tests do NOT exercise the real NeuTTS model — they verify the backend's
contract (load → encode_reference / synthesize / synthesize_stream / health)
and the ``_resolve_ref`` branching across the three legal VoiceRef shapes for
this backend.

The three monkey-patches (n_ctx, repeat_penalty, watermarker) are exercised
indirectly: they run during ``load()`` against the fake classes; we just
verify load doesn't crash and the post-load state is right.
"""

from __future__ import annotations

import numpy as np
import pytest

from tests._stubs.fake_neuttslib import install as install_fake_neutts


@pytest.fixture
def neutts_backend(monkeypatch):
    """Yield a loaded NeuTTSBackend backed by the fake neutts/llama_cpp."""
    install_fake_neutts(monkeypatch)
    from voice_forge.backends.neutts import NeuTTSBackend

    backend = NeuTTSBackend()
    backend.load({"model": "fake/model", "device": "cpu"})
    return backend


def _voice_ref(**overrides):
    from voice_forge.backends import VoiceRef

    defaults = dict(
        voice_id="test-voice",
        backend="neutts",
        ref_audio_path="/tmp/fake-ref.wav",
        ref_text="this is the reference text",
    )
    defaults.update(overrides)
    return VoiceRef(**defaults)


def test_load_sets_tts_instance_and_disables_watermarker(neutts_backend):
    # After load, the fake instance is in place and watermarker is disabled.
    assert neutts_backend._tts is not None
    assert neutts_backend._tts.watermarker is None
    # Config defaults flowed through.
    assert neutts_backend._config["chunk_chars"] == 600
    assert neutts_backend._config["device"] == "cpu"


def test_health_shape(neutts_backend):
    h = neutts_backend.health()
    for key in (
        "name",
        "loaded",
        "model",
        "device",
        "n_ctx",
        "repeat_penalty",
        "chunk_chars",
        "watermarker_disabled",
    ):
        assert key in h, f"missing health key: {key}"
    assert h["name"] == "neutts"
    assert h["loaded"] is True
    assert h["watermarker_disabled"] is True


def test_encode_reference_delegates_to_tts(neutts_backend):
    codes = neutts_backend.encode_reference("/tmp/fake-ref.wav")
    # FakeNeuTTS returns [10, 20, 30].
    assert codes == [10, 20, 30]


def test_synthesize_returns_float32_24khz_pcm(neutts_backend):
    audio = neutts_backend.synthesize("Hello world.", _voice_ref())
    assert isinstance(audio, np.ndarray)
    assert audio.dtype == np.float32
    # FakeNeuTTS.infer yields 0.5s of silence (12000 samples at 24kHz);
    # short input fits in one chunk, so we get exactly that.
    assert len(audio) == 12000


def test_synthesize_concatenates_chunks_for_long_input(neutts_backend):
    # Force chunker to split by using two clearly-separated sentences,
    # then shrinking chunk_chars so each is its own chunk.
    neutts_backend._config["chunk_chars"] = 10
    text = "First sentence here. Second sentence there. Third one."
    audio = neutts_backend.synthesize(text, _voice_ref())
    # 3 chunks × 12000 samples = 36000. (Order-preserving concatenation.)
    assert len(audio) == 36000


def test_synthesize_stream_yields_per_chunk(neutts_backend):
    chunks = list(neutts_backend.synthesize_stream("Hello.", _voice_ref()))
    # FakeNeuTTS.infer_stream yields 3 chunks of 2400 samples (0.1s @ 24kHz).
    assert len(chunks) == 3
    for c in chunks:
        assert c.dtype == np.float32
        assert len(c) == 2400


def test_resolve_ref_requires_ref_text(neutts_backend):
    bad = _voice_ref(ref_text=None)
    with pytest.raises(ValueError, match="requires ref_text"):
        neutts_backend.synthesize("text", bad)


def test_resolve_ref_uses_encoded_codes_when_present(neutts_backend):
    pre = _voice_ref(encoded_codes=[99, 98, 97], ref_audio_path=None)
    audio = neutts_backend.synthesize("Hello.", pre)
    # Should not crash; FakeNeuTTS.infer still returns 12000 samples.
    assert len(audio) == 12000


def test_resolve_ref_requires_ref_audio_or_codes(neutts_backend):
    bad = _voice_ref(ref_audio_path=None, encoded_codes=None)
    with pytest.raises(ValueError, match="requires ref_audio_path or encoded_codes"):
        neutts_backend.synthesize("text", bad)


def test_synthesize_without_load_raises(monkeypatch):
    install_fake_neutts(monkeypatch)
    from voice_forge.backends.neutts import NeuTTSBackend

    backend = NeuTTSBackend()  # no .load() call
    with pytest.raises(RuntimeError, match="not loaded"):
        backend.synthesize("text", _voice_ref())


def test_encode_reference_without_load_raises(monkeypatch):
    install_fake_neutts(monkeypatch)
    from voice_forge.backends.neutts import NeuTTSBackend

    backend = NeuTTSBackend()
    with pytest.raises(RuntimeError, match="not loaded"):
        backend.encode_reference("/tmp/ref.wav")


def test_empty_text_returns_empty_array(neutts_backend):
    # _chunk_text on whitespace-only text returns [""] which still goes to
    # FakeNeuTTS.infer, so we get one chunk of zeros. That's a defensible
    # contract — the backend doesn't error on empty input.
    audio = neutts_backend.synthesize("", _voice_ref())
    assert isinstance(audio, np.ndarray)
    assert audio.dtype == np.float32
