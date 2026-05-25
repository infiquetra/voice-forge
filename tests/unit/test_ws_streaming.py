"""WebSocket layer-2 streaming round-trip tests.

Uses FastAPI's TestClient (which speaks the ASGI WebSocket protocol)
plus a fake backend pre-cached in ``server._BACKENDS`` so we never
touch a real model. Tests assert the wire-protocol contract end-to-end:
session metadata, per-sentence start/audio/done events, completion frame,
ordering, and error paths.
"""

from __future__ import annotations

import json
from typing import Any

import numpy as np
import pytest
from fastapi.testclient import TestClient


class FakeWSBackend:
    """Stand-in for a real backend in WS tests.

    synthesize() returns 0.5s of silence at 24 kHz per call — enough for
    assertions about frame shape + ordering. Records every call so tests
    can verify which sentences arrived in what order.
    """

    name = "fake-ws"
    KNOWN_TUNABLES: dict = {}

    def __init__(self) -> None:
        # Each tuple is (voice_id, text, sampling_snapshot). Lets tests assert
        # both routing (which sentence to which voice) AND that request-scope
        # sampling overrides flowed through to the backend.
        self.calls: list[tuple[str, str, dict]] = []

    def load(self, config: dict) -> None:  # pragma: no cover — not exercised
        pass

    def encode_reference(self, _ref_audio_path: str) -> None:  # pragma: no cover
        return None

    def synthesize(self, text: str, ref: Any) -> np.ndarray:
        sampling = dict(ref.metadata.get("sampling") or {})
        self.calls.append((ref.voice_id, text, sampling))
        # 0.5 s silence at 24 kHz, float32
        return np.zeros(12_000, dtype=np.float32)

    def synthesize_stream(self, text: str, ref: Any):  # pragma: no cover
        yield self.synthesize(text, ref)

    def health(self) -> dict:  # pragma: no cover
        return {"name": self.name, "loaded": True}


@pytest.fixture
def ws_setup(tmp_path, monkeypatch):
    """Build a tmp registry with one fake voice + pre-cache a fake backend."""
    reg_root = tmp_path / "registry"
    reg_root.mkdir()
    voice_dir = reg_root / "fake-voice"
    voice_dir.mkdir()
    (voice_dir / "metadata.json").write_text(
        json.dumps(
            {
                "voice_id": "fake-voice",
                "backend": "fake-ws",
                "language": "en",
                "description": "fake backend for WS tests",
            }
        )
    )
    monkeypatch.setenv("VOICE_FORGE_REGISTRY", str(reg_root))

    # Pre-cache the fake backend so _ensure_backend() short-circuits the
    # canonical backend-registry dispatch.
    from voice_forge import server

    fake = FakeWSBackend()
    monkeypatch.setitem(server._BACKENDS, "fake-ws", fake)

    client = TestClient(server.app)
    return client, fake


def _collect_until_complete(ws) -> tuple[list[dict], list[bytes]]:
    """Drain events + binary audio frames until the server sends 'complete' or 'error'."""
    events: list[dict] = []
    audio_frames: list[bytes] = []
    while True:
        # Starlette's TestClient WS surfaces text + bytes frames via raw receive().
        msg = ws.receive()
        if "text" in msg and msg["text"] is not None:
            event = json.loads(msg["text"])
            events.append(event)
            if event.get("event") in ("complete", "error"):
                return events, audio_frames
        elif "bytes" in msg and msg["bytes"] is not None:
            audio_frames.append(msg["bytes"])


def test_ws_basic_single_sentence_round_trip(ws_setup):
    client, fake = ws_setup
    with client.websocket_connect("/v1/tts/stream") as ws:
        ws.send_json({"voice": "fake-voice"})
        # First frame is the session-metadata event.
        meta = ws.receive_json()
        assert meta == {
            "event": "session",
            "voice": "fake-voice",
            "backend": "fake-ws",
            "sample_rate": 24_000,
            "channels": 1,
            "format": "pcm_f32le",
        }
        ws.send_json({"text": "Hello world.", "end": True})
        events, audio = _collect_until_complete(ws)

    # One synth call for one sentence.
    assert fake.calls == [("fake-voice", "Hello world.", {})]
    # Events: sentence_start, sentence_done, complete (and there's exactly one bin frame).
    starts = [e for e in events if e["event"] == "sentence_start"]
    dones = [e for e in events if e["event"] == "sentence_done"]
    completes = [e for e in events if e["event"] == "complete"]
    assert len(starts) == 1
    assert starts[0]["idx"] == 0
    assert starts[0]["text"] == "Hello world."
    assert len(dones) == 1
    assert dones[0]["idx"] == 0
    assert dones[0]["samples"] == 12_000
    assert dones[0]["synth_ms"] >= 0
    assert len(audio) == 1
    # 12,000 float32 samples = 48,000 bytes
    assert len(audio[0]) == 12_000 * 4
    assert completes[0]["sentences_total"] == 1


def test_ws_multi_sentence_streamed_in_chunks(ws_setup):
    """Mimics an LLM trickling tokens — sentences emerge as their boundary forms."""
    client, fake = ws_setup
    with client.websocket_connect("/v1/tts/stream") as ws:
        ws.send_json({"voice": "fake-voice"})
        ws.receive_json()  # session
        # Send the first sentence in two pieces — no synth should happen
        # until the boundary (`. `) materializes.
        ws.send_json({"text": "First sentence"})
        ws.send_json({"text": ". "})
        # Now the second + third in another burst.
        ws.send_json({"text": "Second one. Third one.", "end": True})
        events, audio = _collect_until_complete(ws)

    assert [c[1] for c in fake.calls] == [
        "First sentence.",
        "Second one.",
        "Third one.",
    ]
    assert len([e for e in events if e["event"] == "sentence_done"]) == 3
    assert len(audio) == 3
    assert [e for e in events if e["event"] == "complete"][0]["sentences_total"] == 3


def test_ws_flush_emits_partial_trailing_text(ws_setup):
    """Text without a trailing terminator still gets synth'd on end-of-stream."""
    client, fake = ws_setup
    with client.websocket_connect("/v1/tts/stream") as ws:
        ws.send_json({"voice": "fake-voice"})
        ws.receive_json()
        ws.send_json({"text": "Done sentence. trailing no period", "end": True})
        events, _ = _collect_until_complete(ws)

    sentences = [c[1] for c in fake.calls]
    assert sentences == ["Done sentence.", "trailing no period"]
    assert [e for e in events if e["event"] == "complete"][0]["sentences_total"] == 2


def test_ws_event_ordering_per_sentence(ws_setup):
    """For each sentence: sentence_start, then binary frame, then sentence_done."""
    client, _ = ws_setup
    with client.websocket_connect("/v1/tts/stream") as ws:
        ws.send_json({"voice": "fake-voice"})
        ws.receive_json()
        ws.send_json({"text": "A. B.", "end": True})

        # Collect each frame in order, identifying which type each one is.
        sequence: list[str] = []
        while True:
            msg = ws.receive()
            if "text" in msg and msg["text"] is not None:
                event = json.loads(msg["text"])
                sequence.append(event["event"])
                if event["event"] == "complete":
                    break
            elif "bytes" in msg and msg["bytes"] is not None:
                sequence.append("binary")

    assert sequence == [
        "sentence_start",
        "binary",
        "sentence_done",
        "sentence_start",
        "binary",
        "sentence_done",
        "complete",
    ]


def test_ws_missing_voice_in_first_message_errors(ws_setup):
    client, _ = ws_setup
    with client.websocket_connect("/v1/tts/stream") as ws:
        ws.send_json({"not_voice": "oops"})
        msg = ws.receive_json()
    assert msg["event"] == "error"
    assert "voice" in msg["detail"]


def test_ws_unknown_voice_errors(ws_setup):
    client, _ = ws_setup
    with client.websocket_connect("/v1/tts/stream") as ws:
        ws.send_json({"voice": "does-not-exist"})
        msg = ws.receive_json()
    assert msg["event"] == "error"
    assert "does-not-exist" in msg["detail"]
    assert "registry" in msg["detail"].lower()


def test_ws_end_without_any_text_emits_zero_sentences(ws_setup):
    """A connection that sends just {"end": true} is valid — yields no audio."""
    client, fake = ws_setup
    with client.websocket_connect("/v1/tts/stream") as ws:
        ws.send_json({"voice": "fake-voice"})
        ws.receive_json()
        ws.send_json({"end": True})
        events, audio = _collect_until_complete(ws)
    assert fake.calls == []
    assert audio == []
    assert [e for e in events if e["event"] == "complete"][0]["sentences_total"] == 0


def test_ws_audio_frame_is_float32_le_24khz(ws_setup):
    """Binary frame contract: raw float32-little-endian PCM."""
    client, _ = ws_setup
    with client.websocket_connect("/v1/tts/stream") as ws:
        ws.send_json({"voice": "fake-voice"})
        ws.receive_json()
        ws.send_json({"text": "Hello.", "end": True})
        _, audio = _collect_until_complete(ws)
    # Round-trip the bytes back through numpy and confirm it's a valid float32 array.
    pcm = np.frombuffer(audio[0], dtype=np.float32)
    assert pcm.dtype == np.float32
    assert len(pcm) == 12_000
    # Sample range is finite (no NaN / Inf in our fake silence)
    assert np.isfinite(pcm).all()


def test_ws_text_only_whitespace_is_dropped(ws_setup):
    """A flush of pure-whitespace remainder does not produce a synth call."""
    client, fake = ws_setup
    with client.websocket_connect("/v1/tts/stream") as ws:
        ws.send_json({"voice": "fake-voice"})
        ws.receive_json()
        ws.send_json({"text": "One sentence. ", "end": True})
        ws.send_json({"text": "   \n\t  ", "end": True})  # ignored — after end
        events, _ = _collect_until_complete(ws)
    # Only the one real sentence was synthesized.
    assert [c[1] for c in fake.calls] == ["One sentence."]
    assert [e for e in events if e["event"] == "complete"][0]["sentences_total"] == 1


def test_ws_init_frame_sampling_overrides_flow_through_to_backend(ws_setup):
    """Init-frame sampling override is merged into voice metadata for synth."""
    client, fake = ws_setup
    from voice_forge.registry import Registry

    # Set a per-voice sampling baseline first (writes through to metadata.json).
    reg = Registry()
    reg.tune("fake-voice", sampling_overrides={"speed": 1.0})
    # Open WS with a request-scope override that should win
    with client.websocket_connect("/v1/tts/stream") as ws:
        ws.send_json({"voice": "fake-voice", "sampling": {"speed": 1.5, "nfe_step": 16}})
        ws.receive_json()  # session
        ws.send_json({"text": "Hello.", "end": True})
        # Drain to completion
        _events, _audio = _collect_until_complete(ws)
    # FakeBackend records ref objects on each call. The synth call should see
    # the merged metadata — speed overridden to 1.5 (request), plus nfe_step=16
    # added (request-only).
    # FakeBackend's calls now include a sampling snapshot — the request-scope
    # overrides should be merged into voice_ref.metadata for the synth call.
    last_sampling = fake.calls[-1][2]
    assert last_sampling.get("speed") == 1.5  # request override wins over registry
    assert last_sampling.get("nfe_step") == 16  # request-only key added

    # Registry is untouched — request-scope override is per-session, not persisted.
    reg_again = Registry().get("fake-voice")
    assert reg_again.metadata.get("sampling", {}).get("speed") == 1.0
    assert "nfe_step" not in reg_again.metadata.get("sampling", {})


def test_list_backends_returns_known_set_with_tunable_schemas(ws_setup):
    """GET /v1/backends lists each known backend + its KNOWN_TUNABLES schema."""
    client, _ = ws_setup
    resp = client.get("/v1/backends")
    assert resp.status_code == 200
    body = resp.json()
    assert "data" in body
    by_name = {b["name"]: b for b in body["data"]}
    # All five v0.2 backends should appear regardless of which extras are installed
    # (some may have installed=False in CI where extras are missing).
    for expected in ("f5", "kokoro", "neutts", "xtts", "dia"):
        assert expected in by_name, f"missing backend {expected!r} in /v1/backends"
        entry = by_name[expected]
        assert "tunables" in entry
        assert "installed" in entry
        assert "known" in entry
    # F5's tunable schema should at minimum carry nfe_step + its bounds.
    f5_tunables = by_name["f5"]["tunables"]
    if by_name["f5"]["installed"]:
        assert "nfe_step" in f5_tunables
        spec = f5_tunables["nfe_step"]
        assert spec["type"] == "int"
        assert spec["min"] <= 16 <= spec["max"]
        assert spec["default"] == 32


def test_list_voices_surfaces_persona(ws_setup):
    """GET /v1/audio/voices returns each voice's derived (or explicit) persona."""
    client, _ = ws_setup
    resp = client.get("/v1/audio/voices")
    assert resp.status_code == 200
    body = resp.json()
    fake = next(v for v in body["data"] if v["id"] == "fake-voice")
    # The fake voice has no explicit persona in metadata, so the derivation
    # falls back to voice_id verbatim (no known backend suffix to strip).
    assert fake["persona"] == "fake-voice"


def test_demo_page_is_served(ws_setup):
    """GET /demo returns the live-demo HTML page from the packaged static dir."""
    client, _ = ws_setup
    resp = client.get("/demo")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    body = resp.text
    # Sanity-check that it's actually our demo page, not a generic 404.
    assert "voice-forge" in body.lower()
    assert "websocket" in body.lower()
    assert "/v1/tts/stream" in body
    # The voice picker is populated by an in-page fetch — confirm the JS
    # would hit our REST endpoint.
    assert "/v1/audio/voices" in body
