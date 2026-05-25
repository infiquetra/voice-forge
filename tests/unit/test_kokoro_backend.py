"""Body tests for KokoroBackend using sys.modules-injected fake kokoro.

These tests verify the backend contract without depending on the real
``kokoro`` package (or its transitive ``torch`` / ``transformers`` chain).
The voice-mixing parser has its own dedicated tests; here we only verify
the backend wires the parsed result through to ``KPipeline(voice=...)``.
"""

from __future__ import annotations

import logging

import numpy as np
import pytest

from tests._stubs.fake_kokorolib import install as install_fake_kokoro


@pytest.fixture
def kokoro_backend(monkeypatch):
    install_fake_kokoro(monkeypatch)
    from voice_forge.backends.kokoro import KokoroBackend

    backend = KokoroBackend()
    backend.load({})
    return backend


def _voice_ref(**overrides):
    from voice_forge.backends import VoiceRef

    defaults = dict(voice_id="kokoro-bella", backend="kokoro", preset_id="af_bella")
    defaults.update(overrides)
    return VoiceRef(**defaults)


def test_load_constructs_pipeline_with_default_lang_code(kokoro_backend):
    assert kokoro_backend._pipeline is not None
    assert kokoro_backend._pipeline.lang_code == "a"
    assert kokoro_backend._config["lang_code"] == "a"


def test_load_respects_explicit_lang_code(monkeypatch):
    install_fake_kokoro(monkeypatch)
    from voice_forge.backends.kokoro import KokoroBackend

    backend = KokoroBackend()
    backend.load({"lang_code": "b"})  # British English
    assert backend._pipeline.lang_code == "b"
    assert backend.health()["lang_code"] == "b"


def test_load_fails_without_espeak_ng(monkeypatch):
    install_fake_kokoro(monkeypatch, with_espeak_ng=False)
    # Force which() to report espeak-ng missing.
    import shutil

    monkeypatch.setattr(shutil, "which", lambda name, *a, **k: None)
    from voice_forge.backends.kokoro import KokoroBackend

    backend = KokoroBackend()
    with pytest.raises(RuntimeError, match="espeak-ng"):
        backend.load({})


def test_encode_reference_returns_none(kokoro_backend):
    assert kokoro_backend.encode_reference("/anything.wav") is None


def test_health_shape(kokoro_backend):
    h = kokoro_backend.health()
    assert h["name"] == "kokoro"
    assert h["loaded"] is True
    assert h["lang_code"] == "a"
    assert h["model"] == "kokoro-82M"


def test_synthesize_returns_concatenated_float32(kokoro_backend):
    audio = kokoro_backend.synthesize("Hello.", _voice_ref())
    assert isinstance(audio, np.ndarray)
    assert audio.dtype == np.float32
    # FakeKPipeline yields 2 × 0.25s @ 24kHz = 12000 samples.
    assert len(audio) == 12000


def test_synthesize_passes_bare_voice_name_to_pipeline(kokoro_backend):
    kokoro_backend.synthesize("text", _voice_ref(preset_id="af_bella"))
    last_call = kokoro_backend._pipeline.call_log[-1]
    assert last_call["voice"] == "af_bella"


def test_synthesize_stream_yields_per_chunk(kokoro_backend):
    chunks = list(kokoro_backend.synthesize_stream("text", _voice_ref()))
    # FakeKPipeline yields 2 chunks of 6000 samples (0.25s @ 24kHz).
    assert len(chunks) == 2
    for c in chunks:
        assert c.dtype == np.float32
        assert len(c) == 6000


def test_missing_preset_raises(kokoro_backend):
    bad = _voice_ref(preset_id=None)
    with pytest.raises(ValueError, match="requires preset_id"):
        kokoro_backend.synthesize("text", bad)


def test_voice_mix_degrades_to_highest_weight_voice(kokoro_backend, caplog):
    """Multi-voice mix in v0.2 picks the highest-weight voice (tensor blend deferred)."""
    caplog.set_level(logging.WARNING, logger="voice_forge.backends.kokoro")
    kokoro_backend.synthesize("text", _voice_ref(preset_id="af_sky+af_bella(3)"))
    last_call = kokoro_backend._pipeline.call_log[-1]
    assert last_call["voice"] == "af_bella"  # weight 3 > 1
    assert any("voice-mix degradation" in r.message for r in caplog.records)


def test_resolve_voice_without_load_raises(monkeypatch):
    install_fake_kokoro(monkeypatch)
    from voice_forge.backends.kokoro import KokoroBackend

    backend = KokoroBackend()  # not loaded
    with pytest.raises(RuntimeError, match="not loaded"):
        backend.synthesize("text", _voice_ref())


def test_empty_text_returns_empty_array(monkeypatch):
    """If the pipeline yields nothing, synthesize returns an empty float32 array."""
    install_fake_kokoro(monkeypatch)
    from voice_forge.backends.kokoro import KokoroBackend

    # Override the fake pipeline to yield zero chunks.
    backend = KokoroBackend()
    backend.load({})

    def empty_gen(*args, **kwargs):
        return iter([])

    backend._pipeline = type(
        "EmptyPipeline", (), {"__call__": staticmethod(empty_gen), "lang_code": "a"}
    )()
    audio = backend.synthesize("anything", _voice_ref())
    assert isinstance(audio, np.ndarray)
    assert audio.dtype == np.float32
    assert len(audio) == 0
