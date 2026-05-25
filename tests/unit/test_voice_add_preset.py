"""Tests for `voice-forge voice add` preset-voice support.

The original v0.1 CLI required a positional ``REF_AUDIO_PATH`` and had no way
to register a preset-only voice (e.g. for Kokoro). v0.2 makes the ref path
optional and adds ``--preset <name>`` for preset-voice backends. These tests
lock that behavior in.
"""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from voice_forge.cli import main


def test_voice_add_kokoro_preset_writes_preset_id_to_metadata(tmp_registry: Path):
    """Registering a Kokoro-style preset voice should persist `preset_id` in metadata.json."""
    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "voice",
            "add",
            "kokoro-bella",
            "--backend",
            "kokoro",
            "--preset",
            "af_bella",
            "--description",
            "Kokoro preset af_bella",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "registered kokoro-bella (backend=kokoro)" in result.output
    assert "af_bella" in result.output

    metadata_path = tmp_registry / "kokoro-bella" / "metadata.json"
    assert metadata_path.is_file()
    meta = json.loads(metadata_path.read_text())
    assert meta["backend"] == "kokoro"
    assert meta["preset_id"] == "af_bella"
    # Preset voices don't carry ref audio.
    assert not (tmp_registry / "kokoro-bella" / "ref.wav").exists()
    assert not (tmp_registry / "kokoro-bella" / "ref.txt").exists()


def test_voice_add_without_ref_or_preset_errors(tmp_registry: Path):
    """`voice add foo` (neither REF_AUDIO_PATH nor --preset) should exit 2 with a clear message."""
    runner = CliRunner()
    result = runner.invoke(main, ["voice", "add", "ghost"])
    assert result.exit_code == 2
    assert "REF_AUDIO_PATH" in result.output
    assert "--preset" in result.output
    # Nothing should have been registered.
    assert not (tmp_registry / "ghost").exists()


def test_voice_add_with_both_ref_and_preset_errors(tmp_registry: Path, tiny_wav: Path):
    """REF_AUDIO_PATH and --preset are mutually exclusive."""
    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "voice",
            "add",
            "ambiguous",
            str(tiny_wav),
            "--preset",
            "af_bella",
            "--backend",
            "kokoro",
        ],
    )
    assert result.exit_code == 2
    assert "mutually exclusive" in result.output
    assert not (tmp_registry / "ambiguous").exists()


def test_voice_add_help_documents_preset_option():
    """The --help output should mention --preset so users discover the new flag."""
    runner = CliRunner()
    result = runner.invoke(main, ["voice", "add", "--help"])
    assert result.exit_code == 0
    assert "--preset" in result.output
    assert "[REF_AUDIO_PATH]" in result.output  # optional positional, shown in brackets
