"""U7 — The Forge cold-start capability probe.

`GET /v1/capabilities` is the authoritative signal the empty-state hero asks to
choose its door: design-from-description (describe-hero) when a design path
exists, else clone-hero with describe gated. Design-readiness is a cloud-key /
future-local-model fact, not a per-backend one — so it lives here, not on
`/v1/backends` (closes plan-review P2 F2).
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from voice_forge.server import app  # noqa: E402

client = TestClient(app)


def test_capabilities_shape() -> None:
    r = client.get("/v1/capabilities")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"elevenlabs_configured", "design_local"}
    assert isinstance(body["elevenlabs_configured"], bool)
    # Local design-from-description (#60) is not shipped — the flag stays False
    # until that backend lands; it's what flips describe from gated to always-on.
    assert body["design_local"] is False


def test_elevenlabs_configured_reflects_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # No key → the cloud design path is unavailable → describe is gated.
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    assert client.get("/v1/capabilities").json()["elevenlabs_configured"] is False

    # Key present → the design path can route to ElevenLabs → describe is the hero.
    monkeypatch.setenv("ELEVENLABS_API_KEY", "sk-test-not-a-real-key")
    assert client.get("/v1/capabilities").json()["elevenlabs_configured"] is True
