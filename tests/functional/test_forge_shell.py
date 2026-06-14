"""U2 — The Forge shell IA + Calm/Bench density.

The studio is no-build (no JS test runner — KTD9), so deep interaction is a
/qa-phase browser check. These CI-gating guards still have teeth:

- every shipped Forge module is valid JavaScript (`node --check`), skipped only
  where node is genuinely absent — node is a check tool here, never a build dep;
- the shell exposes the three regions and the one density control;
- the XSS convention holds: dynamic values go through esc() (the security gate).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from voice_forge.server import app  # noqa: E402

FORGE_DIR = Path(__file__).resolve().parents[2] / "src" / "voice_forge" / "static" / "forge"
JS_FILES = sorted(FORGE_DIR.rglob("*.js"))
NODE = shutil.which("node")


@pytest.fixture(scope="module")
def app_js() -> str:
    return TestClient(app).get("/forge/forge-app.js").text


@pytest.mark.skipif(NODE is None, reason="node not available (it is a check tool, not a build dep)")
@pytest.mark.parametrize("js", JS_FILES, ids=lambda p: p.name)
def test_forge_js_is_valid(js: Path) -> None:
    proc = subprocess.run([NODE, "--check", str(js)], capture_output=True, text=True)
    assert proc.returncode == 0, f"{js.name} syntax error:\n{proc.stderr}"


def test_shell_has_three_regions(app_js: str) -> None:
    for region in ('class="rail"', 'class="subject"', 'class="inspector"'):
        assert region in app_js, f"shell missing region {region}"


def test_shell_has_density_control(app_js: str) -> None:
    assert 'data-density="calm"' in app_js
    assert 'data-density="bench"' in app_js
    assert "setDensity" in app_js


def test_dynamic_values_are_escaped(app_js: str) -> None:
    # The XSS convention: registry/user strings must never be interpolated raw.
    assert "esc(" in app_js, "esc() must guard dynamic values"
    # The voice id is the most-interpolated dynamic field — it must be escaped.
    assert "esc(v.voice_id" in app_js
