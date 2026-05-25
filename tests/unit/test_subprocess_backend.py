"""Unit tests for SubprocessBackend using a real-but-fake child shim.

Strategy: instead of mocking out subprocess/urllib (which would leave the
actual lifecycle code untested), we spawn a TINY Python HTTP server as the
"child shim" via the standard library's http.server. It speaks the contract
SubprocessBackend expects (/health + /synth POST returning PCM bytes), but
backs onto a no-op fake synth that returns 0.5s of silence. This exercises
the real spawn / poll-for-health / IPC / shutdown code path end-to-end.
"""

from __future__ import annotations

import json
import stat
import textwrap

import numpy as np
import pytest

from voice_forge.backends import VoiceRef
from voice_forge.backends._subprocess import (
    SubprocessBackend,
    SubprocessBackendNotInstalled,
)


# The fake shim script. Written to a temp dir + chmod'd executable + invoked
# directly by SubprocessBackend's _spawn_child(). This is what would normally
# be `voice-forge-backend-shim` installed in the per-backend venv.
_FAKE_SHIM_SCRIPT = textwrap.dedent(
    """\
    #!/usr/bin/env python3
    import argparse
    import http.server
    import json
    import numpy as np

    parser = argparse.ArgumentParser()
    parser.add_argument("backend_name")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()


    class ShimHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/health":
                body = json.dumps({"loaded": True, "model": "fake-model"}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_response(404)
                self.end_headers()

        def do_POST(self):
            if self.path == "/synth":
                length = int(self.headers.get("Content-Length", "0"))
                _ = self.rfile.read(length)
                pcm = np.zeros(12_000, dtype=np.float32).tobytes()
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Length", str(len(pcm)))
                self.end_headers()
                self.wfile.write(pcm)
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, *_args, **_kwargs):
            pass


    server = http.server.HTTPServer((args.host, args.port), ShimHandler)
    server.serve_forever()
    """
)


class FakeSubprocessBackend(SubprocessBackend):
    name = "fake-subproc"
    KNOWN_TUNABLES: dict = {}


@pytest.fixture
def provisioned_backend_root(tmp_path):
    """Create a fake provisioned per-backend layout with the fake shim installed."""
    backend_root = tmp_path / "backends"
    venv_bin = backend_root / "fake-subproc" / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    shim_path = venv_bin / "voice-forge-backend-shim"
    shim_path.write_text(_FAKE_SHIM_SCRIPT)
    shim_path.chmod(shim_path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    state_path = backend_root / "fake-subproc" / "state.json"
    state_path.write_text(json.dumps({"shim_entry": "voice-forge-backend-shim"}))
    return backend_root


def _voice_ref(**overrides):
    defaults = dict(
        voice_id="fake-voice",
        backend="fake-subproc",
        ref_audio_path=None,
        ref_text=None,
        preset_id=None,
        metadata={"language": "en"},
    )
    defaults.update(overrides)
    return VoiceRef(**defaults)


def test_load_raises_when_venv_missing(tmp_path):
    backend = FakeSubprocessBackend()
    with pytest.raises(SubprocessBackendNotInstalled, match="not provisioned"):
        backend.load({"backends_root": str(tmp_path / "nonexistent")})


def test_load_raises_when_state_json_missing(tmp_path):
    """Venv exists but state.json doesn't — provisioning was incomplete."""
    venv_bin = tmp_path / "backends" / "fake-subproc" / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    backend = FakeSubprocessBackend()
    with pytest.raises(SubprocessBackendNotInstalled, match="not provisioned"):
        backend.load({"backends_root": str(tmp_path / "backends")})


def test_load_raises_when_state_json_corrupted(tmp_path):
    backend_root = tmp_path / "backends"
    venv_bin = backend_root / "fake-subproc" / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    (backend_root / "fake-subproc" / "state.json").write_text("{ not valid json")
    backend = FakeSubprocessBackend()
    with pytest.raises(SubprocessBackendNotInstalled, match="corrupted state"):
        backend.load({"backends_root": str(backend_root)})


def test_load_raises_when_shim_entry_not_executable(tmp_path):
    backend_root = tmp_path / "backends"
    venv_bin = backend_root / "fake-subproc" / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    state_path = backend_root / "fake-subproc" / "state.json"
    state_path.write_text(json.dumps({"shim_entry": "voice-forge-backend-shim"}))
    backend = FakeSubprocessBackend()
    with pytest.raises(SubprocessBackendNotInstalled, match="shim entrypoint"):
        backend.load({"backends_root": str(backend_root)})


def test_load_succeeds_with_provisioned_layout(provisioned_backend_root):
    backend = FakeSubprocessBackend()
    backend.load({"backends_root": str(provisioned_backend_root)})
    try:
        h = backend.health()
        assert h["name"] == "fake-subproc"
        assert h["loaded"] is True
        assert h["shim_port"] is not None
        assert h["child"]["loaded"] is True
        assert h["child"]["model"] == "fake-model"
    finally:
        backend.shutdown()


def test_synthesize_round_trips_pcm(provisioned_backend_root):
    backend = FakeSubprocessBackend()
    backend.load({"backends_root": str(provisioned_backend_root)})
    try:
        audio = backend.synthesize("hello world", _voice_ref())
        assert isinstance(audio, np.ndarray)
        assert audio.dtype == np.float32
        assert len(audio) == 12_000
        assert np.all(audio == 0.0)
    finally:
        backend.shutdown()


def test_synthesize_stream_yields_pcm_chunks(provisioned_backend_root):
    backend = FakeSubprocessBackend()
    backend.load({"backends_root": str(provisioned_backend_root)})
    try:
        total_samples = 0
        for chunk in backend.synthesize_stream("hello", _voice_ref()):
            assert chunk.dtype == np.float32
            total_samples += len(chunk)
        assert total_samples == 12_000
    finally:
        backend.shutdown()


def test_shutdown_is_idempotent(provisioned_backend_root):
    backend = FakeSubprocessBackend()
    backend.load({"backends_root": str(provisioned_backend_root)})
    backend.shutdown()
    backend.shutdown()


def test_synthesize_without_load_raises():
    backend = FakeSubprocessBackend()
    with pytest.raises(RuntimeError, match="not loaded"):
        backend.synthesize("text", _voice_ref())


def test_two_concurrent_backends_get_different_ports(provisioned_backend_root):
    """Two SubprocessBackend instances must not collide on the same port."""
    b1 = FakeSubprocessBackend()
    b2 = FakeSubprocessBackend()
    b1.load({"backends_root": str(provisioned_backend_root)})
    try:
        b2.load({"backends_root": str(provisioned_backend_root)})
        try:
            assert b1._port != b2._port
        finally:
            b2.shutdown()
    finally:
        b1.shutdown()
