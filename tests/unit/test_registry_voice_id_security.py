"""Security regression: voice_id is a directory name, so it MUST be a safe slug.

Without validation, a body-supplied voice_id like ``../escape`` or ``/etc/x``
(which bypasses URL-path normalization on the JSON-body endpoints forge_pick /
from-elevenlabs) would let register()/set_*() write files anywhere the server
can — a path-traversal / arbitrary-write primitive. The guard lives in the
registry's single chokepoint (``_voice_dir``), so every per-voice op is covered.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from voice_forge.registry import Registry, _validate_voice_id

TRAVERSAL_IDS = ["../escape", "../../etc/x", "/etc/passwd", "a/b", "..", ".", "", "foo/../bar"]
VALID_IDS = ["warm-gravelly-narrator", "heid-research", "freya-v1", "voice_1", "a.b", "X"]


@pytest.mark.parametrize("bad", TRAVERSAL_IDS)
def test_validate_rejects_unsafe_ids(bad: str) -> None:
    with pytest.raises(ValueError):
        _validate_voice_id(bad)


@pytest.mark.parametrize("good", VALID_IDS)
def test_validate_accepts_safe_slugs(good: str) -> None:
    assert _validate_voice_id(good) == good


def test_register_rejects_traversal_and_writes_nothing(tmp_path: Path) -> None:
    # A real register() attempt with a traversal id must raise BEFORE any mkdir/
    # copy, and must NOT create anything outside (or inside) the registry root.
    root = tmp_path / "registry"
    root.mkdir()
    ref = tmp_path / "ref.wav"
    ref.write_bytes(b"RIFF....WAVE")  # contents irrelevant; the call must abort first
    reg = Registry(root=root)

    sentinel_outside = tmp_path / "escaped"
    with pytest.raises(ValueError):
        reg.register(
            voice_id="../escaped",
            ref_audio_path=str(ref),
            ref_text="x",
            backend="f5",
            metadata={},
        )
    assert not sentinel_outside.exists(), "traversal id wrote outside the registry root"
    assert list(root.iterdir()) == [], "traversal id created a dir inside the root"


def test_set_backend_and_set_persona_reject_traversal(tmp_path: Path) -> None:
    root = tmp_path / "registry"
    root.mkdir()
    reg = Registry(root=root)
    with pytest.raises(ValueError):
        reg.set_backend("../escape", "f5")
    with pytest.raises(ValueError):
        reg.set_persona("/abs/x", "Persona")
