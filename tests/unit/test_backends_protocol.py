"""Tests for the TTSBackend Protocol + VoiceRef dataclass.

Phase D fills out actual assertions. This file demonstrates the test shape.
"""

import pytest

from voice_forge.backends import TTSBackend, VoiceRef, available_backends


def test_voice_ref_can_carry_ref_audio_path():
    ref = VoiceRef(voice_id="example", backend="neutts", ref_audio_path="/tmp/ref.wav", ref_text="hi")
    assert ref.voice_id == "example"
    assert ref.backend == "neutts"


def test_voice_ref_can_carry_preset_id():
    ref = VoiceRef(voice_id="kokoro_af_bella", backend="kokoro", preset_id="af_bella")
    assert ref.preset_id == "af_bella"
    assert ref.ref_audio_path is None


def test_registry_starts_empty():
    # Phase D backends will self-register on import; for now it's empty.
    backends = available_backends()
    assert isinstance(backends, list)


# TODO Phase D: add tests for actual backend implementations (NeuTTS first)
