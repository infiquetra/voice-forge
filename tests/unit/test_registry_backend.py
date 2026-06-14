"""U6 — Registry.set_backend: a voice's backend promoted to an in-place edit.

Mirrors test_registry_persona. Verifies the backend persists across reload,
that the 1-key metadata edit leaves persona + language untouched, raises on a
missing voice, and rejects an empty backend.
"""

from __future__ import annotations

import struct
import wave
from pathlib import Path

import pytest

from voice_forge.registry import Registry


def _dummy_wav(path: Path) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(struct.pack("<" + "h" * 100, *([0] * 100)))


@pytest.fixture
def reg(tmp_path: Path) -> Registry:
    r = Registry(tmp_path / "reg")
    wav = tmp_path / "ref.wav"
    _dummy_wav(wav)
    r.register("saga-comms-f5", str(wav), "hello there", "f5", metadata={"language": "en"})
    return r


def test_set_backend_persists(reg: Registry) -> None:
    v = reg.set_backend("saga-comms-f5", "higgs")
    assert v.backend == "higgs"
    assert reg.get("saga-comms-f5").backend == "higgs"  # survives reload


def test_set_backend_preserves_other_metadata(reg: Registry) -> None:
    reg.set_persona("saga-comms-f5", "Saga")
    reg.set_backend("saga-comms-f5", "neutts")
    v = reg.get("saga-comms-f5")
    assert v.backend == "neutts"
    assert v.persona == "Saga"  # not clobbered
    assert v.metadata.get("language") == "en"


def test_set_backend_missing_voice_raises(reg: Registry) -> None:
    with pytest.raises(KeyError):
        reg.set_backend("does-not-exist", "higgs")


def test_set_backend_empty_raises(reg: Registry) -> None:
    with pytest.raises(ValueError):
        reg.set_backend("saga-comms-f5", "")
