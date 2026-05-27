"""Smoke tests for the CLI — verify commands exist and basic parsing works.

Doesn't actually invoke heavy backends (NeuTTS load, Whisper, etc.) since those
need external deps. Just confirms Click wiring is sane.
"""

from click.testing import CliRunner

from voice_forge.cli import main


def test_cli_version_works():
    runner = CliRunner()
    result = runner.invoke(main, ["--version"])
    assert result.exit_code == 0
    assert "0.2.0" in result.output


def test_cli_help_lists_subcommands():
    runner = CliRunner()
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    for cmd in ["serve", "synth", "voices", "voice", "health"]:
        assert cmd in result.output


def test_voice_subgroup_help():
    runner = CliRunner()
    result = runner.invoke(main, ["voice", "--help"])
    assert result.exit_code == 0
    for sub in ["add", "from-elevenlabs", "delete", "retrim"]:
        assert sub in result.output


def test_voices_command_empty_registry(tmp_registry):
    runner = CliRunner()
    result = runner.invoke(main, ["voices"])
    assert result.exit_code == 0
    assert "no voices registered" in result.output


def test_health_command_structure(tmp_registry, monkeypatch):
    runner = CliRunner()
    # Don't trigger real backend imports (neutts/kokoro may not be installed
    # in test env). The CLI's `health` command iterates known_backends() and
    # imports each; monkeypatch the imported-name in the cli module.
    monkeypatch.setattr("voice_forge.cli.load_backend_module", lambda *a, **k: None)
    result = runner.invoke(main, ["health"])
    assert result.exit_code == 0
    assert "version" in result.output
    assert "registry_dir" in result.output
