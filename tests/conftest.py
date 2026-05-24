"""Shared pytest fixtures for voice-forge tests."""

from pathlib import Path

import pytest


@pytest.fixture
def tmp_registry(tmp_path: Path, monkeypatch):
    """Isolated registry root in a tmp dir."""
    root = tmp_path / "voices"
    root.mkdir()
    monkeypatch.setenv("VOICE_FORGE_REGISTRY", str(root))
    return root


@pytest.fixture
def tiny_wav(tmp_path: Path) -> Path:
    """Generate a tiny valid WAV file (0.1s of silence at 24kHz mono int16)."""
    import wave

    wav_path = tmp_path / "tiny.wav"
    with wave.open(str(wav_path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(24000)
        f.writeframes(b"\x00" * (24000 * 2 // 10))  # 0.1s of silence
    return wav_path
