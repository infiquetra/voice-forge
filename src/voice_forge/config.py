"""Runtime-mutable voice-forge configuration (default backend, etc).

A small file at ``~/.voice-forge/config.json`` that survives process restarts.
The single decision this currently persists is ``default_backend`` — which
backend new voices use when their metadata.json doesn't specify one, and
what the CLI / REST surfaces fall back to when no explicit ``--backend``
flag is passed.

Why a config FILE instead of an env var: we want it mutable at runtime via
``PUT /v1/backends/default`` without forcing the user to edit shell rc files
or restart processes.

Why JSON instead of TOML: the registry already speaks JSON (every voice's
metadata.json), so the dep is zero. Mistypes are caught at read time.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path

logger = logging.getLogger("voice_forge.config")

# F5-TTS is the default per DECISIONS 2026-05-25.
HARDCODED_FALLBACK_BACKEND = "f5"

# Single source of truth for where the config file lives. Mirrors the
# registry's VOICE_FORGE_REGISTRY env knob so tests can sandbox both.
_CONFIG_DIR_ENV = "VOICE_FORGE_CONFIG_DIR"
_DEFAULT_CONFIG_DIR = "~/.voice-forge"


def _config_path() -> Path:
    base = Path(os.environ.get(_CONFIG_DIR_ENV, _DEFAULT_CONFIG_DIR)).expanduser()
    return base / "config.json"


# Serialize writes; concurrent PUT /v1/backends/default calls would otherwise
# race on the json.load/dump cycle.
_WRITE_LOCK = threading.Lock()


def get_default_backend() -> str:
    """Return the currently-configured default backend.

    Falls back to ``HARDCODED_FALLBACK_BACKEND`` (``"f5"``) when:
        - the config file doesn't exist yet (first run on a fresh install)
        - the file is corrupted (malformed JSON)
        - the ``default_backend`` key is missing or non-string

    These are all "treat as fresh install" cases — the operator can still
    flip the default via ``PUT /v1/backends/default``.
    """
    path = _config_path()
    if not path.is_file():
        return HARDCODED_FALLBACK_BACKEND
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("config file at %s unreadable (%s); using fallback", path, exc)
        return HARDCODED_FALLBACK_BACKEND
    value = data.get("default_backend")
    if not isinstance(value, str) or not value:
        return HARDCODED_FALLBACK_BACKEND
    return value


def set_default_backend(name: str) -> str:
    """Persist a new default-backend choice. Returns the value actually written.

    Creates the config directory + file if absent. Threadsafe via _WRITE_LOCK.
    Does NOT validate that ``name`` is a known backend — callers should do
    that check before calling (the REST endpoint validates against
    ``known_backends()``).
    """
    if not name or not isinstance(name, str):
        raise ValueError(f"default backend must be a non-empty string, got {name!r}")
    with _WRITE_LOCK:
        path = _config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        # Preserve any other top-level config keys we add in the future.
        data: dict = {}
        if path.is_file():
            try:
                data = json.loads(path.read_text())
                if not isinstance(data, dict):
                    data = {}
            except (json.JSONDecodeError, OSError):
                data = {}
        data["default_backend"] = name
        path.write_text(json.dumps(data, indent=2, sort_keys=True))
    logger.info("default backend set to %r", name)
    return name
