"""Subprocess-isolated backend pattern.

A reusable base class for backends whose Python dependency closure cannot
coexist with the main voice-forge process — typically because they pin
torch / transformers / numpy to versions that clash with what other
backends (or voice-forge itself) require. The classic offenders are
Chatterbox (``torch==2.6.0`` + ``transformers==5.2.0`` exact pins) and
anything GPL-licensed where we want a hard process boundary for
distribution hygiene (Piper).

How it works
============

Each subprocess-isolated backend ships its own ``[name]`` extra in
``pyproject.toml`` that installs **into a dedicated per-backend venv** at
``~/.voice-forge/backends/<name>/.venv/`` — NOT into voice-forge's main
venv. Provisioning is a separate CLI command::

    voice-forge backend install <name>

That command:

1. Creates the per-backend venv under
   ``~/.voice-forge/backends/<name>/``.
2. Installs ``voice-forge-tts[name,subprocess-shim]`` into it. The
   ``subprocess-shim`` extra carries the tiny FastAPI server that
   responds to voice-forge's IPC calls.
3. Records the venv path in ``~/.voice-forge/backends/<name>/state.json``
   so the parent process can find + spawn it.

At runtime, ``SubprocessBackend.load()``:

1. Looks up the venv path.
2. Spawns ``<venv>/bin/voice-forge-backend-shim <name> --port <random>``
   as a child process.
3. Polls the child's ``/health`` until it responds.
4. Keeps the child alive for the process lifetime of the parent;
   ``synthesize()`` and ``synthesize_stream()`` POST to the child over
   localhost HTTP.

If the child dies unexpectedly, the next call attempts one restart. A
second failure raises ``RuntimeError`` — backends shouldn't crash twice
in a row in normal operation.

IPC protocol
============

Wire format mirrors voice-forge's own REST API so the shim is trivial to
implement::

    POST http://127.0.0.1:<child_port>/synth
      body: {"text": "...", "ref": {"voice_id": "...", ...VoiceRef fields...}}
      response: streaming float32-LE PCM (chunked transfer-encoding)

    GET  http://127.0.0.1:<child_port>/health
      response: {"loaded": true, "model": "...", ...}

The shim itself lives in ``voice_forge.subprocess_shim`` (a separate
module installed into both the parent and child venvs).

Cost
====

- Cold start: ~3-5s additional latency on the FIRST call (shim subprocess
  spawn + child's model warmup). Subsequent calls reuse the running
  child.
- Per-call: ~50-100ms IPC overhead over plain in-process. Negligible vs
  synth time.
- Memory: each subprocess backend's resident set is INDEPENDENT of the
  parent — adding Chatterbox doesn't bloat voice-forge's main process.
- Crash isolation: a malformed model output that segfaults the shim
  doesn't take down the parent.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import subprocess
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np

from . import VoiceRef

logger = logging.getLogger("voice_forge.backends._subprocess")

DEFAULT_BACKEND_ROOT = Path("~/.voice-forge/backends").expanduser()
SHIM_BIND_HOST = "127.0.0.1"
HEALTH_POLL_TIMEOUT_SEC = 60.0  # shim cold-start can take 30-45s on first run
HEALTH_POLL_INTERVAL_SEC = 0.5


def _pick_free_port() -> int:
    """Get an unused localhost port by binding-and-releasing."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((SHIM_BIND_HOST, 0))
        return int(s.getsockname()[1])


def _backend_venv_path(backend_name: str, root: Path | None = None) -> Path:
    """Resolve the per-backend venv directory."""
    return (root or DEFAULT_BACKEND_ROOT) / backend_name / ".venv"


def _backend_state_path(backend_name: str, root: Path | None = None) -> Path:
    """Resolve the per-backend provisioning-state file."""
    return (root or DEFAULT_BACKEND_ROOT) / backend_name / "state.json"


class SubprocessBackendNotInstalled(RuntimeError):
    """The per-backend venv hasn't been provisioned yet.

    Raised by ``SubprocessBackend.load()`` when the venv path is missing
    or the state file is malformed. The fix is one CLI invocation::

        voice-forge backend install <name>
    """


class SubprocessBackend:
    """Base class for backends that run in a dedicated subprocess.

    Concrete subclasses set ``name`` and ``KNOWN_TUNABLES``. The default
    ``load() / synthesize() / synthesize_stream()`` implementations
    drive the HTTP-shim IPC protocol.

    Subclasses may override ``_build_request_payload()`` if the wire
    contract for their child shim differs from the default.
    """

    name: str = "subprocess-base"
    KNOWN_TUNABLES: dict = {}

    def __init__(self) -> None:
        self._proc: subprocess.Popen[bytes] | None = None
        self._port: int | None = None
        self._restart_attempts = 0

    # ----- TTSBackend Protocol -----

    def load(self, config: dict) -> None:
        """Spawn the child shim + wait for its health endpoint."""
        backends_root = Path(config.get("backends_root") or DEFAULT_BACKEND_ROOT).expanduser()
        venv_path = _backend_venv_path(self.name, backends_root)
        state_path = _backend_state_path(self.name, backends_root)
        if not venv_path.is_dir() or not state_path.is_file():
            raise SubprocessBackendNotInstalled(
                f"backend {self.name!r} not provisioned at {venv_path.parent}. "
                f"Run: voice-forge backend install {self.name}"
            )
        try:
            state = json.loads(state_path.read_text())
        except json.JSONDecodeError as exc:
            raise SubprocessBackendNotInstalled(
                f"backend {self.name!r}: corrupted state.json at {state_path} ({exc})"
            ) from exc
        shim_entry = state.get("shim_entry")
        if not shim_entry:
            raise SubprocessBackendNotInstalled(
                f"backend {self.name!r}: state.json missing 'shim_entry' key"
            )
        self._spawn_child(shim_entry, venv_path, config)

    def _spawn_child(self, shim_entry: str, venv_path: Path, config: dict) -> None:
        port = _pick_free_port()
        shim_bin = venv_path / "bin" / shim_entry
        if not shim_bin.is_file():
            raise SubprocessBackendNotInstalled(
                f"backend {self.name!r}: shim entrypoint {shim_bin} not found"
            )
        cmd = [
            str(shim_bin),
            self.name,
            "--host",
            SHIM_BIND_HOST,
            "--port",
            str(port),
        ]
        # Extra config keys flow to the child via env (simpler than
        # rebuilding a config-CLI for every backend).
        env = os.environ.copy()
        for k, v in (config or {}).items():
            if k != "backends_root" and isinstance(v, str | int | float | bool):
                env[f"VOICE_FORGE_BACKEND_CONFIG_{k.upper()}"] = str(v)
        logger.info("[%s] spawning shim: %s", self.name, " ".join(cmd))
        self._proc = subprocess.Popen(  # noqa: S603 — cmd is constructed from known paths
            cmd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self._port = port
        self._wait_for_health()

    def _wait_for_health(self) -> None:
        deadline = time.monotonic() + HEALTH_POLL_TIMEOUT_SEC
        last_err: Exception | None = None
        while time.monotonic() < deadline:
            if self._proc is not None and self._proc.poll() is not None:
                # Child died before becoming healthy — surface the stderr.
                stderr = b""
                if self._proc.stderr:
                    stderr = self._proc.stderr.read()
                raise RuntimeError(
                    f"[{self.name}] shim exited before healthy "
                    f"(rc={self._proc.returncode}); stderr={stderr.decode(errors='replace')[:500]}"
                )
            try:
                req = urllib.request.Request(f"http://{SHIM_BIND_HOST}:{self._port}/health")
                with urllib.request.urlopen(req, timeout=2) as resp:  # nosec B310 — localhost only
                    if resp.status == 200:
                        return
            except (urllib.error.URLError, ConnectionRefusedError, OSError) as exc:
                last_err = exc
            time.sleep(HEALTH_POLL_INTERVAL_SEC)
        raise RuntimeError(
            f"[{self.name}] shim never became healthy on port {self._port} "
            f"after {HEALTH_POLL_TIMEOUT_SEC}s (last error: {last_err!r})"
        )

    def encode_reference(self, _ref_audio_path: str) -> list | None:
        # Subprocess shims don't expose pre-encode (the round-trip would
        # double IPC overhead for no benefit). Encoding happens inside
        # synthesize() in the child.
        return None

    def synthesize(self, text: str, ref: VoiceRef) -> np.ndarray:
        """Batch synth: POST to the child + collect the full PCM body."""
        chunks: list[np.ndarray] = []
        for chunk in self.synthesize_stream(text, ref):
            chunks.append(chunk)
        if not chunks:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(chunks) if len(chunks) > 1 else chunks[0]

    def synthesize_stream(self, text: str, ref: VoiceRef) -> Iterator[np.ndarray]:
        """Stream synth: POST + read chunked PCM bytes from the child."""
        if self._port is None:
            raise RuntimeError(f"[{self.name}] backend not loaded")
        payload = self._build_request_payload(text, ref)
        body = json.dumps(payload).encode()
        req = urllib.request.Request(
            f"http://{SHIM_BIND_HOST}:{self._port}/synth",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=600) as resp:  # nosec B310 — localhost
                pcm_buffer = b""
                while True:
                    buf = resp.read(8192)
                    if not buf:
                        break
                    pcm_buffer += buf
                    # Float32 frames must be 4-byte aligned; drain whole frames only.
                    frame_bytes = len(pcm_buffer) - (len(pcm_buffer) % 4)
                    if frame_bytes:
                        yield np.frombuffer(pcm_buffer[:frame_bytes], dtype=np.float32)
                        pcm_buffer = pcm_buffer[frame_bytes:]
                if pcm_buffer:
                    # Tail bytes that didn't fill a complete float — discard
                    # rather than crash. Should never happen on a healthy shim.
                    logger.warning(
                        "[%s] discarding %d trailing bytes from shim response",
                        self.name,
                        len(pcm_buffer),
                    )
        except (urllib.error.URLError, urllib.error.HTTPError) as exc:
            raise RuntimeError(f"[{self.name}] shim call failed: {exc!r}") from exc

    def _build_request_payload(self, text: str, ref: VoiceRef) -> dict:
        """Default payload — subclasses override only if their shim differs."""
        return {
            "text": text,
            "ref": {
                "voice_id": ref.voice_id,
                "ref_audio_path": ref.ref_audio_path,
                "ref_text": ref.ref_text,
                "preset_id": ref.preset_id,
                "metadata": ref.metadata,
            },
        }

    def health(self) -> dict:
        """Return diagnostics. Calls the child shim's /health endpoint."""
        info: dict[str, Any] = {
            "name": self.name,
            "loaded": self._port is not None and self._proc is not None,
            "shim_port": self._port,
        }
        if self._port is None:
            return info
        try:
            req = urllib.request.Request(f"http://{SHIM_BIND_HOST}:{self._port}/health")
            with urllib.request.urlopen(req, timeout=2) as resp:  # nosec B310 — localhost
                child_health = json.loads(resp.read())
            info["child"] = child_health
        except (urllib.error.URLError, json.JSONDecodeError) as exc:
            info["child_error"] = repr(exc)
        return info

    def shutdown(self) -> None:
        """Best-effort kill of the child shim. Idempotent."""
        if self._proc is None:
            return
        try:
            self._proc.terminate()
            self._proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._proc.kill()
            self._proc.wait()
        except ProcessLookupError:
            pass
        self._proc = None
        self._port = None
