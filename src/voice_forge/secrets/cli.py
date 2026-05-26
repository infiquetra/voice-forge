"""CLI for the voice-forge secrets store.

Entry-point: ``voice-forge-secrets <subcommand>``. Subcommands:

  init    — Create an empty vault file. Prompts for password (or reads from
            ``$VOICE_FORGE_VAULT_PASSWORD`` / password file if already set).
            Won't clobber an existing vault unless ``--force`` is passed.

  edit    — Decrypt to a temp file, open in ``$EDITOR`` (or vi), re-encrypt
            on save. Mirrors ``ansible-vault edit`` UX. Temp file is removed
            even on editor crash (best-effort).

  show    — Print the decrypted vault contents as YAML to stdout. With
            ``--redact``, replaces string values with truncated previews
            so it's screenshot-safe.

  get     — Print one value by dot-path. Useful for shell: ``API_KEY=$(...)``.
            Exits non-zero (1) if the key is missing.

  set     — Set one dot-path value. Reads value from argv or stdin (``-``).

  rotate  — Re-encrypt the vault under a new password. Prompts twice for
            confirmation. The old password must still be valid to read the
            current contents.

  path    — Print the active vault path + password source. No secrets touched.

  encrypt — Plumbing: encrypt arbitrary stdin to vault format on stdout.
  decrypt — Plumbing: decrypt a vault file from argv to stdout.
"""

from __future__ import annotations

import argparse
import getpass
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

from . import (
    BadPasswordError,
    MalformedVaultError,
    VaultError,
    get_config,
    reload,
    resolve_password,
    resolve_vault_path,
    save_secrets,
    set_secret,
    show_secrets,
)
from .vault import decrypt, encrypt, is_vault_file


def _prompt_password(label: str = "Vault password") -> str:
    """Prompt the user for a password without echo."""
    return getpass.getpass(f"{label}: ")


def _editor() -> list[str]:
    """Pick an editor. ``$EDITOR`` if set, else `vi` (POSIX) / `notepad` (Windows)."""
    env_editor = os.environ.get("EDITOR")
    if env_editor:
        return env_editor.split()  # supports `EDITOR='code --wait'`
    if shutil.which("vi"):
        return ["vi"]
    if sys.platform == "win32" and shutil.which("notepad"):
        return ["notepad"]
    sys.exit("no $EDITOR set and no fallback editor (vi / notepad) found")


# ---------- subcommands ----------


def cmd_init(args: argparse.Namespace) -> int:
    vault_path = resolve_vault_path()
    if vault_path.is_file() and not args.force:
        sys.exit(f"vault already exists at {vault_path}; use --force to overwrite")

    # Resolve / prompt for a password. Don't use resolve_password() here
    # because we'd want to PROMPT if missing rather than error out.
    pw_env = os.environ.get("VOICE_FORGE_VAULT_PASSWORD")
    pw_file = Path(
        os.environ.get(
            "VOICE_FORGE_VAULT_PASSWORD_FILE", Path.home() / ".voice-forge" / "vault_pass"
        )
    ).expanduser()
    if pw_env:
        password = pw_env
        print("using password from $VOICE_FORGE_VAULT_PASSWORD env var")
    elif pw_file.is_file():
        password = pw_file.read_text().strip()
        print(f"using password from {pw_file}")
    else:
        password = _prompt_password("New vault password")
        confirm = _prompt_password("Confirm password")
        if password != confirm:
            sys.exit("passwords do not match")
        # Offer to save the password to the default location
        if not args.no_save_password:
            pw_file.parent.mkdir(parents=True, exist_ok=True)
            pw_file.write_text(password + "\n")
            pw_file.chmod(0o600)
            print(f"saved password to {pw_file} (mode 0600)")

    initial: dict = {}
    save_secrets(initial, vault_path=vault_path, password=password)
    print(f"initialized empty vault at {vault_path} (mode 0600)")
    return 0


def cmd_edit(args: argparse.Namespace) -> int:
    vault_path = resolve_vault_path()
    if not vault_path.is_file():
        sys.exit(f"no vault at {vault_path} — run `voice-forge-secrets init` first")
    password, _ = resolve_password()

    plaintext = decrypt(vault_path.read_text(), password)

    # Edit in a temp file. Use mkstemp so we control the suffix (.yaml for
    # editor syntax highlighting) and can chmod 0600 before writing.
    fd, tmp_path = tempfile.mkstemp(suffix=".yaml", prefix="voice-forge-vault-")
    tmp = Path(tmp_path)
    try:
        os.close(fd)
        tmp.chmod(0o600)
        tmp.write_bytes(plaintext)
        editor_argv = _editor()
        # nosec B603: editor argv is from $EDITOR or hardcoded fallbacks; this is
        # the documented pattern for "open user editor on file" (mirrors git, sudoedit).
        subprocess.call([*editor_argv, str(tmp)])  # noqa: S603
        new_text = tmp.read_bytes()
        if new_text == plaintext:
            print("no changes; vault not rewritten")
            return 0
        # Validate the user typed valid YAML before we re-encrypt.
        try:
            parsed = yaml.safe_load(new_text.decode("utf-8")) or {}
        except yaml.YAMLError as e:
            sys.exit(f"vault file is not valid YAML after edit — refusing to save:\n  {e}")
        if not isinstance(parsed, dict):
            sys.exit(f"vault root must be a YAML mapping; got {type(parsed).__name__}")
        save_secrets(parsed, vault_path=vault_path, password=password)
        print(f"vault updated → {vault_path}")
        return 0
    finally:
        # Wipe + remove the temp file even if the editor crashed. Best-effort
        # zero overwrite — won't beat a forensic disk recovery, but better
        # than leaving plaintext sitting on disk.
        try:
            tmp.write_bytes(b"\0" * len(plaintext))
        except OSError:
            pass
        tmp.unlink(missing_ok=True)


def cmd_show(args: argparse.Namespace) -> int:
    try:
        data = show_secrets(redact=args.redact)
    except VaultError as e:
        sys.exit(f"vault error: {e}")
    print(
        yaml.safe_dump(data, sort_keys=True, allow_unicode=True, default_flow_style=False), end=""
    )
    return 0


def cmd_get(args: argparse.Namespace) -> int:
    from . import get_secret  # local import to avoid top-level cycle

    val = get_secret(args.key)
    if val is None:
        sys.exit(f"key not found: {args.key!r}")
    # Don't wrap in quotes — output suitable for `KEY=$(... get ...)`.
    print(val)
    return 0


def cmd_set(args: argparse.Namespace) -> int:
    value = args.value
    if value == "-":
        value = sys.stdin.read().rstrip("\n")
    try:
        set_secret(args.key, value)
    except VaultError as e:
        sys.exit(f"vault error: {e}")
    print(f"set {args.key}")
    return 0


def cmd_rotate(args: argparse.Namespace) -> int:
    vault_path = resolve_vault_path()
    if not vault_path.is_file():
        sys.exit(f"no vault at {vault_path}")
    # Need OLD password to decrypt; resolve_password reads from env/file as configured.
    old_pw, src = resolve_password()
    plaintext = decrypt(vault_path.read_text(), old_pw)

    new_pw = _prompt_password("New vault password")
    confirm = _prompt_password("Confirm new password")
    if new_pw != confirm:
        sys.exit("passwords do not match")
    if new_pw == old_pw:
        sys.exit("new password matches old — nothing to do")

    new_blob = encrypt(plaintext, new_pw)
    vault_path.write_text(new_blob)
    vault_path.chmod(0o600)

    # If the old password came from a file, offer to update it.
    if src.startswith("file:"):
        pw_file = Path(src.split(":", 1)[1])
        if pw_file.is_file() and not args.no_update_password_file:
            pw_file.write_text(new_pw + "\n")
            pw_file.chmod(0o600)
            print(f"updated password file {pw_file}")

    reload()
    print(f"vault rotated → {vault_path}")
    return 0


def cmd_path(args: argparse.Namespace) -> int:
    cfg = get_config()
    print(f"vault    : {cfg.vault_path}")
    print(f"exists   : {cfg.vault_path.is_file()}")
    print(f"password : {cfg.password_source}")
    return 0


def cmd_encrypt(args: argparse.Namespace) -> int:
    password, _ = resolve_password()
    plaintext = sys.stdin.buffer.read()
    sys.stdout.write(encrypt(plaintext, password))
    return 0


def cmd_decrypt(args: argparse.Namespace) -> int:
    password, _ = resolve_password()
    path = Path(args.path).expanduser()
    if not path.is_file():
        sys.exit(f"no such file: {path}")
    text = path.read_text()
    if not is_vault_file(text):
        sys.exit(f"not an Ansible Vault file: {path}")
    try:
        plaintext = decrypt(text, password)
    except BadPasswordError as e:
        sys.exit(f"bad password: {e}")
    except MalformedVaultError as e:
        sys.exit(f"malformed vault: {e}")
    sys.stdout.buffer.write(plaintext)
    return 0


# ---------- argparse wiring ----------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="voice-forge-secrets",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init", help="create empty vault")
    p_init.add_argument("--force", action="store_true", help="overwrite existing vault")
    p_init.add_argument(
        "--no-save-password",
        action="store_true",
        help="don't write the password file when prompting for a new password",
    )
    p_init.set_defaults(func=cmd_init)

    p_edit = sub.add_parser("edit", help="edit vault in $EDITOR")
    p_edit.set_defaults(func=cmd_edit)

    p_show = sub.add_parser("show", help="print decrypted vault YAML to stdout")
    p_show.add_argument("--redact", action="store_true", help="mask string values")
    p_show.set_defaults(func=cmd_show)

    p_get = sub.add_parser("get", help="print one value by dot-path")
    p_get.add_argument("key", help="dot-path, e.g. elevenlabs.api_key")
    p_get.set_defaults(func=cmd_get)

    p_set = sub.add_parser("set", help="set one value by dot-path")
    p_set.add_argument("key", help="dot-path, e.g. elevenlabs.api_key")
    p_set.add_argument("value", help="literal value, or '-' to read from stdin")
    p_set.set_defaults(func=cmd_set)

    p_rotate = sub.add_parser("rotate", help="re-encrypt vault with new password")
    p_rotate.add_argument(
        "--no-update-password-file",
        action="store_true",
        help="don't auto-update the password file (default: update if file was used)",
    )
    p_rotate.set_defaults(func=cmd_rotate)

    p_path = sub.add_parser("path", help="show active vault path + password source")
    p_path.set_defaults(func=cmd_path)

    p_enc = sub.add_parser("encrypt", help="encrypt stdin → vault on stdout")
    p_enc.set_defaults(func=cmd_encrypt)

    p_dec = sub.add_parser("decrypt", help="decrypt a vault file → stdout")
    p_dec.add_argument("path", help="path to vault file")
    p_dec.set_defaults(func=cmd_decrypt)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    sys.exit(main())
