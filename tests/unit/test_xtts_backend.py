"""Body tests for XTTSBackend using sys.modules-injected fake TTS.api.

XTTS is a cloning backend (ref_audio_path arm of VoiceRef; ref_text NOT
required — XTTS does its own encoding) so coverage mirrors the F5 tests
with one twist: language code is required and threads through from
VoiceRef.metadata.
"""

from __future__ import annotations

import numpy as np
import pytest

from tests._stubs.fake_xttslib import install as install_fake_xtts


@pytest.fixture
def xtts_backend(monkeypatch):
    install_fake_xtts(monkeypatch)
    # XTTS-v2 weights are CPML-licensed; load() requires explicit env consent.
    monkeypatch.setenv("COQUI_TOS_AGREED", "1")
    from voice_forge.backends.xtts import XTTSBackend

    backend = XTTSBackend()
    backend.load({})
    return backend


def _voice_ref(**overrides):
    from voice_forge.backends import VoiceRef

    defaults = dict(
        voice_id="test-voice",
        backend="xtts",
        ref_audio_path="/tmp/fake-ref.wav",
        ref_text="this is the reference text (ignored by xtts)",
        metadata={"language": "en"},
    )
    defaults.update(overrides)
    return VoiceRef(**defaults)


def test_load_sets_tts_with_default_model(xtts_backend):
    assert xtts_backend._tts is not None
    assert xtts_backend._config["model"] == "tts_models/multilingual/multi-dataset/xtts_v2"
    assert xtts_backend._config["device"] is None  # CPU default


def test_load_respects_explicit_device(monkeypatch):
    install_fake_xtts(monkeypatch)
    monkeypatch.setenv("COQUI_TOS_AGREED", "1")
    from voice_forge.backends.xtts import XTTSBackend

    backend = XTTSBackend()
    backend.load({"device": "mps"})
    assert backend._config["device"] == "mps"
    assert backend._tts.device == "mps"  # FakeTTS.to() records the device
    assert backend.health()["device"] == "mps"


def test_load_without_coqui_tos_agreed_raises_with_cpml_explanation(monkeypatch):
    """Loading XTTS without COQUI_TOS_AGREED=1 must refuse with a clear license message."""
    install_fake_xtts(monkeypatch)
    monkeypatch.delenv("COQUI_TOS_AGREED", raising=False)
    from voice_forge.backends.xtts import XTTSBackend

    backend = XTTSBackend()
    with pytest.raises(RuntimeError, match="CPML") as exc:
        backend.load({})
    # The error should point users at the right URL and the commercial-licensing path.
    msg = str(exc.value)
    assert "coqui.ai/cpml" in msg or "CPML" in msg
    assert "COQUI_TOS_AGREED" in msg
    assert "licensing@coqui.ai" in msg or "commercial" in msg.lower()


def test_load_with_wrong_coqui_tos_value_still_raises(monkeypatch):
    """Anything other than exactly '1' shouldn't count as consent."""
    install_fake_xtts(monkeypatch)
    monkeypatch.setenv("COQUI_TOS_AGREED", "yes")  # not '1'
    from voice_forge.backends.xtts import XTTSBackend

    backend = XTTSBackend()
    with pytest.raises(RuntimeError, match="CPML"):
        backend.load({})


def test_health_shape(xtts_backend):
    h = xtts_backend.health()
    assert h["name"] == "xtts"
    assert h["loaded"] is True
    assert h["model"] == "tts_models/multilingual/multi-dataset/xtts_v2"
    assert h["device"] == "cpu"
    assert h["default_language"] == "en"


def test_encode_reference_returns_none(xtts_backend):
    """XTTS has no public pre-encode API; encode_reference returns None per Protocol."""
    assert xtts_backend.encode_reference("/anything.wav") is None


def test_synthesize_returns_float32_at_24khz(xtts_backend):
    audio = xtts_backend.synthesize("Hello world.", _voice_ref())
    assert isinstance(audio, np.ndarray)
    assert audio.dtype == np.float32
    # FakeTTS.tts returns 0.5s × 24000 = 12000 samples.
    assert len(audio) == 12000


def test_synthesize_passes_speaker_wav_and_language(xtts_backend):
    ref = _voice_ref(ref_audio_path="/the/ref.wav", metadata={"language": "es"})
    xtts_backend.synthesize("Synthesize me.", ref)
    last = xtts_backend._tts.calls[-1]
    assert last["text"] == "Synthesize me."
    assert last["speaker_wav"] == "/the/ref.wav"
    assert last["language"] == "es"


def test_synthesize_defaults_to_english_when_metadata_missing(xtts_backend):
    """Voices without metadata['language'] default to 'en' rather than crash."""
    ref = _voice_ref(metadata={})  # no language
    xtts_backend.synthesize("text", ref)
    assert xtts_backend._tts.calls[-1]["language"] == "en"


def test_synthesize_ignores_ref_text(xtts_backend):
    """Unlike NeuTTS/F5, XTTS doesn't use ref_text — synth works even with None."""
    ref = _voice_ref(ref_text=None)
    audio = xtts_backend.synthesize("text", ref)
    assert isinstance(audio, np.ndarray)


def test_synthesize_stream_single_sentence_one_chunk(xtts_backend):
    chunks = list(xtts_backend.synthesize_stream("Hello.", _voice_ref()))
    assert len(chunks) == 1
    assert chunks[0].dtype == np.float32
    assert len(chunks[0]) == 12000


def test_synthesize_stream_multi_sentence_yields_per_chunk(xtts_backend):
    ref = _voice_ref()
    ref.metadata["sampling"] = {"stream_chunk_chars": 15}
    long = "First sentence here. Second sentence. Third sentence here."
    chunks = list(xtts_backend.synthesize_stream(long, ref))
    assert len(chunks) >= 2
    for c in chunks:
        assert c.dtype == np.float32


def test_synthesize_stream_empty_text_yields_nothing(xtts_backend):
    chunks = list(xtts_backend.synthesize_stream("", _voice_ref()))
    assert chunks == []


def test_missing_ref_audio_raises(xtts_backend):
    bad = _voice_ref(ref_audio_path=None)
    with pytest.raises(ValueError, match="requires ref_audio_path"):
        xtts_backend.synthesize("text", bad)


def test_synthesize_without_load_raises(monkeypatch):
    install_fake_xtts(monkeypatch)
    monkeypatch.setenv("COQUI_TOS_AGREED", "1")
    from voice_forge.backends.xtts import XTTSBackend

    backend = XTTSBackend()  # no .load() call
    with pytest.raises(RuntimeError, match="not loaded"):
        backend.synthesize("text", _voice_ref())


# ---- per-voice sampling overrides (QUEUED P2 feature) ----


def test_voice_sampling_speed_threads_through(xtts_backend):
    ref = _voice_ref()
    ref.metadata["sampling"] = {"speed": 1.2}
    xtts_backend.synthesize("text", ref)
    last = xtts_backend._tts.calls[-1]
    assert last["speed"] == 1.2


def test_voice_sampling_temperature_and_top_k(xtts_backend):
    ref = _voice_ref()
    ref.metadata["sampling"] = {"temperature": 0.7, "top_k": 30}
    xtts_backend.synthesize("text", ref)
    last = xtts_backend._tts.calls[-1]
    assert last["temperature"] == 0.7
    assert last["top_k"] == 30
    assert isinstance(last["top_k"], int)


def test_voice_sampling_repetition_and_length_penalty(xtts_backend):
    """XTTS-specific tunables — repetition_penalty + length_penalty."""
    ref = _voice_ref()
    ref.metadata["sampling"] = {"repetition_penalty": 2.0, "length_penalty": 0.8}
    xtts_backend.synthesize("text", ref)
    last = xtts_backend._tts.calls[-1]
    assert last["repetition_penalty"] == 2.0
    assert last["length_penalty"] == 0.8


def test_no_sampling_block_uses_xtts_defaults(xtts_backend):
    """No sampling = no per-call kwargs forwarded; XTTS uses its built-in defaults."""
    ref = _voice_ref()
    assert "sampling" not in ref.metadata
    xtts_backend.synthesize("text", ref)
    last = xtts_backend._tts.calls[-1]
    # The optional sampling keys should NOT be in the call record (would have
    # been recorded by the fake if forwarded).
    assert "speed" not in last
    assert "temperature" not in last
    assert "top_k" not in last
