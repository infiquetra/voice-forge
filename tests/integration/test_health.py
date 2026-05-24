"""Integration test for the /health endpoint."""

from fastapi.testclient import TestClient


def test_health_returns_ok(tmp_registry):
    from voice_forge.server import app

    client = TestClient(app)
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert "version" in body
    assert "voices_count" in body
    assert body["voices_count"] == 0


def test_list_voices_empty_registry(tmp_registry):
    from voice_forge.server import app

    client = TestClient(app)
    r = client.get("/v1/audio/voices")
    assert r.status_code == 200
    assert r.json() == {"data": []}


def test_get_missing_voice_returns_404(tmp_registry):
    from voice_forge.server import app

    client = TestClient(app)
    r = client.get("/voices/nothere")
    assert r.status_code == 404


def test_delete_missing_voice_is_idempotent(tmp_registry):
    from voice_forge.server import app

    client = TestClient(app)
    r = client.delete("/voices/nothere")
    assert r.status_code == 204


def test_synth_missing_voice_returns_404(tmp_registry):
    from voice_forge.server import app

    client = TestClient(app)
    r = client.post(
        "/v1/audio/speech",
        json={"input": "hello", "voice": "nothere"},
    )
    assert r.status_code == 404
