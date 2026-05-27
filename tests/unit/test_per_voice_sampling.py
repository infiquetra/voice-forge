"""Tests for the per-voice sampling-params feature.

Schema: optional ``metadata['sampling']: {key: value, ...}`` block stored
in each voice's ``metadata.json``. Registry + CLI plumbing covered here;
per-backend wiring lives in each backend's own test file (test_f5_backend
etc.) as they're added.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from voice_forge.cli import _parse_sampling_kv, _parse_sampling_value, main
from voice_forge.registry import Registry

# ---- value parser ----


def test_parse_sampling_value_int():
    assert _parse_sampling_value("42") == 42
    assert isinstance(_parse_sampling_value("42"), int)


def test_parse_sampling_value_float():
    assert _parse_sampling_value("1.5") == 1.5
    assert isinstance(_parse_sampling_value("1.5"), float)


def test_parse_sampling_value_negative_int():
    assert _parse_sampling_value("-1") == -1


def test_parse_sampling_value_bool_true():
    assert _parse_sampling_value("true") is True
    assert _parse_sampling_value("True") is True
    assert _parse_sampling_value("YES") is True


def test_parse_sampling_value_bool_false():
    assert _parse_sampling_value("false") is False
    assert _parse_sampling_value("no") is False


def test_parse_sampling_value_none():
    assert _parse_sampling_value("none") is None
    assert _parse_sampling_value("NULL") is None


def test_parse_sampling_value_string_fallback():
    assert _parse_sampling_value("af_bella") == "af_bella"
    assert _parse_sampling_value("euler") == "euler"


def test_parse_sampling_kv_multiple_keys():
    out = _parse_sampling_kv(("speed=1.1", "seed=42", "model=euler"))
    assert out == {"speed": 1.1, "seed": 42, "model": "euler"}


def test_parse_sampling_kv_rejects_missing_equals():
    import click

    with pytest.raises(click.BadParameter, match="key=value"):
        _parse_sampling_kv(("speed",))


# ---- Registry.tune() ----


def _seed_voice(tmp_registry: Path, voice_id: str, sampling: dict | None = None) -> None:
    vd = tmp_registry / voice_id
    vd.mkdir(parents=True)
    meta = {
        "voice_id": voice_id,
        "backend": "neutts",
        "language": "en",
        "description": "seed",
    }
    if sampling is not None:
        meta["sampling"] = sampling
    (vd / "metadata.json").write_text(json.dumps(meta, indent=2, sort_keys=True))


def test_registry_tune_sets_sampling_when_missing(tmp_registry: Path):
    _seed_voice(tmp_registry, "v1")
    reg = Registry()
    ref = reg.tune("v1", sampling_overrides={"speed": 1.1, "seed": 42})
    assert ref.metadata["sampling"] == {"speed": 1.1, "seed": 42}

    on_disk = json.loads((tmp_registry / "v1" / "metadata.json").read_text())
    assert on_disk["sampling"] == {"speed": 1.1, "seed": 42}


def test_registry_tune_updates_partial(tmp_registry: Path):
    """Tuning preserves existing keys not in the overrides dict."""
    _seed_voice(tmp_registry, "v1", sampling={"speed": 1.0, "seed": 1})
    reg = Registry()
    reg.tune("v1", sampling_overrides={"seed": 99})  # speed should be preserved
    on_disk = json.loads((tmp_registry / "v1" / "metadata.json").read_text())
    assert on_disk["sampling"] == {"speed": 1.0, "seed": 99}


def test_registry_tune_clear_removes_block(tmp_registry: Path):
    _seed_voice(tmp_registry, "v1", sampling={"speed": 1.5})
    reg = Registry()
    ref = reg.tune("v1", clear=True)
    assert "sampling" not in ref.metadata
    on_disk = json.loads((tmp_registry / "v1" / "metadata.json").read_text())
    assert "sampling" not in on_disk


def test_registry_tune_unknown_voice_raises(tmp_registry: Path):
    reg = Registry()
    with pytest.raises(KeyError, match="not in registry"):
        reg.tune("never-existed", sampling_overrides={"speed": 1.0})


# ---- CLI: voice add --sampling ----


def test_voice_add_with_sampling_writes_to_metadata(tmp_registry: Path, tiny_wav: Path):
    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "voice",
            "add",
            "saga-f5",
            str(tiny_wav),
            "--ref-text",
            "hi",
            "--backend",
            "f5",
            "--sampling",
            "cfg_strength=2.5",
            "--sampling",
            "seed=42",
            "--sampling",
            "nfe_step=24",
        ],
    )
    assert result.exit_code == 0, result.output
    on_disk = json.loads((tmp_registry / "saga-f5" / "metadata.json").read_text())
    assert on_disk["sampling"] == {"cfg_strength": 2.5, "seed": 42, "nfe_step": 24}


def test_voice_add_without_sampling_omits_block(tmp_registry: Path, tiny_wav: Path):
    """Backwards-compatible: no --sampling = no sampling block in metadata."""
    runner = CliRunner()
    result = runner.invoke(
        main,
        ["voice", "add", "plain-voice", str(tiny_wav), "--ref-text", "hi", "--backend", "f5"],
    )
    assert result.exit_code == 0, result.output
    on_disk = json.loads((tmp_registry / "plain-voice" / "metadata.json").read_text())
    assert "sampling" not in on_disk


def test_voice_add_sampling_with_preset_voice(tmp_registry: Path):
    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "voice",
            "add",
            "kokoro-bella-tuned",
            "--backend",
            "kokoro",
            "--preset",
            "af_bella",
            "--sampling",
            "speed=1.2",
        ],
    )
    assert result.exit_code == 0, result.output
    on_disk = json.loads((tmp_registry / "kokoro-bella-tuned" / "metadata.json").read_text())
    assert on_disk["preset_id"] == "af_bella"
    assert on_disk["sampling"] == {"speed": 1.2}


# ---- CLI: voice tune ----


def test_voice_tune_updates_sampling(tmp_registry: Path):
    _seed_voice(tmp_registry, "saga")
    runner = CliRunner()
    result = runner.invoke(
        main,
        ["voice", "tune", "saga", "--sampling", "speed=1.1", "--sampling", "seed=42"],
    )
    assert result.exit_code == 0, result.output
    assert "tuned saga" in result.output
    on_disk = json.loads((tmp_registry / "saga" / "metadata.json").read_text())
    assert on_disk["sampling"] == {"speed": 1.1, "seed": 42}


def test_voice_tune_preserves_existing_keys(tmp_registry: Path):
    _seed_voice(tmp_registry, "saga", sampling={"speed": 1.0, "cfg_strength": 2.0})
    runner = CliRunner()
    result = runner.invoke(main, ["voice", "tune", "saga", "--sampling", "seed=42"])
    assert result.exit_code == 0, result.output
    on_disk = json.loads((tmp_registry / "saga" / "metadata.json").read_text())
    # speed + cfg_strength preserved; seed added
    assert on_disk["sampling"] == {"speed": 1.0, "cfg_strength": 2.0, "seed": 42}


def test_voice_tune_clear_removes_block(tmp_registry: Path):
    _seed_voice(tmp_registry, "saga", sampling={"speed": 1.5})
    runner = CliRunner()
    result = runner.invoke(main, ["voice", "tune", "saga", "--clear-sampling"])
    assert result.exit_code == 0, result.output
    on_disk = json.loads((tmp_registry / "saga" / "metadata.json").read_text())
    assert "sampling" not in on_disk


def test_voice_tune_unknown_voice_exits_1(tmp_registry: Path):
    runner = CliRunner()
    result = runner.invoke(main, ["voice", "tune", "never-existed", "--sampling", "speed=1.0"])
    assert result.exit_code == 1
    assert "not in registry" in result.output


def test_voice_tune_no_args_exits_2(tmp_registry: Path):
    _seed_voice(tmp_registry, "saga")
    runner = CliRunner()
    result = runner.invoke(main, ["voice", "tune", "saga"])
    assert result.exit_code == 2
    assert "--clear-sampling" in result.output or "key=value" in result.output


def test_voice_tune_sampling_and_clear_mutually_exclusive(tmp_registry: Path):
    _seed_voice(tmp_registry, "saga")
    runner = CliRunner()
    result = runner.invoke(
        main,
        ["voice", "tune", "saga", "--sampling", "speed=1.0", "--clear-sampling"],
    )
    assert result.exit_code == 2
    assert "mutually exclusive" in result.output


def test_voice_tune_help_documents_examples():
    runner = CliRunner()
    result = runner.invoke(main, ["voice", "tune", "--help"])
    assert result.exit_code == 0
    assert "cfg_strength" in result.output  # example sampling key
    assert "--clear-sampling" in result.output


# ---- VoiceRef passthrough (smoke) ----


def test_voiceref_carries_sampling_from_metadata(tmp_registry: Path):
    """Registry.get() returns a VoiceRef whose .metadata['sampling'] is round-tripped."""
    _seed_voice(tmp_registry, "saga", sampling={"speed": 1.1, "seed": 7})
    reg = Registry()
    ref = reg.get("saga")
    assert ref.metadata.get("sampling") == {"speed": 1.1, "seed": 7}
