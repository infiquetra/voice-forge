"""U5 — Registry.set_persona: the persona promoted to a settable 1:1 binding.

Verifies the binding persists, clears back to the derived persona, raises on a
missing voice, and — critically — that an explicit binding overrides the
existing _derive_persona() fallback without disturbing it (the fleet-safety
guarantee from the readiness review, F4).
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
    # derived persona of "saga-comms-f5" strips the -f5 backend suffix -> "saga-comms"
    r.register("saga-comms-f5", str(wav), "hello there", "f5", metadata={"language": "en"})
    return r


def test_set_persona_persists(reg: Registry) -> None:
    v = reg.set_persona("saga-comms-f5", "Athena")
    assert v.persona == "Athena"
    assert reg.get("saga-comms-f5").persona == "Athena"  # survives reload


def test_explicit_persona_overrides_derived(reg: Registry) -> None:
    # by default the fleet voice carries its DERIVED persona...
    assert reg.get("saga-comms-f5").persona == "saga-comms"
    # ...and an explicit binding overrides it (without touching derivation)
    reg.set_persona("saga-comms-f5", "Saga")
    assert reg.get("saga-comms-f5").persona == "Saga"


def test_clear_persona_reverts_to_derived(reg: Registry) -> None:
    reg.set_persona("saga-comms-f5", "Custom")
    assert reg.get("saga-comms-f5").persona == "Custom"
    v = reg.set_persona("saga-comms-f5", None)
    assert v.persona == "saga-comms"  # back to derived, fleet behaviour preserved


def test_empty_persona_clears(reg: Registry) -> None:
    reg.set_persona("saga-comms-f5", "X")
    assert reg.set_persona("saga-comms-f5", "").persona == "saga-comms"


def test_set_persona_missing_voice_raises(reg: Registry) -> None:
    with pytest.raises(KeyError):
        reg.set_persona("does-not-exist", "Whoever")
