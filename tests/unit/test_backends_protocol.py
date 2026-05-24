"""Tests for the TTSBackend Protocol + VoiceRef dataclass."""

from voice_forge.backends import TTSBackend, VoiceRef, available_backends, register_backend


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

        def load(self, config): ...
        def encode_reference(self, ref):
            return None

        def synthesize(self, text, ref):
            return None

        def synthesize_stream(self, text, ref):
            yield None

        def health(self):
            return {}

    assert isinstance(FakeBackend(), TTSBackend)


def test_register_and_lookup_backend():
    class DummyBackend:
        name = "dummy_test"

        def load(self, config): ...
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
