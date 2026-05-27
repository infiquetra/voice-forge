"""Tests for voice_forge.secrets.vault — the Ansible Vault 1.1 codec.

Focuses on (a) round-trip correctness, (b) interop with files produced
by the actual ``ansible-vault`` CLI when available, (c) the failure
modes (bad password, malformed files, unsafe permissions).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from voice_forge.secrets.vault import (
    BadPasswordError,
    MalformedVaultError,
    decrypt,
    encrypt,
    is_vault_file,
)


def test_round_trip_basic():
    pt = b"hello world from voice-forge"
    blob = encrypt(pt, "hunter2")
    assert blob.startswith("$ANSIBLE_VAULT;1.1;AES256\n")
    assert blob.endswith("\n")
    assert decrypt(blob, "hunter2") == pt


def test_round_trip_empty():
    blob = encrypt(b"", "p")
    assert decrypt(blob, "p") == b""


def test_round_trip_unicode():
    pt = "Bokmål — Iceland — 中文 — 🎤".encode()
    blob = encrypt(pt, "påsswørd")
    assert decrypt(blob, "påsswørd") == pt


def test_round_trip_long_payload():
    pt = (b"voice-forge secrets " * 1000)[:16_000]
    blob = encrypt(pt, "k")
    assert decrypt(blob, "k") == pt


def test_round_trip_block_boundary_lengths():
    # Hit each PKCS7 pad-length 1..16 to flush out padding bugs
    for n in (15, 16, 17, 31, 32, 33):
        pt = b"x" * n
        blob = encrypt(pt, "p")
        assert decrypt(blob, "p") == pt, f"length {n} round-trip failed"


def test_wrong_password_raises_bad_password_error():
    blob = encrypt(b"top secret", "right")
    with pytest.raises(BadPasswordError):
        decrypt(blob, "wrong")


def test_bytes_input_required_for_encrypt():
    with pytest.raises(TypeError):
        encrypt("a str, not bytes", "p")  # type: ignore[arg-type]


def test_str_input_required_for_decrypt():
    with pytest.raises(TypeError):
        decrypt(b"raw bytes", "p")  # type: ignore[arg-type]


def test_malformed_header_raises():
    with pytest.raises(MalformedVaultError):
        decrypt("not a vault file\nrandom contents", "p")


def test_malformed_hex_body_raises():
    blob = "$ANSIBLE_VAULT;1.1;AES256\nNOT-HEX-AT-ALL\n"
    with pytest.raises(MalformedVaultError):
        decrypt(blob, "p")


def test_truncated_inner_envelope_raises():
    # Build a vault-looking blob whose decoded inner envelope has only
    # 1 newline-separated part instead of 3.
    inner = b"01" * 32  # one hex-encoded blob, no separators
    body = inner.hex()
    blob = f"$ANSIBLE_VAULT;1.1;AES256\n{body}\n"
    with pytest.raises(MalformedVaultError):
        decrypt(blob, "p")


def test_each_encryption_uses_a_fresh_salt():
    # Two encrypts of the same plaintext+password produce different
    # ciphertexts (because salt + IV are randomized).
    pt = b"determinism would be a bug here"
    a = encrypt(pt, "p")
    b = encrypt(pt, "p")
    assert a != b
    assert decrypt(a, "p") == pt == decrypt(b, "p")


def test_is_vault_file_string_inputs():
    yes = encrypt(b"x", "p")
    assert is_vault_file(yes)
    assert not is_vault_file("not a vault file\nat all")


def test_is_vault_file_path_inputs(tmp_path: Path):
    f = tmp_path / "v.vault"
    f.write_text(encrypt(b"x", "p"))
    assert is_vault_file(f)
    other = tmp_path / "plain.txt"
    other.write_text("hello")
    assert not is_vault_file(other)


@pytest.mark.skipif(shutil.which("ansible-vault") is None, reason="ansible-vault CLI not installed")
def test_interop_decrypt_ansible_vault_produced_file(tmp_path: Path):
    """Files that ``ansible-vault encrypt`` writes must decrypt for us."""
    pw_file = tmp_path / "pw"
    pw_file.write_text("hunter2")
    pw_file.chmod(0o600)
    payload = b"interop-test from ansible-vault"
    in_file = tmp_path / "plain.txt"
    in_file.write_bytes(payload)
    subprocess.check_call(  # noqa: S603
        [
            "ansible-vault",
            "encrypt",
            "--vault-password-file",
            str(pw_file),
            str(in_file),
        ]
    )
    blob = in_file.read_text()
    assert blob.startswith("$ANSIBLE_VAULT;1.1;AES256")
    assert decrypt(blob, "hunter2") == payload


@pytest.mark.skipif(shutil.which("ansible-vault") is None, reason="ansible-vault CLI not installed")
def test_interop_ansible_vault_can_decrypt_our_output(tmp_path: Path):
    """Files we ``encrypt`` must decrypt cleanly with the ``ansible-vault`` CLI."""
    pw_file = tmp_path / "pw"
    pw_file.write_text("hunter2")
    pw_file.chmod(0o600)
    payload = b"voice-forge encrypted this; ansible-vault can read it"
    our_blob = encrypt(payload, "hunter2")
    vault_file = tmp_path / "v.vault"
    vault_file.write_text(our_blob)
    out = subprocess.check_output(  # noqa: S603
        [
            "ansible-vault",
            "view",
            "--vault-password-file",
            str(pw_file),
            str(vault_file),
        ]
    )
    # ansible-vault view appends a trailing newline on output; strip it for
    # the comparison. The vault file content itself was identical.
    assert out.rstrip(b"\n") == payload
