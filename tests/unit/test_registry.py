"""Tests for the FS-backed voice registry."""

import json
from pathlib import Path

import pytest


def test_registry_starts_empty(tmp_registry):
    from voice_forge.registry import Registry

    reg = Registry(root=tmp_registry)
    assert reg.list() == []


def test_register_and_get(tmp_registry, tiny_wav):
    from voice_forge.registry import Registry

    reg = Registry(root=tmp_registry)
    ref = reg.register(
        voice_id="alice",
        ref_audio_path=tiny_wav,
        ref_text="Hello world.",
        backend="neutts",
        metadata={"language": "en", "description": "test"},
    )
    assert ref.voice_id == "alice"
    assert ref.backend == "neutts"
    assert ref.ref_text == "Hello world."
    assert ref.metadata["language"] == "en"
    assert Path(ref.ref_audio_path).exists()

    fetched = reg.get("alice")
    assert fetched.voice_id == "alice"
    assert fetched.ref_text == "Hello world."


def test_register_duplicate_raises_without_overwrite(tmp_registry, tiny_wav):
    from voice_forge.registry import Registry

    reg = Registry(root=tmp_registry)
    reg.register("alice", tiny_wav, "hi", "neutts")
    with pytest.raises(FileExistsError):
        reg.register("alice", tiny_wav, "hi again", "neutts")


def test_register_overwrite_replaces(tmp_registry, tiny_wav):
    from voice_forge.registry import Registry

    reg = Registry(root=tmp_registry)
    reg.register("alice", tiny_wav, "hi", "neutts")
    ref2 = reg.register("alice", tiny_wav, "hi again", "neutts", overwrite=True)
    assert ref2.ref_text == "hi again"


def test_list_returns_sorted(tmp_registry, tiny_wav):
    from voice_forge.registry import Registry

    reg = Registry(root=tmp_registry)
    reg.register("zebra", tiny_wav, "z", "neutts")
    reg.register("apple", tiny_wav, "a", "neutts")
    reg.register("mango", tiny_wav, "m", "neutts")
    items = reg.list()
    assert [v.voice_id for v in items] == ["apple", "mango", "zebra"]


def test_delete_removes(tmp_registry, tiny_wav):
    from voice_forge.registry import Registry

    reg = Registry(root=tmp_registry)
    reg.register("alice", tiny_wav, "hi", "neutts")
    assert reg.exists("alice")
    reg.delete("alice")
    assert not reg.exists("alice")
    with pytest.raises(KeyError):
        reg.get("alice")


def test_delete_missing_is_idempotent(tmp_registry):
    from voice_forge.registry import Registry

    reg = Registry(root=tmp_registry)
    reg.delete("nonexistent")  # Should not raise
    reg.delete("nonexistent")  # Twice for good measure


def test_get_missing_raises_keyerror(tmp_registry):
    from voice_forge.registry import Registry

    reg = Registry(root=tmp_registry)
    with pytest.raises(KeyError):
        reg.get("nothere")


def test_metadata_persists_to_disk(tmp_registry, tiny_wav):
    from voice_forge.registry import Registry

    reg = Registry(root=tmp_registry)
    reg.register(
        "alice",
        tiny_wav,
        "hi",
        "neutts",
        metadata={"language": "en", "source": "elevenlabs:abc123"},
    )
    meta_path = tmp_registry / "alice" / "metadata.json"
    assert meta_path.exists()
    meta = json.loads(meta_path.read_text())
    assert meta["language"] == "en"
    assert meta["source"] == "elevenlabs:abc123"
    assert meta["backend"] == "neutts"
