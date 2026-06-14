"""U6 — per-voice backend override route: PUT /voices/{id}/backend.

The clone-create back half: a registered voice's backend becomes a first-class,
in-place edit (metadata-only) instead of a re-register-with-ref-audio round trip.
Registry is isolated to a tmp dir via VOICE_FORGE_REGISTRY (resolved per-request).

``higgs`` is a member of known_backends() even when its extra isn't installed, so
the 200 path passes in CI — the override is a metadata edit, not a backend load
(mirrors test_persona_bind using backend "f5" without f5 being importable).
Validation order: 400 (unknown backend) takes precedence over 404 (missing voice).
"""

from __future__ import annotations

import struct
import wave
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from voice_forge.server import app  # noqa: E402


def _dummy_wav(path: Path) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(struct.pack("<" + "h" * 100, *([0] * 100)))


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("VOICE_FORGE_REGISTRY", str(tmp_path / "reg"))
    return TestClient(app)


def _create(client: TestClient, tmp_path: Path, voice_id: str, **data: str):
    wav = tmp_path / "ref.wav"
    _dummy_wav(wav)
    with open(wav, "rb") as f:
        return client.post(
            f"/voices/{voice_id}",
            files={"ref_audio": ("ref.wav", f, "audio/wav")},
            data={"ref_text": "hello", "backend": "f5", **data},
        )


def test_put_backend_overrides_and_roundtrips(client: TestClient, tmp_path: Path) -> None:
    _create(client, tmp_path, "narrator-f5")  # born on f5
    r = client.put("/voices/narrator-f5/backend", json={"backend": "higgs"})
    assert r.status_code == 200, r.text
    assert r.json()["backend"] == "higgs"
    assert client.get("/voices/narrator-f5").json()["backend"] == "higgs"


def test_put_backend_preserves_persona(client: TestClient, tmp_path: Path) -> None:
    _create(client, tmp_path, "narrator-f5", persona="Hera")
    client.put("/voices/narrator-f5/backend", json={"backend": "neutts"})
    body = client.get("/voices/narrator-f5").json()
    assert body["backend"] == "neutts"
    assert body["persona"] == "Hera"  # not clobbered by the backend edit


def test_put_backend_missing_voice_404(client: TestClient) -> None:
    r = client.put("/voices/nope/backend", json={"backend": "higgs"})
    assert r.status_code == 404


def test_put_backend_unknown_backend_400(client: TestClient, tmp_path: Path) -> None:
    _create(client, tmp_path, "narrator-f5")
    r = client.put("/voices/narrator-f5/backend", json={"backend": "not-a-backend"})
    assert r.status_code == 400


def test_put_backend_400_precedes_404(client: TestClient) -> None:
    # bad backend on a missing voice -> 400 (payload rejected before state lookup)
    r = client.put("/voices/also-missing/backend", json={"backend": "not-a-backend"})
    assert r.status_code == 400
