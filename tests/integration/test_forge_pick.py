"""The Forge — POST /v1/forge/pick (persist a design candidate as a BOUND voice).

Full design→pick→register orchestration coverage with zero network and zero key.
Three EL boundary functions are monkeypatched at their source modules so the
endpoint's deferred imports pick up the fakes:

  - ``voice_forge.voice_design.elevenlabs.create_voice_from_preview`` → permanent id
  - ``voice_forge.voice_lab.elevenlabs.pull_and_prepare``             → (wav, ref_text)

``fake_ref_wav`` writes a real tiny WAV because ``registry.register`` copies the
ref audio off disk — a path to a nonexistent file would raise FileNotFoundError.
"""

from __future__ import annotations

import wave
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from voice_forge.registry import Registry  # noqa: E402
from voice_forge.server import app  # noqa: E402


@pytest.fixture
def registry_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "reg"
    root.mkdir()
    monkeypatch.setenv("VOICE_FORGE_REGISTRY", str(root))
    return root


@pytest.fixture
def client(registry_root: Path) -> TestClient:
    return TestClient(app)


@pytest.fixture
def fake_ref_wav(tmp_path: Path) -> Path:
    """A real tiny mono 24kHz WAV — registry.register copies it off disk."""
    wav_path = tmp_path / "ref.wav"
    with wave.open(str(wav_path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(24000)
        f.writeframes(b"\x00" * (24000 * 2 // 10))  # 0.1s silence
    return wav_path


def test_pick_persists_and_registers_bound_voice(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, fake_ref_wav: Path
) -> None:
    calls: dict[str, str] = {}

    def fake_create_from_preview(voice_name, description, generated_voice_id, *, api_key=None):
        calls["gv"] = generated_voice_id
        calls["name"] = voice_name
        calls["description"] = description
        return "el_voice_persisted_123"

    def fake_pull(voice_id, api_key=None, trim_to_seconds=14.0, output_dir=None):
        calls["pulled"] = voice_id
        return fake_ref_wav, "the quick brown fox"

    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    monkeypatch.setattr(
        "voice_forge.voice_design.elevenlabs.create_voice_from_preview",
        fake_create_from_preview,
    )
    monkeypatch.setattr(
        "voice_forge.voice_lab.elevenlabs.pull_and_prepare", fake_pull
    )

    r = client.post(
        "/v1/forge/pick",
        json={
            "generated_voice_id": "gv_2",
            "description": "warm Norwegian",
            "voice_id": "freya",
            "persona": "freya",
            "backend": "f5",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["id"] == "freya"
    assert body["persona"] == "freya"  # born bound
    assert body["backend"] == "f5"
    assert body["metadata"]["source"] == "elevenlabs-design:el_voice_persisted_123"
    assert body["description"] == "warm Norwegian"
    # Orchestration wired correctly:
    assert calls["gv"] == "gv_2"  # design ID forwarded to persist
    assert calls["name"] == "freya"  # voice_name defaulted to voice_id
    assert calls["pulled"] == "el_voice_persisted_123"  # persisted ID forwarded to pull


def test_pick_uses_u6_inference_when_backend_omitted(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, fake_ref_wav: Path
) -> None:
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    monkeypatch.setattr(
        "voice_forge.voice_design.elevenlabs.create_voice_from_preview",
        lambda *a, **k: "el_x",
    )
    monkeypatch.setattr(
        "voice_forge.voice_lab.elevenlabs.pull_and_prepare",
        lambda *a, **k: (fake_ref_wav, "txt"),
    )
    # No backend in the body → U6 infer_backend picks; we assert it produced *a*
    # backend (host-dependent which one), matching what infer_backend returns.
    from voice_forge.backend_inference import infer_backend
    from voice_forge.backends import known_backends
    from voice_forge.config import get_default_backend
    from voice_forge.server import _is_backend_installed

    installed = [n for n in known_backends() if _is_backend_installed(n)]
    expected, _ = infer_backend(
        accent_distinct=True, installed=installed, default=get_default_backend()
    )

    r = client.post(
        "/v1/forge/pick",
        json={
            "generated_voice_id": "gv_1",
            "description": "d",
            "voice_id": "v2",
            "accent_distinct": True,
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["backend"] == expected


def test_pick_gated_without_key(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    r = client.post(
        "/v1/forge/pick",
        json={"generated_voice_id": "gv", "description": "d", "voice_id": "v"},
    )
    assert r.status_code == 503, r.text  # never 500
    assert "ELEVENLABS_API_KEY" in r.json()["detail"]


def test_pick_conflict_without_overwrite(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    fake_ref_wav: Path,
    registry_root: Path,
) -> None:
    # Pre-seed an existing voice so the register step hits FileExistsError.
    Registry().register(
        voice_id="taken",
        ref_audio_path=fake_ref_wav,
        ref_text="existing",
        backend="f5",
    )

    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    monkeypatch.setattr(
        "voice_forge.voice_design.elevenlabs.create_voice_from_preview",
        lambda *a, **k: "el_x",
    )
    monkeypatch.setattr(
        "voice_forge.voice_lab.elevenlabs.pull_and_prepare",
        lambda *a, **k: (fake_ref_wav, "txt"),
    )
    r = client.post(
        "/v1/forge/pick",
        json={
            "generated_voice_id": "gv",
            "description": "d",
            "voice_id": "taken",
            "backend": "f5",
        },
    )
    assert r.status_code == 409, r.text


def test_pick_maps_persist_error_to_502(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from voice_forge.voice_design.elevenlabs import ElevenLabsError

    def boom(*a, **k):
        raise ElevenLabsError(
            "POST", "/v1/text-to-voice/create-voice-from-preview", 400, "bad preview"
        )

    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    monkeypatch.setattr(
        "voice_forge.voice_design.elevenlabs.create_voice_from_preview", boom
    )
    r = client.post(
        "/v1/forge/pick",
        json={"generated_voice_id": "gv", "description": "d", "voice_id": "v"},
    )
    assert r.status_code == 502, r.text


def test_pick_maps_pull_value_error_to_400(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    monkeypatch.setattr(
        "voice_forge.voice_design.elevenlabs.create_voice_from_preview",
        lambda *a, **k: "el_x",
    )

    def bad_pull(*a, **k):
        raise ValueError("voice 'el_x' has no preview_url")

    monkeypatch.setattr(
        "voice_forge.voice_lab.elevenlabs.pull_and_prepare", bad_pull
    )
    r = client.post(
        "/v1/forge/pick",
        json={"generated_voice_id": "gv", "description": "d", "voice_id": "v", "backend": "f5"},
    )
    assert r.status_code == 400, r.text
