"""Body tests for F5Backend using sys.modules-injected fake f5_tts.

F5 is a cloning backend (ref_audio_path + ref_text arms of VoiceRef), so
these tests cover the same shape as test_neutts_backend.py: load,
synthesize, synthesize_stream, health, and the missing-ref guard rails.
"""

from __future__ import annotations

import numpy as np
import pytest

from tests._stubs.fake_f5lib import install as install_fake_f5


@pytest.fixture
def f5_backend(monkeypatch):
    install_fake_f5(monkeypatch)
    from voice_forge.backends.f5 import F5Backend

    backend = F5Backend()
    backend.load({})
    return backend


def _voice_ref(**overrides):
    from voice_forge.backends import VoiceRef

    defaults = dict(
        voice_id="test-voice",
        backend="f5",
        ref_audio_path="/tmp/fake-ref.wav",
        ref_text="this is the reference text",
    )
    defaults.update(overrides)
    return VoiceRef(**defaults)


def test_load_sets_tts_with_defaults(f5_backend):
    assert f5_backend._tts is not None
    assert f5_backend._config["model"] == "F5TTS_v1_Base"
    assert f5_backend._config["nfe_step"] == 32
    assert f5_backend._config["device"] is None  # autodetect


def test_load_respects_explicit_device_and_nfe(monkeypatch):
    install_fake_f5(monkeypatch)
    from voice_forge.backends.f5 import F5Backend

    backend = F5Backend()
    backend.load({"device": "mps", "nfe_step": 16})
    assert backend._config["device"] == "mps"
    assert backend._config["nfe_step"] == 16
    assert backend.health()["device"] == "mps"
    assert backend.health()["nfe_step"] == 16


def test_health_shape(f5_backend):
    h = f5_backend.health()
    assert h["name"] == "f5"
    assert h["loaded"] is True
    assert h["model"] == "F5TTS_v1_Base"
    assert h["device"] == "auto"
    assert h["nfe_step"] == 32


def test_encode_reference_returns_none(f5_backend):
    """F5 has no public pre-encode API; encode_reference returns None per Protocol."""
    assert f5_backend.encode_reference("/anything.wav") is None


def test_synthesize_returns_float32_at_24khz(f5_backend):
    audio = f5_backend.synthesize("Hello world.", _voice_ref())
    assert isinstance(audio, np.ndarray)
    assert audio.dtype == np.float32
    # FakeF5TTS.infer returns 0.5s × 24000 = 12000 samples.
    assert len(audio) == 12000


def test_synthesize_passes_ref_audio_and_text_to_f5(f5_backend):
    f5_backend.synthesize(
        "Synthesize me.", _voice_ref(ref_audio_path="/the/ref.wav", ref_text="ref text")
    )
    last = f5_backend._tts.calls[-1]
    assert last["ref_file"] == "/the/ref.wav"
    assert last["ref_text"] == "ref text"
    assert last["gen_text"] == "Synthesize me."
    assert last["nfe_step"] == 32


def test_synthesize_stream_degrades_to_single_chunk(f5_backend):
    """F5 has no native streaming; synthesize_stream yields the full batch as one chunk."""
    chunks = list(f5_backend.synthesize_stream("Hello.", _voice_ref()))
    assert len(chunks) == 1
    assert chunks[0].dtype == np.float32
    assert len(chunks[0]) == 12000


def test_missing_ref_audio_raises(f5_backend):
    bad = _voice_ref(ref_audio_path=None)
    with pytest.raises(ValueError, match="requires ref_audio_path"):
        f5_backend.synthesize("text", bad)


def test_missing_ref_text_raises(f5_backend):
    bad = _voice_ref(ref_text=None)
    with pytest.raises(ValueError, match="requires ref_text"):
        f5_backend.synthesize("text", bad)


def test_synthesize_without_load_raises(monkeypatch):
    install_fake_f5(monkeypatch)
    from voice_forge.backends.f5 import F5Backend

    backend = F5Backend()  # no .load() call
    with pytest.raises(RuntimeError, match="not loaded"):
        backend.synthesize("text", _voice_ref())


def test_nfe_step_threads_through_to_infer(monkeypatch):
    """A custom nfe_step at load time is forwarded to each F5TTS.infer call."""
    install_fake_f5(monkeypatch)
    from voice_forge.backends.f5 import F5Backend

    backend = F5Backend()
    backend.load({"nfe_step": 16})
    backend.synthesize("text", _voice_ref())
    assert backend._tts.calls[-1]["nfe_step"] == 16
