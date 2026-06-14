"""The Forge — POST /v1/forge/design (freeform description → preview candidates).

Full coverage with zero network and zero API key: ``create_voice_previews`` is
monkeypatched at its source module so the endpoint's deferred import picks up the
fake. The two gating tests prove the no-key path returns a clean 503 (NOT a 500
leaking the elevenlabs module's RuntimeError).
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from voice_forge.server import app  # noqa: E402
from voice_forge.voice_design.elevenlabs import Preview  # noqa: E402


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("VOICE_FORGE_REGISTRY", str(tmp_path / "reg"))
    return TestClient(app)


@pytest.fixture
def fake_previews() -> list[Preview]:
    """Three previews with junk MP3 bytes — enough to exercise base64 encoding."""
    return [
        Preview(generated_voice_id="gv_1", audio=b"\xff\xfb..mp3-1.."),
        Preview(generated_voice_id="gv_2", audio=b"\xff\xfb..mp3-2.."),
        Preview(generated_voice_id="gv_3", audio=b"\xff\xfb..mp3-3.."),
    ]


def test_design_returns_data_uri_candidates(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, fake_previews: list[Preview]
) -> None:
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    monkeypatch.setattr(
        "voice_forge.voice_design.elevenlabs.create_voice_previews",
        lambda description, sample_text, *, api_key=None: fake_previews,
    )
    r = client.post(
        "/v1/forge/design",
        json={"description": "Female, early 40s, warm Norwegian", "voice_id": "freya"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["candidates"]) == 3
    c0 = body["candidates"][0]
    assert c0["generated_voice_id"] == "gv_1"
    assert c0["audio"].startswith("data:audio/mpeg;base64,")
    assert c0["label"] == "Candidate 1"
    assert body["candidates"][2]["label"] == "Candidate 3"
    assert body["description"] == "Female, early 40s, warm Norwegian"
    assert body["voice_name"] == "freya"


def test_design_forwards_description_and_sample_text(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, fake_previews: list[Preview]
) -> None:
    seen: dict[str, str] = {}

    def fake_create(description, sample_text, *, api_key=None):
        seen["description"] = description
        seen["sample_text"] = sample_text
        seen["api_key"] = api_key
        return fake_previews

    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    monkeypatch.setattr("voice_forge.voice_design.elevenlabs.create_voice_previews", fake_create)
    r = client.post(
        "/v1/forge/design",
        json={"description": "deep gravelly narrator", "sample_text": "Hello there."},
    )
    assert r.status_code == 200, r.text
    # Freeform description flows through verbatim (no prompt_builder on this path).
    assert seen["description"] == "deep gravelly narrator"
    assert seen["sample_text"] == "Hello there."
    assert seen["api_key"] == "test-key"


def test_design_uses_default_sample_text_when_omitted(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, fake_previews: list[Preview]
) -> None:
    from voice_forge.server import SAMPLE_TEXT_DEFAULT

    seen: dict[str, str] = {}
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    monkeypatch.setattr(
        "voice_forge.voice_design.elevenlabs.create_voice_previews",
        lambda description, sample_text, *, api_key=None: seen.update(sample_text=sample_text)
        or fake_previews,
    )
    r = client.post("/v1/forge/design", json={"description": "anything"})
    assert r.status_code == 200, r.text
    assert seen["sample_text"] == SAMPLE_TEXT_DEFAULT


def test_design_gated_without_key(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    r = client.post("/v1/forge/design", json={"description": "anything", "voice_id": "x"})
    # CRITICAL: must be 503, NOT 500 — proves the gate fires before the EL module's
    # RuntimeError (which FastAPI would surface as a 500) can ever fire.
    assert r.status_code == 503, r.text
    assert "ELEVENLABS_API_KEY" in r.json()["detail"]  # how-to-enable present


def test_design_rejects_empty_description(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    r = client.post("/v1/forge/design", json={"description": "", "voice_id": "x"})
    assert r.status_code in (400, 422)  # pydantic min_length=1


def test_design_maps_elevenlabs_error_to_502(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from voice_forge.voice_design.elevenlabs import ElevenLabsError

    def boom(description, sample_text, *, api_key=None):
        raise ElevenLabsError("POST", "/v1/text-to-voice/create-previews", 429, "rate limited")

    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    monkeypatch.setattr("voice_forge.voice_design.elevenlabs.create_voice_previews", boom)
    r = client.post("/v1/forge/design", json={"description": "x"})
    assert r.status_code == 502, r.text
