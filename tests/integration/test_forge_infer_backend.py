"""U6 — the cold-start backend recommendation endpoint: GET /v1/forge/infer-backend.

A pure read/derivation (no state change) the Forge cold-start one-tap calls to
pick a clone backend. The endpoint's answer is host-dependent: it reflects which
LLM-backbone backends are actually importable here. We assert the *contract*
(always 200, always a backend + why, the why distinguishes the two branches)
rather than hardcoding a CI-only degrade path — the deterministic degrade branch
is covered in tests/unit/test_backend_inference.py where ``installed`` is fixed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from voice_forge.backend_inference import LLM_BACKBONE_PREFERENCE  # noqa: E402
from voice_forge.backends import known_backends  # noqa: E402
from voice_forge.server import _is_backend_installed, app  # noqa: E402

_LLM_BACKBONE_INSTALLED = [
    n for n in known_backends() if n in LLM_BACKBONE_PREFERENCE and _is_backend_installed(n)
]


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    # The endpoint doesn't touch the registry, but isolate the env to mirror the
    # other integration tests and keep config resolution hermetic.
    monkeypatch.setenv("VOICE_FORGE_REGISTRY", str(tmp_path / "reg"))
    return TestClient(app)


def test_infer_backend_default_path(client: TestClient) -> None:
    r = client.get("/v1/forge/infer-backend?accent_distinct=false")
    assert r.status_code == 200
    body = r.json()
    assert "backend" in body and "why" in body
    assert "default" in body["why"]


def test_infer_backend_accent_distinct_returns_a_backend_and_why(client: TestClient) -> None:
    r = client.get("/v1/forge/infer-backend?accent_distinct=true")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body["backend"], str) and body["backend"]
    assert isinstance(body["why"], str) and body["why"]


def test_infer_backend_accent_distinct_reflects_installed_backbones(client: TestClient) -> None:
    # Host-dependent: with an LLM-backbone backend importable the endpoint routes
    # to it (preference order); with none it degrades to the default + explains.
    r = client.get("/v1/forge/infer-backend?accent_distinct=true")
    assert r.status_code == 200
    body = r.json()
    if _LLM_BACKBONE_INSTALLED:
        # first installed in journal preference order wins
        expected = next(n for n in LLM_BACKBONE_PREFERENCE if n in _LLM_BACKBONE_INSTALLED)
        assert body["backend"] == expected
        assert "LLM-backbone" in body["why"]
    else:
        assert "no LLM-backbone backend installed" in body["why"]
        assert "may not preserve" in body["why"]


def test_infer_backend_default_omitted_defaults_false(client: TestClient) -> None:
    # accent_distinct defaults to False when the query param is omitted.
    r = client.get("/v1/forge/infer-backend")
    assert r.status_code == 200
    assert "no distinct accent to preserve" in r.json()["why"]
