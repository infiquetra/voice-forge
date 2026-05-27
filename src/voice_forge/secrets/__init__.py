"""Voice-forge encrypted credential store.

Wraps :mod:`voice_forge.secrets.vault` (Ansible Vault 1.1 codec) with a
file + dot-path API that the rest of voice-forge uses to fetch
credentials without each call site having to know where the vault
lives or how to decrypt it.

Resolution chain for ``get_secret(path)``:

  1. **Explicit env var** — ``path = "elevenlabs.api_key"`` looks for
     ``ELEVENLABS_API_KEY`` first. The env-var name is the path with
     dots → underscores, uppercased.
  2. **Vault file** — the encrypted YAML at
     ``$VOICE_FORGE_VAULT_FILE`` (default: ``secrets/voice-forge.vault``
     in the current working directory, then ``~/.voice-forge/secrets.vault``
     as a fallback). Decrypted with the password from
     ``$VOICE_FORGE_VAULT_PASSWORD_FILE`` (default
     ``~/.voice-forge/vault_pass``), then dot-path traversed for the key.
  3. **None** — secret is genuinely missing. Caller decides whether
     that's fatal.

The vault is decrypted **once per process** and cached in-memory. Call
:func:`reload` to invalidate (e.g. after writing a new secret via the
CLI from a different terminal). The cache is keyed by vault file path
+ mtime, so an external edit re-triggers decryption transparently.

Threat model
------------
- Vault file at rest: AES-256-CTR with HMAC-SHA256, salt + IV randomized
  per file. Safe to commit if you trust your password against attacker
  GPU time (PBKDF2 iterations are Ansible's 10 000 — adequate against
  online attacks, not future-proof against offline brute force of weak
  passwords).
- Vault file in memory: decrypted lazily, kept in a module-global until
  process exit OR :func:`reload`. We do NOT wipe the buffer; if you
  need that, fork voice-forge or call ``del secrets._cache; gc.collect()``
  before sensitive operations.
- Password file: should be ``chmod 600`` and outside the repo
  (default ``~/.voice-forge/vault_pass``). We refuse to read it if
  group or world has read access.
- Env-var override: ``VOICE_FORGE_VAULT_PASSWORD`` skips the password
  file entirely. Useful for CI/Docker; obviously visible in process
  listings — don't use on a shared host.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .vault import (
    BadPasswordError,
    MalformedVaultError,
    VaultError,
    decrypt,
    encrypt,
    is_vault_file,
)

__all__ = [
    "BadPasswordError",
    "MalformedVaultError",
    "SecretsConfig",
    "VaultError",
    "get_secret",
    "reload",
    "resolve_vault_path",
    "resolve_password",
    "save_secrets",
    "set_secret",
    "show_secrets",
]


DEFAULT_VAULT_PATHS = (
    Path("secrets/voice-forge.vault"),  # repo-local
    Path.home() / ".voice-forge" / "secrets.vault",  # user-global fallback
)
DEFAULT_PASSWORD_FILE = Path.home() / ".voice-forge" / "vault_pass"

ENV_VAULT_FILE = "VOICE_FORGE_VAULT_FILE"
ENV_PASSWORD_FILE = "VOICE_FORGE_VAULT_PASSWORD_FILE"
ENV_PASSWORD = "VOICE_FORGE_VAULT_PASSWORD"


@dataclass(frozen=True)
class SecretsConfig:
    """Where the vault + password live for the current process."""

    vault_path: Path
    password_source: str  # "env" | "file:<path>" | "missing"

    def __repr__(self) -> str:
        return f"SecretsConfig(vault={self.vault_path}, pw={self.password_source})"


# In-process cache. Keyed by absolute vault path → (mtime_ns, decrypted_dict).
# A change in mtime forces re-decrypt; this is what lets the CLI write a new
# secret from one shell and have the running service notice on next access.
_cache: dict[Path, tuple[int, dict[str, Any]]] = {}


# ---------- Path / password resolution ----------


def resolve_vault_path() -> Path:
    """Pick the vault file: ``$VOICE_FORGE_VAULT_FILE`` → repo → home.

    Returns the path that EXISTS, falling back to the repo-local default
    if none exist (so an init flow has a sensible target).
    """
    override = os.environ.get(ENV_VAULT_FILE)
    if override:
        return Path(override).expanduser().resolve()
    for cand in DEFAULT_VAULT_PATHS:
        p = cand.expanduser().resolve()
        if p.is_file():
            return p
    return DEFAULT_VAULT_PATHS[0].expanduser().resolve()


def _check_password_file_perms(path: Path) -> None:
    """Refuse to read a password file readable by group / world (mode bits)."""
    try:
        mode = path.stat().st_mode
    except OSError:
        return
    if mode & 0o077:
        raise VaultError(
            f"password file {path} has unsafe permissions {oct(mode & 0o777)}; "
            f"run `chmod 600 {path}` and try again"
        )


def resolve_password() -> tuple[str, str]:
    """Get the vault password + a short source-of-record string.

    Returns ``(password, source)`` where source is one of:
      - ``"env"`` — from ``$VOICE_FORGE_VAULT_PASSWORD``
      - ``"file:<absolute_path>"`` — from the password file
      - raises VaultError if neither resolves.
    """
    direct = os.environ.get(ENV_PASSWORD)
    if direct:
        return direct, "env"

    pwf_env = os.environ.get(ENV_PASSWORD_FILE)
    pwf = Path(pwf_env).expanduser().resolve() if pwf_env else DEFAULT_PASSWORD_FILE
    if pwf.is_file():
        _check_password_file_perms(pwf)
        return pwf.read_text().strip(), f"file:{pwf}"

    raise VaultError(
        f"no vault password — set ${ENV_PASSWORD} or write password to {pwf} "
        f"(chmod 600). Use `voice-forge secrets init` to create the vault."
    )


def get_config() -> SecretsConfig:
    """Diagnostic: where am I reading from?"""
    vault_path = resolve_vault_path()
    try:
        _, src = resolve_password()
    except VaultError:
        src = "missing"
    return SecretsConfig(vault_path=vault_path, password_source=src)


# ---------- Vault load / decrypt ----------


def _load_vault(vault_path: Path) -> dict[str, Any]:
    """Decrypt + parse the vault file. Uses + populates :data:`_cache`."""
    if not vault_path.is_file():
        return {}
    mtime = vault_path.stat().st_mtime_ns
    cached = _cache.get(vault_path)
    if cached is not None and cached[0] == mtime:
        return cached[1]

    text = vault_path.read_text()
    if not is_vault_file(text):
        raise MalformedVaultError(f"{vault_path} is not an Ansible Vault file")
    password, _ = resolve_password()
    plaintext = decrypt(text, password)
    data = yaml.safe_load(plaintext.decode("utf-8")) or {}
    if not isinstance(data, dict):
        raise MalformedVaultError(
            f"{vault_path} decrypted content is not a YAML mapping (got {type(data).__name__})"
        )
    _cache[vault_path] = (mtime, data)
    return data


def reload() -> None:
    """Drop the in-process vault cache. Next ``get_secret`` re-decrypts."""
    _cache.clear()


# ---------- High-level API ----------


def _path_to_env_var(path: str) -> str:
    """``elevenlabs.api_key`` → ``ELEVENLABS_API_KEY`` for env-var fallback."""
    return path.replace(".", "_").upper()


def _dot_lookup(data: dict[str, Any], path: str) -> Any:
    """Traverse a dot-path through a nested dict. Returns None on missing."""
    cur: Any = data
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _dot_set(data: dict[str, Any], path: str, value: Any) -> None:
    """Mutate ``data`` to set ``path`` → ``value``, creating nested dicts as needed."""
    parts = path.split(".")
    cur: dict[str, Any] = data
    for part in parts[:-1]:
        nxt = cur.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[part] = nxt
        cur = nxt
    cur[parts[-1]] = value


def get_secret(path: str, *, default: Any = None) -> Any:
    """Look up ``path`` (dot-separated) — env var first, then vault.

    Returns ``default`` (None) if neither source has the key. Does NOT
    raise on missing-vault-file or missing-password, since the env-var
    path is supposed to work without any vault setup.
    """
    env_name = _path_to_env_var(path)
    env_val = os.environ.get(env_name)
    if env_val:
        return env_val

    vault_path = resolve_vault_path()
    try:
        data = _load_vault(vault_path)
    except VaultError:
        # Missing/malformed/wrong-password vault. Don't crash the caller —
        # they might be using env-vars-only on this host.
        return default
    val = _dot_lookup(data, path) if data else None
    return default if val is None else val


def set_secret(path: str, value: Any) -> None:
    """Set ``path`` → ``value`` in the vault file. Reads-modifies-writes."""
    vault_path = resolve_vault_path()
    password, _ = resolve_password()
    if vault_path.is_file():
        plaintext = decrypt(vault_path.read_text(), password)
        data = yaml.safe_load(plaintext.decode("utf-8")) or {}
        if not isinstance(data, dict):
            raise MalformedVaultError("vault content is not a YAML mapping")
    else:
        data = {}
    _dot_set(data, path, value)
    save_secrets(data, vault_path=vault_path, password=password)
    reload()


def show_secrets(*, redact: bool = False) -> dict[str, Any]:
    """Return the decrypted vault contents (optionally redact values)."""
    vault_path = resolve_vault_path()
    data = _load_vault(vault_path)
    if not redact:
        return dict(data)

    def _walk(node: Any) -> Any:
        if isinstance(node, dict):
            return {k: _walk(v) for k, v in node.items()}
        if isinstance(node, list):
            return [_walk(v) for v in node]
        if isinstance(node, str):
            return node[:4] + "…(redacted)" if len(node) > 8 else "…(redacted)"
        return "…(redacted)"

    return _walk(data)


def save_secrets(
    data: dict[str, Any], *, vault_path: Path | None = None, password: str | None = None
) -> Path:
    """Encrypt ``data`` (a dict) and write to the vault path. Returns the path written."""
    path = vault_path or resolve_vault_path()
    pw = password or resolve_password()[0]
    yaml_text = yaml.safe_dump(data, sort_keys=True, allow_unicode=True, default_flow_style=False)
    encrypted = encrypt(yaml_text.encode("utf-8"), pw)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(encrypted)
    # 0600 so the file isn't world-readable even before encryption catches up.
    try:
        path.chmod(0o600)
    except OSError:
        pass
    reload()
    return path
