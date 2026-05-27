"""Tests for voice_forge.secrets — the high-level get/set + resolution chain."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from voice_forge.secrets import (
    VaultError,
    get_secret,
    reload,
    save_secrets,
    set_secret,
    show_secrets,
)


@pytest.fixture
def vault_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Point the secrets module at a clean tmp vault + password for one test.

    Yields the vault Path so tests can inspect it. ``reload()`` after the
    monkeypatch + before test body so any prior cached state is dropped.
    """
    vault = tmp_path / "voice-forge.vault"
    pw = tmp_path / "vault_pass"
    pw.write_text("hunter2")
    pw.chmod(0o600)
    monkeypatch.setenv("VOICE_FORGE_VAULT_FILE", str(vault))
    monkeypatch.setenv("VOICE_FORGE_VAULT_PASSWORD_FILE", str(pw))
    monkeypatch.delenv("VOICE_FORGE_VAULT_PASSWORD", raising=False)
    reload()
    yield vault
    reload()


def test_env_var_takes_precedence_over_vault(vault_env: Path, monkeypatch: pytest.MonkeyPatch):
    set_secret("elevenlabs.api_key", "from-vault")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "from-env")
    assert get_secret("elevenlabs.api_key") == "from-env"


def test_vault_used_when_no_env_var(vault_env: Path):
    set_secret("elevenlabs.api_key", "from-vault")
    assert get_secret("elevenlabs.api_key") == "from-vault"


def test_missing_key_returns_default(vault_env: Path):
    set_secret("openai.api_key", "x")
    assert get_secret("elevenlabs.api_key") is None
    assert get_secret("elevenlabs.api_key", default="fallback") == "fallback"


def test_missing_vault_file_does_not_crash(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """No vault file + no env var should return default, not raise."""
    monkeypatch.setenv("VOICE_FORGE_VAULT_FILE", str(tmp_path / "nope.vault"))
    monkeypatch.setenv("VOICE_FORGE_VAULT_PASSWORD_FILE", str(tmp_path / "nope.pass"))
    reload()
    assert get_secret("anything") is None
    assert get_secret("anything", default="ok") == "ok"


def test_dot_path_traverses_nested_dicts(vault_env: Path):
    set_secret("services.elevenlabs.api_key", "deep")
    assert get_secret("services.elevenlabs.api_key") == "deep"
    assert get_secret("services.elevenlabs") == {"api_key": "deep"}


def test_set_creates_nested_dicts(vault_env: Path):
    set_secret("a.b.c.d", 42)
    assert get_secret("a.b.c.d") == 42
    full = show_secrets()
    assert full == {"a": {"b": {"c": {"d": 42}}}}


def test_show_redact_masks_string_values(vault_env: Path):
    set_secret("elevenlabs.api_key", "sk-supersecret-1234567890")
    redacted = show_secrets(redact=True)
    # Should mask the value but preserve the structure
    assert "elevenlabs" in redacted
    assert "api_key" in redacted["elevenlabs"]
    assert "supersecret" not in str(redacted)


def test_env_var_name_derives_from_dot_path():
    # elevenlabs.api_key → ELEVENLABS_API_KEY
    # The mapping is documented; this test pins it so future refactors
    # can't quietly change the convention.
    from voice_forge.secrets import _path_to_env_var

    assert _path_to_env_var("elevenlabs.api_key") == "ELEVENLABS_API_KEY"
    assert _path_to_env_var("a.b.c") == "A_B_C"
    assert _path_to_env_var("simple") == "SIMPLE"


def test_password_file_perms_enforced(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    vault = tmp_path / "v.vault"
    pw = tmp_path / "pw"
    pw.write_text("p")
    pw.chmod(0o644)  # group-readable — too permissive
    monkeypatch.setenv("VOICE_FORGE_VAULT_FILE", str(vault))
    monkeypatch.setenv("VOICE_FORGE_VAULT_PASSWORD_FILE", str(pw))
    monkeypatch.delenv("VOICE_FORGE_VAULT_PASSWORD", raising=False)
    reload()
    # save_secrets would refuse — but get_secret swallows VaultError so
    # we call resolve_password directly to surface the check.
    from voice_forge.secrets import resolve_password

    with pytest.raises(VaultError, match="unsafe permissions"):
        resolve_password()


def test_env_password_overrides_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("VOICE_FORGE_VAULT_FILE", str(tmp_path / "v.vault"))
    monkeypatch.setenv("VOICE_FORGE_VAULT_PASSWORD", "from-env")
    monkeypatch.delenv("VOICE_FORGE_VAULT_PASSWORD_FILE", raising=False)
    reload()
    from voice_forge.secrets import resolve_password

    pw, src = resolve_password()
    assert pw == "from-env"
    assert src == "env"


def test_cache_invalidates_on_mtime_change(vault_env: Path):
    set_secret("a", "v1")
    assert get_secret("a") == "v1"
    # External rewrite (simulating CLI from another shell). Bump mtime
    # explicitly because some filesystems quantize timestamps to 1s.
    save_secrets({"a": "v2"}, vault_path=vault_env, password="hunter2")
    # Force the cache key (mtime) to differ so the in-process cache invalidates
    new_mtime = os.stat(vault_env).st_mtime_ns + 1_000_000_000
    os.utime(vault_env, ns=(new_mtime, new_mtime))
    assert get_secret("a") == "v2"


def test_show_returns_empty_for_fresh_vault(vault_env: Path):
    # No save yet → no file → empty dict
    assert show_secrets() == {}
