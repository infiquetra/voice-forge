"""U1 — The Forge no-build serving foundation.

Verifies the studio ships as a complete, predefined interface served straight
from the package with zero build step (R23/R24): /forge and all its assets
resolve, the entry mounts <forge-app>, the legacy /lab survives, and nothing in
the bundle reaches out to a CDN at runtime (the offline / no-vendoring guard).
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from voice_forge.server import app  # noqa: E402

FORGE_DIR = Path(__file__).resolve().parents[2] / "src" / "voice_forge" / "static" / "forge"


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


def test_forge_index_serves(client: TestClient) -> None:
    r = client.get("/forge/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    body = r.text
    assert "<forge-app>" in body
    assert 'type="module"' in body  # native ES modules, no bundle


@pytest.mark.parametrize(
    "asset",
    [
        "forge-app.js",
        "tokens.css",
        "store.js",
        "base.js",
        "index.html",
        # The component layer (U3/U4/U6–U10) — each ships as its own no-build module.
        "forge-waveform.js",
        "forge-voice-card.js",
        "forge-backend-chip.js",
        "forge-empty-hero.js",
        "forge-spec-editor.js",
        "forge-serve-console.js",
        "forge-contact-sheet.js",
    ],
)
def test_forge_assets_serve(client: TestClient, asset: str) -> None:
    assert client.get(f"/forge/{asset}").status_code == 200


def test_shell_registers_component_layer() -> None:
    # The shell must side-effect-import every component so the custom elements
    # are defined when <forge-app> paints them — a missing import = a blank region.
    shell = (FORGE_DIR / "forge-app.js").read_text(encoding="utf-8")
    for component in (
        "forge-waveform.js",
        "forge-voice-card.js",
        "forge-backend-chip.js",
        "forge-empty-hero.js",
        "forge-spec-editor.js",
        "forge-serve-console.js",
        "forge-contact-sheet.js",
    ):
        assert f'"./{component}"' in shell, f"shell does not import {component}"


def test_seed_clip_serves_and_is_wired(client: TestClient) -> None:
    # U7/KTD6 — the bundled first-paint clip makes the cold start audible. It must
    # ship + serve as real audio, and the shell must point the hero at it.
    r = client.get("/forge/seed.mp3")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("audio/")
    assert len(r.content) > 1000  # a real clip, not an empty/placeholder file
    shell = (FORGE_DIR / "forge-app.js").read_text(encoding="utf-8")
    assert 'seed-src="seed.mp3"' in shell, "the hero is not wired to the seed clip"


def test_legacy_lab_still_serves(client: TestClient) -> None:
    # /lab stays as the legacy power-user surface (KTD7) — the redesign is additive.
    assert client.get("/lab").status_code == 200


def test_no_runtime_cdn_imports() -> None:
    # The offline / no-build guard: no asset may import from an http(s) URL at
    # runtime (that would be a hidden network dependency / a vendoring failure).
    offenders: list[str] = []
    for path in FORGE_DIR.rglob("*.js"):
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("import") and ("http://" in stripped or "https://" in stripped):
                offenders.append(f"{path.name}: {stripped}")
    assert not offenders, f"runtime CDN imports break offline/no-build: {offenders}"
