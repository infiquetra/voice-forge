"""U5 — persona bind endpoints: PUT /voices/{id}/persona, GET /v1/personas,
and the create-time persona setter on POST /voices/{id}.

The design->bind->serve back half: binding becomes a first-class API action, a
voice can be born bound, and personas are listable. Registry is isolated to a
tmp dir via VOICE_FORGE_REGISTRY (resolved per-request, so env set before the
call wins even though the app is already imported).
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


def test_create_with_persona_is_born_bound(client: TestClient, tmp_path: Path) -> None:
    r = _create(client, tmp_path, "narrator-f5", persona="Athena")
    assert r.status_code == 201, r.text
    assert r.json()["persona"] == "Athena"
    assert client.get("/voices/narrator-f5").json()["persona"] == "Athena"


def test_put_binds_and_roundtrips(client: TestClient, tmp_path: Path) -> None:
    _create(client, tmp_path, "narrator-f5")
    r = client.put("/voices/narrator-f5/persona", json={"persona": "Hera"})
    assert r.status_code == 200
    assert r.json()["persona"] == "Hera"
    assert client.get("/voices/narrator-f5").json()["persona"] == "Hera"


def test_rebind_overwrites(client: TestClient, tmp_path: Path) -> None:
    _create(client, tmp_path, "narrator-f5", persona="Hera")
    client.put("/voices/narrator-f5/persona", json={"persona": "Eir"})
    assert client.get("/voices/narrator-f5").json()["persona"] == "Eir"


def test_clear_binding_reverts_to_derived(client: TestClient, tmp_path: Path) -> None:
    _create(client, tmp_path, "saga-comms-f5", persona="Custom")
    client.put("/voices/saga-comms-f5/persona", json={"persona": None})
    assert client.get("/voices/saga-comms-f5").json()["persona"] == "saga-comms"


def test_list_personas_groups_voices(client: TestClient, tmp_path: Path) -> None:
    _create(client, tmp_path, "narrator-f5", persona="Hera")
    groups = client.get("/v1/personas").json()["personas"]
    assert any(g["persona"] == "Hera" and "narrator-f5" in g["voices"] for g in groups)


def test_bind_missing_voice_404(client: TestClient) -> None:
    assert client.put("/voices/nope/persona", json={"persona": "X"}).status_code == 404
