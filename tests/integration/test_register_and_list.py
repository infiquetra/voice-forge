"""Integration tests for voice registration + listing via the HTTP API."""

import io

from fastapi.testclient import TestClient


def _make_tiny_wav() -> bytes:
    import wave

    buf = io.BytesIO()
    with wave.open(buf, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(24000)
        f.writeframes(b"\x00" * 2400)  # 0.05s silence
    return buf.getvalue()


def test_register_voice_with_explicit_ref_text(tmp_registry):
    from voice_forge.server import app

    client = TestClient(app)
    wav = _make_tiny_wav()
    r = client.post(
        "/voices/alice",
        files={"ref_audio": ("ref.wav", wav, "audio/wav")},
        data={
            "ref_text": "Hello world.",
            "backend": "neutts",
            "language": "en",
            "description": "test voice",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["id"] == "alice"
    assert body["backend"] == "neutts"
    assert body["language"] == "en"

    # Now /voices/alice should return same metadata
    r2 = client.get("/voices/alice")
    assert r2.status_code == 200
    assert r2.json()["id"] == "alice"

    # And the list endpoint includes it
    r3 = client.get("/v1/audio/voices")
    voices = r3.json()["data"]
    assert any(v["id"] == "alice" for v in voices)


def test_register_duplicate_voice_returns_409(tmp_registry):
    from voice_forge.server import app

    client = TestClient(app)
    wav = _make_tiny_wav()
    client.post(
        "/voices/bob",
        files={"ref_audio": ("ref.wav", wav, "audio/wav")},
        data={"ref_text": "hi", "backend": "neutts"},
    )
    r = client.post(
        "/voices/bob",
        files={"ref_audio": ("ref.wav", wav, "audio/wav")},
        data={"ref_text": "hi again", "backend": "neutts"},
    )
    assert r.status_code == 409
