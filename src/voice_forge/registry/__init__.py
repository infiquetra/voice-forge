"""FS-backed voice registry.

Each voice lives at ``$VOICE_FORGE_REGISTRY/<voice_id>/`` (default
``~/.voice-forge/voices/<voice_id>/``) with three files:

- ``ref.wav``      reference audio for cloning backends (absent for preset-voice backends)
- ``ref.txt``      matching transcript (absent for preset-voice backends)
- ``metadata.json`` ``{"backend": "...", "model": "...", "language": "...", ...}``
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from ..backends import VoiceRef

DEFAULT_REGISTRY_PATH = "~/.voice-forge/voices"


def _resolve_default_root() -> Path:
    """Resolve registry root at call time (not import time) so VOICE_FORGE_REGISTRY env
    changes are picked up by every Registry() call."""
    return Path(os.environ.get("VOICE_FORGE_REGISTRY", DEFAULT_REGISTRY_PATH)).expanduser()


def _voice_dir(root: Path, voice_id: str) -> Path:
    """Per-voice directory inside the registry root."""
    return root / voice_id


def _derive_persona(voice_id: str, backend: str, known_backends: tuple[str, ...]) -> str:
    """Fallback persona derivation when metadata doesn't carry one.

    Strips a trailing ``-<backend>`` suffix where backend is in the
    closed set we know about. Anything else returns voice_id verbatim.
    Example: ``saga-comms-f5`` → ``saga-comms`` (one persona, two backend
    rows). ``kokoro-bella`` stays as ``kokoro-bella`` since no known
    backend suffix matches.
    """
    for known in known_backends:
        suffix = f"-{known}"
        if voice_id.endswith(suffix):
            return voice_id[: -len(suffix)]
    return voice_id


_KNOWN_BACKEND_NAMES = (
    "f5",
    "neutts",
    "kokoro",
    "xtts",
    "dia",
    "piper",
    "chatterbox",
    "melotts",
    "kitten",
    "fast",  # nfe_step=16 variants are tagged "-fast" but share the parent persona
)


def _load_voice(voice_dir: Path) -> VoiceRef:
    """Read metadata.json + assemble a VoiceRef for one voice directory."""
    meta_path = voice_dir / "metadata.json"
    if not meta_path.exists():
        raise FileNotFoundError(f"missing metadata.json in {voice_dir}")
    meta = json.loads(meta_path.read_text())
    voice_id = meta.get("voice_id", voice_dir.name)
    # Default per DECISIONS 2026-05-25 was F5; the runtime-configured
    # default (via PUT /v1/backends/default → ~/.voice-forge/config.json)
    # overrides it. Legacy metadata.json files without an explicit backend
    # field route to the configured default.
    from voice_forge.config import get_default_backend

    backend = meta.get("backend", get_default_backend())
    ref_wav = voice_dir / "ref.wav"
    ref_txt = voice_dir / "ref.txt"
    ref_text = ref_txt.read_text().strip() if ref_txt.exists() else None
    explicit_persona = meta.get("persona")
    persona = explicit_persona or _derive_persona(voice_id, backend, _KNOWN_BACKEND_NAMES)
    return VoiceRef(
        voice_id=voice_id,
        backend=backend,
        ref_audio_path=str(ref_wav) if ref_wav.exists() else None,
        ref_text=ref_text,
        preset_id=meta.get("preset_id"),
        metadata=meta,
        persona=persona,
    )


class Registry:
    """FS-backed voice registry. CRUD against the on-disk directory tree."""

    def __init__(self, root: Path | str | None = None) -> None:
        if root is None:
            root = _resolve_default_root()
        self.root = Path(root).expanduser()
        self.root.mkdir(parents=True, exist_ok=True)

    def list(self) -> list[VoiceRef]:
        """Return all registered voices, sorted by voice_id."""
        voices = []
        for entry in sorted(self.root.iterdir()):
            if entry.is_dir() and (entry / "metadata.json").exists():
                try:
                    voices.append(_load_voice(entry))
                except (json.JSONDecodeError, FileNotFoundError):
                    # Skip malformed entries silently; caller can inspect FS
                    continue
        return voices

    def get(self, voice_id: str) -> VoiceRef:
        """Look up a voice. Raises KeyError if not found."""
        voice_dir = _voice_dir(self.root, voice_id)
        if not voice_dir.exists():
            raise KeyError(f"voice not in registry: {voice_id!r}")
        return _load_voice(voice_dir)

    def register(
        self,
        voice_id: str,
        ref_audio_path: str | os.PathLike | None,
        ref_text: str | None,
        backend: str,
        metadata: dict | None = None,
        *,
        overwrite: bool = False,
    ) -> VoiceRef:
        """Add a new voice. Copies ref_audio into the registry dir.

        Set ``overwrite=True`` to replace an existing voice with the same id.
        """
        voice_dir = _voice_dir(self.root, voice_id)
        if voice_dir.exists() and not overwrite:
            raise FileExistsError(f"voice already registered: {voice_id!r}")
        voice_dir.mkdir(parents=True, exist_ok=True)

        meta = dict(metadata or {})
        meta.setdefault("voice_id", voice_id)
        meta["backend"] = backend

        if ref_audio_path is not None:
            ref_audio_src = Path(ref_audio_path).expanduser()
            if not ref_audio_src.exists():
                raise FileNotFoundError(f"ref_audio_path not found: {ref_audio_src}")
            shutil.copy2(ref_audio_src, voice_dir / "ref.wav")
        if ref_text is not None:
            (voice_dir / "ref.txt").write_text(ref_text.strip() + "\n")
        (voice_dir / "metadata.json").write_text(json.dumps(meta, indent=2, sort_keys=True))
        return _load_voice(voice_dir)

    def delete(self, voice_id: str) -> None:
        """Remove a voice. Idempotent (no error if missing)."""
        voice_dir = _voice_dir(self.root, voice_id)
        if voice_dir.exists():
            shutil.rmtree(voice_dir)

    def exists(self, voice_id: str) -> bool:
        return _voice_dir(self.root, voice_id).exists()

    def tune(
        self,
        voice_id: str,
        sampling_overrides: dict | None = None,
        *,
        clear: bool = False,
    ) -> VoiceRef:
        """Update the ``sampling`` block of a voice's metadata.json.

        Args:
            voice_id: existing voice to tune. Raises KeyError if missing.
            sampling_overrides: keys to set or update inside ``metadata['sampling']``.
                Existing keys are preserved unless explicitly overwritten here.
            clear: if True, remove the ``sampling`` block entirely. Takes precedence
                over ``sampling_overrides`` for the same call.

        Returns the refreshed VoiceRef.
        """
        voice_dir = _voice_dir(self.root, voice_id)
        if not voice_dir.exists():
            raise KeyError(f"voice not in registry: {voice_id!r}")
        meta_path = voice_dir / "metadata.json"
        meta = json.loads(meta_path.read_text())
        if clear:
            meta.pop("sampling", None)
        elif sampling_overrides:
            existing = dict(meta.get("sampling") or {})
            existing.update(sampling_overrides)
            meta["sampling"] = existing
        meta_path.write_text(json.dumps(meta, indent=2, sort_keys=True))
        return _load_voice(voice_dir)

    def set_persona(self, voice_id: str, persona: str | None) -> VoiceRef:
        """Bind a voice to a persona (1:1) by writing ``metadata['persona']``.

        Mirrors :meth:`tune`'s metadata-block write. ``persona=None`` (or empty)
        clears the *explicit* binding, reverting to the derived persona
        (:func:`_derive_persona`) — so the existing fleet's derived personas are
        never disturbed; only the explicit override is added or removed.

        Raises KeyError if the voice is missing.
        """
        voice_dir = _voice_dir(self.root, voice_id)
        if not voice_dir.exists():
            raise KeyError(f"voice not in registry: {voice_id!r}")
        meta_path = voice_dir / "metadata.json"
        meta = json.loads(meta_path.read_text())
        if persona:
            meta["persona"] = persona
        else:
            meta.pop("persona", None)
        meta_path.write_text(json.dumps(meta, indent=2, sort_keys=True))
        return _load_voice(voice_dir)

    def set_backend(self, voice_id: str, backend: str) -> VoiceRef:
        """Change a registered voice's backend in place (metadata-only edit).

        Mirrors :meth:`set_persona`: rewrites ``metadata['backend']`` and nothing
        else — ref.wav, ref.txt, persona, and the sampling block are untouched.
        Does NOT validate that ``backend`` is known/installed; the REST layer
        validates against ``known_backends()`` before calling (parallel to
        set_default_backend's contract).

        Raises KeyError if the voice is missing. Raises ValueError on empty backend.
        """
        if not backend or not isinstance(backend, str):
            raise ValueError(f"backend must be a non-empty string, got {backend!r}")
        voice_dir = _voice_dir(self.root, voice_id)
        if not voice_dir.exists():
            raise KeyError(f"voice not in registry: {voice_id!r}")
        meta_path = voice_dir / "metadata.json"
        meta = json.loads(meta_path.read_text())
        meta["backend"] = backend
        meta_path.write_text(json.dumps(meta, indent=2, sort_keys=True))
        return _load_voice(voice_dir)
