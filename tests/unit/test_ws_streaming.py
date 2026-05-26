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

    def unload(self) -> None:  # pragma: no cover — exercised only by lifecycle tests
        return None


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
    from voice_forge.backends import _BACKEND_MODULES

    fake = FakeWSBackend()
    monkeypatch.setitem(server._BACKENDS, "fake-ws", fake)
    # Make "fake-ws" appear in known_backends() so the lifecycle endpoints
    # accept it. Module path doesn't matter because the backend is already
    # cached in _BACKENDS so load_backend_module() never runs.
    monkeypatch.setitem(_BACKEND_MODULES, "fake-ws", "tests._stubs.unused")

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
        assert spec["default"] == 16


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


def test_metrics_endpoint_renders_prometheus_format(ws_setup):
    """GET /metrics returns text/plain Prometheus exposition with the core metrics."""
    client, _ = ws_setup
    resp = client.get("/metrics")
    assert resp.status_code == 200
    # Prometheus client uses one of "text/plain; version=0.0.4; charset=utf-8"
    # or the OpenMetrics variant. Either way we should see text/plain.
    assert "text/plain" in resp.headers["content-type"]
    body = resp.text
    # Each metric we defined should appear in the registry's HELP/TYPE block,
    # even before any synth has happened.
    for name in (
        "voice_forge_synth_seconds",
        "voice_forge_synth_requests_total",
        "voice_forge_backend_loaded",
        "voice_forge_voices_registered",
        "voice_forge_active_ws_connections",
        "voice_forge_ws_sentences_total",
    ):
        assert name in body, f"missing metric {name!r} in /metrics body"
    # voices_registered gauge is set per scrape — should show our fake voice.
    assert "voice_forge_voices_registered 1" in body or "voice_forge_voices_registered 1.0" in body


def test_metrics_ws_active_connections_tracks_open_sockets(ws_setup):
    """The active-WS-connections gauge increments on connect + decrements on close."""
    client, _ = ws_setup

    def gauge_value(body):
        for line in body.splitlines():
            if line.startswith("voice_forge_active_ws_connections "):
                return float(line.split()[1])
        return None

    initial = gauge_value(client.get("/metrics").text)
    with client.websocket_connect("/v1/tts/stream") as ws:
        ws.send_json({"voice": "fake-voice"})
        ws.receive_json()  # session
        during = gauge_value(client.get("/metrics").text)
        ws.send_json({"end": True})
        _collect_until_complete(ws)
    after = gauge_value(client.get("/metrics").text)
    assert (
        during == (initial or 0) + 1
    ), f"expected gauge to go up; initial={initial} during={during}"
    assert after == initial, f"expected gauge back to initial; initial={initial} after={after}"


def test_ws_pipelining_handles_burst_of_sentences_in_one_frame(ws_setup):
    """Burst-loading multiple sentences in one text frame: producer fans them out
    onto the queue; consumer drains in order. Exercises the producer/consumer
    split in the WS handler."""
    client, fake = ws_setup
    with client.websocket_connect("/v1/tts/stream") as ws:
        ws.send_json({"voice": "fake-voice"})
        ws.receive_json()  # session
        # All five sentences in one text frame — they all hit SentenceBuffer
        # boundaries together, producer pushes all five onto the queue, consumer
        # drains them sequentially via the F5-style backend lock.
        ws.send_json({"text": "S1. S2. S3. S4. S5.", "end": True})
        events, audio = _collect_until_complete(ws)

    assert [c[1] for c in fake.calls] == ["S1.", "S2.", "S3.", "S4.", "S5."]
    assert len(audio) == 5
    done_events = [e for e in events if e["event"] == "sentence_done"]
    assert [e["idx"] for e in done_events] == [0, 1, 2, 3, 4]
    assert [e for e in events if e["event"] == "complete"][0]["sentences_total"] == 5


def test_ws_pipelining_text_arriving_after_synth_starts(ws_setup):
    """Producer keeps pulling text frames while consumer is mid-synth — the
    scenario where layer-2 actually pays off vs the old sequential handler.

    Sends s1's boundary, then immediately s2/s3 + end while s1 is being
    synthesized in the threadpool. With pipelining the producer never blocks
    on the consumer, so all three sentences end up queued + synth'd in order.
    """
    client, fake = ws_setup
    with client.websocket_connect("/v1/tts/stream") as ws:
        ws.send_json({"voice": "fake-voice"})
        ws.receive_json()
        # Each send_json is a separate WS frame the producer pulls in its loop;
        # interleave so the queue has items by the time synth(s1) returns.
        ws.send_json({"text": "First. "})
        ws.send_json({"text": "Second. "})
        ws.send_json({"text": "Third.", "end": True})
        events, _ = _collect_until_complete(ws)

    assert [c[1] for c in fake.calls] == ["First.", "Second.", "Third."]
    assert [e for e in events if e["event"] == "complete"][0]["sentences_total"] == 3


def test_ws_consumer_failure_surfaces_as_error_event(ws_setup, monkeypatch):
    """If backend.synthesize raises mid-stream, the consumer task catches it,
    sets error_state, and the WS sends an ``error`` event before closing."""
    client, fake = ws_setup

    # Patch the fake's synth to raise on the second sentence — the first
    # should complete normally, the second triggers the error path.
    original_synthesize = fake.synthesize
    call_count = {"n": 0}

    def boom_on_second(text, ref):
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise RuntimeError("synthetic backend failure")
        return original_synthesize(text, ref)

    monkeypatch.setattr(fake, "synthesize", boom_on_second)

    with client.websocket_connect("/v1/tts/stream") as ws:
        ws.send_json({"voice": "fake-voice"})
        ws.receive_json()
        ws.send_json({"text": "Good. Bad. Never.", "end": True})

        events: list[dict] = []
        seen_error = False
        try:
            while True:
                msg = ws.receive()
                if "text" in msg and msg["text"] is not None:
                    event = json.loads(msg["text"])
                    events.append(event)
                    if event.get("event") == "error":
                        seen_error = True
                        break
        except Exception:
            # Server-side close after error may surface as a TestClient exception
            pass

    assert seen_error, f"expected error event in {[e.get('event') for e in events]}"
    error_event = next(e for e in events if e["event"] == "error")
    assert "synthetic backend failure" in error_event["detail"]


def test_ws_burst_then_idle_still_completes(ws_setup):
    """Five sentences fired at once, then a long pause before end:true.
    Producer queues all five immediately; consumer drains while the producer
    blocks waiting for the end frame. Tests that the queue/sentinel flow
    handles the "all work queued before end arrives" case."""
    client, fake = ws_setup
    with client.websocket_connect("/v1/tts/stream") as ws:
        ws.send_json({"voice": "fake-voice"})
        ws.receive_json()
        ws.send_json({"text": "A1. A2. A3. A4. A5. "})
        # No end yet — the trailing space ensures the last sentence boundary
        # fires inside the buffer.
        ws.send_json({"end": True})
        events, audio = _collect_until_complete(ws)

    assert [c[1] for c in fake.calls] == ["A1.", "A2.", "A3.", "A4.", "A5."]
    assert len(audio) == 5
    assert [e for e in events if e["event"] == "complete"][0]["sentences_total"] == 5


def test_load_endpoint_warms_a_backend(ws_setup):
    """POST /v1/backends/<name>/load loads the backend without needing a synth call."""
    client, _ = ws_setup
    # _BACKENDS already contains fake-ws from the ws_setup fixture; assert that
    # /load reports "already_loaded" instead of double-loading.
    resp = client.post("/v1/backends/fake-ws/load")
    assert resp.status_code == 200
    body = resp.json()
    assert body["backend"] == "fake-ws"
    assert body["action"] == "already_loaded"
    assert body["affected_backends"] == ["fake-ws"]
    assert body["reclaimed_mb"] == 0.0


def test_load_endpoint_unknown_backend_404(ws_setup):
    client, _ = ws_setup
    resp = client.post("/v1/backends/does-not-exist/load")
    assert resp.status_code == 404


def test_unload_endpoint_releases_loaded_backend(ws_setup):
    """POST /v1/backends/<name>/unload calls backend.unload() and reports RSS delta."""
    client, fake = ws_setup
    # Confirm it's loaded first
    list_before = client.get("/v1/backends").json()
    fake_entry = next(b for b in list_before["data"] if b["name"] == "fake-ws")
    assert fake_entry["loaded"] is True

    resp = client.post("/v1/backends/fake-ws/unload")
    assert resp.status_code == 200
    body = resp.json()
    assert body["backend"] == "fake-ws"
    assert body["action"] == "unloaded"
    assert body["affected_backends"] == ["fake-ws"]
    # RSS measurements should be present (psutil is in deps)
    assert body["rss_before_mb"] is not None
    assert body["rss_after_mb"] is not None
    assert body["reclaimed_mb"] is not None

    # Second unload is idempotent
    resp2 = client.post("/v1/backends/fake-ws/unload")
    assert resp2.json()["action"] == "already_unloaded"


def test_delete_loaded_endpoint_unloads_all(ws_setup):
    """DELETE /v1/backends/loaded unloads every loaded backend."""
    client, _ = ws_setup
    resp = client.delete("/v1/backends/loaded")
    assert resp.status_code == 200
    body = resp.json()
    assert body["action"] == "reset"
    assert "fake-ws" in body["affected_backends"]
    # Subsequent DELETE on empty is a no-op (zero affected_backends)
    resp2 = client.delete("/v1/backends/loaded")
    assert resp2.json()["affected_backends"] == []


def test_put_default_persists_to_config_and_surfaces_via_get(ws_setup, tmp_path, monkeypatch):
    """PUT /v1/backends/default writes the config + GET /v1/backends reflects is_default."""
    # Sandbox the config file
    monkeypatch.setenv("VOICE_FORGE_CONFIG_DIR", str(tmp_path / "vf-config"))
    client, _ = ws_setup
    # baseline: f5 is the hardcoded fallback when config file doesn't exist
    baseline = client.get("/v1/backends").json()
    f5_row = next(b for b in baseline["data"] if b["name"] == "f5")
    assert f5_row["is_default"] is True

    # Flip to kokoro
    resp = client.put("/v1/backends/default", json={"backend": "kokoro"})
    assert resp.status_code == 200
    assert resp.json()["default_backend"] == "kokoro"

    after = client.get("/v1/backends").json()
    kokoro_row = next(b for b in after["data"] if b["name"] == "kokoro")
    f5_row_after = next(b for b in after["data"] if b["name"] == "f5")
    assert kokoro_row["is_default"] is True
    assert f5_row_after["is_default"] is False

    # And it's persisted to disk
    config_file = tmp_path / "vf-config" / "config.json"
    assert config_file.is_file()
    import json as _json

    assert _json.loads(config_file.read_text())["default_backend"] == "kokoro"


def test_put_default_rejects_unknown_backend(ws_setup):
    client, _ = ws_setup
    resp = client.put("/v1/backends/default", json={"backend": "does-not-exist"})
    assert resp.status_code == 400


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
