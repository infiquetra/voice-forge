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
    assert f5_backend._config["nfe_step"] == 16
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
    assert h["nfe_step"] == 16


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
    assert last["nfe_step"] == 16


def test_synthesize_stream_single_sentence_one_chunk(f5_backend):
    """Single-sentence input yields one chunk."""
    chunks = list(f5_backend.synthesize_stream("Hello.", _voice_ref()))
    assert len(chunks) == 1
    assert chunks[0].dtype == np.float32
    assert len(chunks[0]) == 12000  # FakeF5TTS infer = 0.5s × 24000


def test_synthesize_stream_multi_sentence_chunks_yielded(f5_backend):
    """Multi-sentence input with a small chunk-size yields per-chunk audio."""
    ref = _voice_ref()
    ref.metadata["sampling"] = {"stream_chunk_chars": 15}
    long = "First sentence here. Second sentence. Third sentence."
    chunks = list(f5_backend.synthesize_stream(long, ref))
    # Should produce at least 2 chunks at chunk_chars=15
    assert len(chunks) >= 2
    for c in chunks:
        assert c.dtype == np.float32


def test_synthesize_stream_empty_text_yields_nothing(f5_backend):
    """Empty input yields zero chunks (not one empty chunk)."""
    chunks = list(f5_backend.synthesize_stream("", _voice_ref()))
    assert chunks == []


def test_synthesize_stream_default_chunk_size_keeps_short_input_one_call(f5_backend):
    """Without a sampling override, default chunk_chars=1000 packs short text into one chunk."""
    chunks = list(f5_backend.synthesize_stream("Three. Short. Sentences.", _voice_ref()))
    assert len(chunks) == 1
    # And the single call should have used F5's default sampling
    last_call = f5_backend._tts.calls[-1]
    assert last_call["nfe_step"] == 16  # backend default (was 32; flipped 2026-05-26)


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


# ---- per-voice sampling overrides (QUEUED P2 feature) ----


def test_voice_sampling_cfg_strength_threads_through(f5_backend):
    """A per-voice cfg_strength override reaches F5TTS.infer."""
    ref = _voice_ref()
    ref.metadata["sampling"] = {"cfg_strength": 3.0}
    f5_backend.synthesize("text", ref)
    assert f5_backend._tts.calls[-1].get("cfg_strength") == 3.0


def test_voice_sampling_seed_int_coerced(f5_backend):
    ref = _voice_ref()
    ref.metadata["sampling"] = {"seed": 42}
    f5_backend.synthesize("text", ref)
    assert f5_backend._tts.calls[-1].get("seed") == 42
    assert isinstance(f5_backend._tts.calls[-1].get("seed"), int)


def test_voice_sampling_nfe_step_overrides_load_default(f5_backend):
    """Per-voice nfe_step beats the load-time default."""
    # Loaded with default 32; voice overrides to 16
    ref = _voice_ref()
    ref.metadata["sampling"] = {"nfe_step": 16}
    f5_backend.synthesize("text", ref)
    assert f5_backend._tts.calls[-1]["nfe_step"] == 16


def test_voice_sampling_speed_threads_through(f5_backend):
    ref = _voice_ref()
    ref.metadata["sampling"] = {"speed": 1.2}
    f5_backend.synthesize("text", ref)
    assert f5_backend._tts.calls[-1].get("speed") == 1.2


def test_voice_sampling_remove_silence_bool(f5_backend):
    ref = _voice_ref()
    ref.metadata["sampling"] = {"remove_silence": True}
    f5_backend.synthesize("text", ref)
    assert f5_backend._tts.calls[-1].get("remove_silence") is True


def test_voice_sampling_unknown_keys_ignored(f5_backend):
    """Sampling keys F5 doesn't recognize are silently dropped (not forwarded)."""
    ref = _voice_ref()
    ref.metadata["sampling"] = {"max_new_tokens": 8192, "cfg_strength": 2.0}
    # max_new_tokens belongs to Dia, not F5. F5 should accept cfg_strength only.
    f5_backend.synthesize("text", ref)
    last = f5_backend._tts.calls[-1]
    assert last.get("cfg_strength") == 2.0
    assert "max_new_tokens" not in last


def test_voice_sampling_combined_keys(f5_backend):
    """Multiple sampling overrides all thread through together."""
    ref = _voice_ref()
    ref.metadata["sampling"] = {
        "cfg_strength": 2.5,
        "seed": 7,
        "nfe_step": 20,
        "speed": 1.1,
    }
    f5_backend.synthesize("text", ref)
    last = f5_backend._tts.calls[-1]
    assert last["cfg_strength"] == 2.5
    assert last["seed"] == 7
    assert last["nfe_step"] == 20
    assert last["speed"] == 1.1


def test_no_sampling_block_uses_backend_defaults(f5_backend):
    """Voices without metadata['sampling'] get the backend's default nfe_step + no overrides."""
    ref = _voice_ref()
    # No sampling key in metadata
    assert "sampling" not in ref.metadata
    f5_backend.synthesize("text", ref)
    last = f5_backend._tts.calls[-1]
    assert last["nfe_step"] == 16  # backend default (flipped 2026-05-26)
    # Optional sampling keys not present in the call
    assert "cfg_strength" not in last
    assert "seed" not in last
