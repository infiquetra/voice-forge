"""Ansible Vault 1.1 file-format codec.

Pure-Python implementation using only the ``cryptography`` library —
no ``ansible`` package dependency. Files written by this module are
byte-compatible with ``ansible-vault encrypt`` output (round-trip
tested against fixtures produced by the ``ansible-vault`` CLI).

Why reimplement instead of depending on Ansible?
- Ansible (the full package) is ~80 MB of transitive deps. Voice-forge
  needs to read credential files at process startup, not orchestrate
  configuration management. The Ansible Vault file format itself is
  small + stable: this module is ~150 LOC.
- Users with ``ansible-vault`` installed can still use it to ``edit``
  / ``view`` / ``rekey`` files we write — they're interop-compatible.

Format (well-documented at https://docs.ansible.com/ansible/latest/vault_guide/):
    Header: ``$ANSIBLE_VAULT;1.1;AES256\\n``
    Body:   hex-encoded outer envelope, line-wrapped at 80 chars.
    Outer envelope (after hex-decode): three ``\\n``-separated parts —
        1. salt        (32 bytes, hex-encoded)
        2. HMAC tag    (32 bytes, hex-encoded)
        3. ciphertext  (variable, hex-encoded; AES-256-CTR + PKCS7 padding)

Key derivation:
    PBKDF2-HMAC-SHA256, 10 000 iterations, 80 bytes derived. Split into
    AES key (32 B) ‖ HMAC key (32 B) ‖ AES-CTR IV (16 B). Iteration
    count is Ansible's stable choice — we match it for interop, NOT
    because 10k is enough by modern standards. Threat model note
    in ``secrets/README.md``.

Security:
- HMAC is verified BEFORE decryption (encrypt-then-MAC, constant-time
  compare). A wrong password produces a clean ``BadPasswordError``
  rather than corrupted plaintext.
- We never log the password or derived keys.
- Plaintext is returned as ``bytes`` so the caller can wipe it (write
  zeros over the bytearray) after use; we don't keep references.

Limitations:
- Only the 1.1 / AES256 format is supported. Ansible's older 1.0 format
  used Crypto.Cipher and a different layout — not in scope.
- No support for vault-id labelling (the ``$ANSIBLE_VAULT;1.2;...;label``
  variant). The vault-id workflow is multi-tenant CM territory; voice-
  forge doesn't need it.
"""

from __future__ import annotations

import hmac
import os
import secrets as _secrets
import textwrap
from hashlib import sha256

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

HEADER_LINE = "$ANSIBLE_VAULT;1.1;AES256"
PBKDF2_ITERATIONS = 10_000  # matches Ansible Vault 1.1 — DO NOT change for new files
DERIVED_KEY_LEN = 80  # 32 (AES) + 32 (HMAC) + 16 (CTR IV)
SALT_LEN = 32
HMAC_LEN = 32
AES_KEY_LEN = 32
IV_LEN = 16
BLOCK_SIZE = 16  # AES block size; PKCS7 pads to this
WRAP_COLS = 80  # body line-wrap width in the output file


class VaultError(Exception):
    """Base class for vault format / decryption errors."""


class MalformedVaultError(VaultError):
    """Raised when a file doesn't conform to the Ansible Vault 1.1 layout."""


class BadPasswordError(VaultError):
    """Raised on HMAC mismatch — the password is wrong (or the file was tampered with).

    These cases are indistinguishable cryptographically; we report
    "wrong password" because that's overwhelmingly the most likely cause
    for an interactive user.
    """


def _derive_keys(password: bytes, salt: bytes) -> tuple[bytes, bytes, bytes]:
    """PBKDF2-HMAC-SHA256 → 80 bytes → (aes_key, hmac_key, iv)."""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=DERIVED_KEY_LEN,
        salt=salt,
        iterations=PBKDF2_ITERATIONS,
    )
    derived = kdf.derive(password)
    return (
        derived[0:AES_KEY_LEN],
        derived[AES_KEY_LEN : AES_KEY_LEN + HMAC_LEN],
        derived[AES_KEY_LEN + HMAC_LEN : AES_KEY_LEN + HMAC_LEN + IV_LEN],
    )


def _pkcs7_pad(data: bytes, block_size: int = BLOCK_SIZE) -> bytes:
    pad_len = block_size - (len(data) % block_size)
    return data + bytes([pad_len] * pad_len)


def _pkcs7_unpad(data: bytes, block_size: int = BLOCK_SIZE) -> bytes:
    if not data or len(data) % block_size:
        raise MalformedVaultError("ciphertext length is not a multiple of block size")
    pad_len = data[-1]
    if pad_len < 1 or pad_len > block_size:
        raise MalformedVaultError(f"invalid PKCS7 pad length {pad_len}")
    # Validate every pad byte matches — cheap defense against truncation
    if data[-pad_len:] != bytes([pad_len] * pad_len):
        raise MalformedVaultError("inconsistent PKCS7 padding bytes")
    return data[:-pad_len]


def encrypt(plaintext: bytes, password: str) -> str:
    """Encrypt ``plaintext`` and return an Ansible-Vault-1.1 string.

    The returned string includes the header line and trailing newline,
    matching ``ansible-vault encrypt`` output exactly.
    """
    if not isinstance(plaintext, bytes | bytearray):
        raise TypeError("encrypt() takes bytes — encode str inputs first")
    salt = _secrets.token_bytes(SALT_LEN)
    aes_key, hmac_key, iv = _derive_keys(password.encode("utf-8"), salt)

    padded = _pkcs7_pad(bytes(plaintext))
    cipher = Cipher(algorithms.AES(aes_key), modes.CTR(iv))
    ciphertext = cipher.encryptor().update(padded) + cipher.encryptor().finalize()

    tag = hmac.new(hmac_key, ciphertext, sha256).digest()

    # Inner envelope: three hex strings joined by literal '\n' bytes.
    inner = b"\n".join((salt.hex().encode(), tag.hex().encode(), ciphertext.hex().encode()))

    # Outer hex + 80-col wrap. Matches ansible-vault output.
    body = inner.hex()
    wrapped = "\n".join(textwrap.wrap(body, WRAP_COLS))
    return f"{HEADER_LINE}\n{wrapped}\n"


def decrypt(vault_text: str, password: str) -> bytes:
    """Decrypt an Ansible-Vault-1.1 string and return the plaintext bytes.

    Raises:
      MalformedVaultError: header missing / wrong version / body malformed
      BadPasswordError: HMAC verification failed (password wrong OR tampered)
    """
    if not isinstance(vault_text, str):
        raise TypeError("decrypt() takes a str — decode bytes inputs first")

    lines = vault_text.strip().splitlines()
    if not lines or not lines[0].startswith("$ANSIBLE_VAULT;1.1;AES256"):
        raise MalformedVaultError(
            f"not an Ansible Vault 1.1 file: {lines[0] if lines else '(empty)'}"
        )
    body_hex = "".join(lines[1:]).strip()
    try:
        inner = bytes.fromhex(body_hex)
    except ValueError as e:
        raise MalformedVaultError(f"body is not valid hex: {e}") from None

    parts = inner.split(b"\n")
    if len(parts) != 3:
        raise MalformedVaultError(
            f"expected 3 newline-separated parts in inner envelope, got {len(parts)}"
        )
    try:
        salt = bytes.fromhex(parts[0].decode("ascii"))
        expected_tag = bytes.fromhex(parts[1].decode("ascii"))
        ciphertext = bytes.fromhex(parts[2].decode("ascii"))
    except (ValueError, UnicodeDecodeError) as e:
        raise MalformedVaultError(f"inner envelope contains non-hex data: {e}") from None

    if len(salt) != SALT_LEN or len(expected_tag) != HMAC_LEN:
        raise MalformedVaultError("salt or HMAC tag has unexpected length")

    aes_key, hmac_key, iv = _derive_keys(password.encode("utf-8"), salt)

    # Verify HMAC BEFORE decrypting (encrypt-then-MAC discipline).
    # Constant-time compare prevents timing oracles.
    actual_tag = hmac.new(hmac_key, ciphertext, sha256).digest()
    if not hmac.compare_digest(actual_tag, expected_tag):
        raise BadPasswordError("HMAC mismatch — password is wrong or file was tampered with")

    cipher = Cipher(algorithms.AES(aes_key), modes.CTR(iv))
    padded = cipher.decryptor().update(ciphertext) + cipher.decryptor().finalize()
    return _pkcs7_unpad(padded)


def is_vault_file(text_or_path: str | os.PathLike) -> bool:
    """Quick check: does this look like an Ansible Vault 1.1 header?

    Accepts either a file path (read first line) or the file contents
    as a string. Returns False on any error rather than raising — this
    is a discriminator for "is X a vault file?" not a validator.
    """
    try:
        text = str(text_or_path)
        if "\n" not in text and os.path.isfile(text):
            with open(text, encoding="utf-8") as f:
                first_line = f.readline().strip()
        else:
            first_line = text.splitlines()[0].strip() if text.splitlines() else ""
        return first_line.startswith("$ANSIBLE_VAULT;1.1;AES256")
    except (OSError, IndexError, UnicodeDecodeError):
        return False
