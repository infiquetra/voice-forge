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


def test_load_normalizes_data_envelope(app_js: str) -> None:
    # Regression: /v1/audio/voices and /v1/backends answer with an OpenAI-style
    # {data:[…]} envelope. The shell must normalize that to a bare array at the
    # load boundary (asList) — not assume the old {voices:[…]}/{backends:[…]}
    # shape, which silently stored an object and broke the fleet once a voice
    # existed. asList must live in base.js and handle the data key.
    base_js = (FORGE_DIR / "base.js").read_text(encoding="utf-8")
    assert "export function asList" in base_js
    assert "payload.data" in base_js, "asList must accept the {data:[…]} envelope"
    assert "asList(" in app_js, "the shell must normalize list payloads via asList"
    assert "voices.voices || voices" not in app_js, "the old envelope-blind read must be gone"


def test_playback_does_not_trigger_global_rerender() -> None:
    # Regression: a finished take playing back is LOCAL to its <forge-waveform>.
    # It must not write store.forging — cards and the shell observe that key and
    # replace their whole innerHTML, which tore down the very chip mid-play (a
    # take killed itself the instant it started). store.forging means "a
    # synthesis is in flight", set by the serve/audition path, never by playback.
    waveform_js = (FORGE_DIR / "forge-waveform.js").read_text(encoding="utf-8")
    code = "\n".join(line for line in waveform_js.splitlines() if not line.lstrip().startswith("*"))
    assert "store.set({ forging" not in code, "playback must not write the global synth flag"
    # And the shell renders nothing off forging, so it must not observe it
    # (observing it rebuilds the whole fleet — and any take playing in a card —
    # on every synth).
    app_js = (FORGE_DIR / "forge-app.js").read_text(encoding="utf-8")
    observe_line = next(line for line in app_js.splitlines() if "static observe" in line)
    assert '"forging"' not in observe_line, "the shell must not observe forging"
