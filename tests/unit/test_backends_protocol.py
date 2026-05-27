"""Tests for the TTSBackend Protocol + VoiceRef dataclass + dispatch helpers."""

import sys

import pytest

from voice_forge.backends import (
    TTSBackend,
    VoiceRef,
    available_backends,
    known_backends,
    register_backend,
)


def test_voice_ref_carries_ref_audio_path():
    ref = VoiceRef(
        voice_id="example", backend="neutts", ref_audio_path="/tmp/ref.wav", ref_text="hi"
    )
    assert ref.voice_id == "example"
    assert ref.backend == "neutts"
    assert ref.ref_audio_path == "/tmp/ref.wav"
    assert ref.ref_text == "hi"
    assert ref.preset_id is None
    assert ref.encoded_codes is None


def test_voice_ref_carries_preset_id():
    ref = VoiceRef(voice_id="kokoro_af_bella", backend="kokoro", preset_id="af_bella")
    assert ref.preset_id == "af_bella"
    assert ref.ref_audio_path is None
    assert ref.ref_text is None


def test_voice_ref_metadata_defaults_to_empty():
    ref = VoiceRef(voice_id="x", backend="y")
    assert ref.metadata == {}


def test_runtime_checkable_protocol_accepts_compliant_class():
    """A plain class with the right methods satisfies the Protocol (no inheritance needed)."""

    class FakeBackend:
        name = "fake"
        KNOWN_TUNABLES: dict = {}

        def load(self, config): ...
        def encode_reference(self, ref):
            return None

        def synthesize(self, text, ref):
            return None

        def synthesize_stream(self, text, ref):
            yield None

        def health(self):
            return {}

        def unload(self) -> None:
            return None

    assert isinstance(FakeBackend(), TTSBackend)


def test_register_and_lookup_backend():
    class DummyBackend:
        name = "dummy_test"
        KNOWN_TUNABLES: dict = {}

        def load(self, config): ...
        def unload(self) -> None:
            return None

        def encode_reference(self, ref):
            return None

        def synthesize(self, text, ref):
            return None

        def synthesize_stream(self, text, ref):
            yield None

        def health(self):
            return {}

    register_backend("dummy_test", DummyBackend)
    from voice_forge.backends import get_backend

    assert get_backend("dummy_test") is DummyBackend
    assert "dummy_test" in available_backends()


# ---- dispatch helpers (_BACKEND_MODULES + load_backend_module) ----


def test_known_backends_lists_built_in():
    """v0.2 ships with neutts + kokoro entries even if their deps aren't installed."""
    known = known_backends()
    assert "neutts" in known
    assert "kokoro" in known


def test_load_backend_module_unknown_name_raises_keyerror():
    from voice_forge.backends import load_backend_module

    with pytest.raises(KeyError, match="unknown backend"):
        load_backend_module("does_not_exist")


def test_load_backend_module_imports_and_registers(monkeypatch):
    """load_backend_module triggers the target module's register_backend() side effect.

    Uses a real on-disk fake module (``tests/_stubs/fake_backend_for_dispatch.py``)
    so importlib actually executes the body — sys.modules pre-injection would
    skip body execution and miss the registration step.
    """
    from voice_forge.backends import _BACKEND_MODULES, get_backend, load_backend_module

    # Ensure the fake module starts unloaded so import-time effects re-run.
    sys.modules.pop("tests._stubs.fake_backend_for_dispatch", None)
    monkeypatch.setitem(
        _BACKEND_MODULES,
        "fake_dispatch",
        "tests._stubs.fake_backend_for_dispatch",
    )

    load_backend_module("fake_dispatch")

    cls = get_backend("fake_dispatch")
    assert cls.__name__ == "FakeDispatchBackend"
    assert "fake_dispatch" in available_backends()
