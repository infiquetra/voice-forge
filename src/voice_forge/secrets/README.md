# voice_forge.secrets

Encrypted credential store for voice-forge. Ansible-Vault-1.1 file
format (interop-compatible with the `ansible-vault` CLI) but
implemented in pure Python on top of `cryptography` — no Ansible
dependency.

## Quick start

```bash
# 1. Create the vault (prompts for password; saves to ~/.voice-forge/vault_pass)
voice-forge-secrets init

# 2. Add credentials
voice-forge-secrets set elevenlabs.api_key sk-...
voice-forge-secrets set openai.api_key sk-...

# 3. Verify
voice-forge-secrets show --redact
voice-forge-secrets path
```

In Python code:

```python
from voice_forge.secrets import get_secret
api_key = get_secret("elevenlabs.api_key")  # None if missing
```

## File locations

| Default | Override |
|---|---|
| `secrets/voice-forge.vault` (repo) → falls back to `~/.voice-forge/secrets.vault` | `$VOICE_FORGE_VAULT_FILE` |
| `~/.voice-forge/vault_pass` (mode 0600) | `$VOICE_FORGE_VAULT_PASSWORD_FILE` |
| — | `$VOICE_FORGE_VAULT_PASSWORD` (skip file entirely; CI/Docker) |

The repo-local vault path is **gitignored by default** (`secrets/` in
`.gitignore`). If you want it sync'd via git across your machines,
remove that gitignore — the file is encrypted, so committing it is
safe as long as your vault password is strong + secret.

## Resolution chain

`get_secret("path.to.key")` tries in order:

1. Env var named after the dot-path (`PATH_TO_KEY`)
2. Vault file (decrypted + cached in-process)
3. Returns `default` (None unless specified)

This means callers can override any vault value at process start by
exporting the corresponding env var — useful for one-off testing
without re-editing the vault.

## Threat model

**Encrypted file at rest.** AES-256-CTR with HMAC-SHA256, random salt
+ IV per file. Safe to leak if (a) your password is strong, (b) you
trust the attacker doesn't have unbounded GPU time. PBKDF2 iterations
are Ansible's stable 10 000 — adequate against online attacks, not
future-proof against well-funded offline brute-forcing of weak
passwords. **Pick a password no shorter than 16 random characters**
or a multi-word passphrase.

**Decrypted contents in memory.** Cached once per process; not wiped
on exit (interpreter doesn't promise that anyway). If you're paranoid,
fork voice-forge or run sensitive operations in short-lived
subprocesses.

**Password file.** Default location `~/.voice-forge/vault_pass`. We
refuse to read it if mode bits permit group / world read (i.e. anything
other than 0600). Run `chmod 600 ~/.voice-forge/vault_pass` to fix.

**Env-var password.** `$VOICE_FORGE_VAULT_PASSWORD` is visible in
`ps aux` and in `/proc/$PID/environ` on Linux. Use only on hosts
where you trust the other processes (CI runners, single-tenant
containers). Don't use on a shared dev box.

## Editing the vault

Three workflows for changing values:

1. **One-off:** `voice-forge-secrets set elevenlabs.api_key sk-new`
2. **Bulk:** `voice-forge-secrets edit` — opens decrypted YAML in
   `$EDITOR`, re-encrypts on save (mirrors `ansible-vault edit` UX).
3. **`ansible-vault` directly:** the file format is identical, so
   `ansible-vault edit secrets/voice-forge.vault --vault-password-file
   ~/.voice-forge/vault_pass` works too.

## Rotation

`voice-forge-secrets rotate` prompts for a new password, re-encrypts
the vault under it, and updates the password file (unless
`--no-update-password-file`). The old password must still be valid
to read the current contents — there's no recovery for forgotten
passwords. This is a feature.

## What if I lose the password?

The contents are unrecoverable. By design — that's what AES-256
buys you. Restore from your secret manager / sticky note / password
manager, or re-issue all the credentials in the vault and
`voice-forge-secrets init --force` to start fresh.

## Why Ansible Vault format specifically?

- **Format stability.** Ansible Vault 1.1 hasn't changed since 2015.
  Files written today will decrypt fine in 5 years.
- **Interop.** Existing `ansible-vault` tooling works on our files;
  our tooling works on Ansible Vault files. No lock-in.
- **Battle tested.** This format protects production secrets at a
  scale our code never will.

We're NOT inheriting the rest of Ansible (its Jinja templating, its
inventory model, its YAML quirks). Just the file format.

## What we did NOT build

- Vault-id support (the `1.2` format variant with named vault IDs).
  Multi-tenant secret store territory; voice-forge doesn't need it.
- Network-fetched secrets (AWS Secrets Manager, Vault by HashiCorp,
  etc.). Easy to add a resolution-chain layer; not needed today.
- Per-secret access logging. Add if a compliance need arises.
- Automated rotation against the upstream API. ElevenLabs has no API
  for "rotate my API key"; rotation is manual + out-of-band.
