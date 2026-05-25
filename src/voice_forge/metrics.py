"""Prometheus metrics for voice-forge.

A small surface — six metrics — designed to answer the questions an operator
actually asks within the first hour of running voice-forge in production:

- "Is the backend healthy and loaded?"  → ``voice_forge_backend_loaded``
- "How long are synth calls taking?"     → ``voice_forge_synth_seconds`` (histogram)
- "How many calls per voice per minute?" → ``voice_forge_synth_requests_total``
- "Are calls succeeding?"                → same counter, label ``status={ok,fail}``
- "How many WS streams are open right now?" → ``voice_forge_active_ws_connections``
- "Is per-sentence WS streaming actually firing?" → ``voice_forge_ws_sentences_total``

Cardinality note: ``voice_id`` is a label on the per-call counters + histograms.
For tiny deployments (≤100 voices) this is fine; for multi-tenant deploys with
thousands of voice_ids it'll blow up Prometheus's tsdb. Mitigation queued in
``engineering-journal/QUEUED.md`` § "Cap voice_id metric cardinality".
"""

from __future__ import annotations

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

# Dedicated registry — keeps voice-forge metrics separate from any process-wide
# collectors that might be polluting the default REGISTRY (e.g. gunicorn fork
# scraps). The /metrics endpoint exports ONLY this registry.
REGISTRY = CollectorRegistry()

# Synth latency in seconds — the canonical "how slow is my TTS" metric.
# Buckets chosen to cover the range we actually observe:
#   - Kokoro: ~0.5-2s
#   - F5 (nfe_step=16): ~2-8s per sentence
#   - F5 (nfe_step=32): ~5-15s per sentence
#   - NeuTTS long-form (30s+): 10-60s
synth_seconds = Histogram(
    "voice_forge_synth_seconds",
    "Wall-clock seconds per synth call",
    labelnames=("backend", "voice_id", "mode"),  # mode = "batch" | "stream"
    buckets=(0.25, 0.5, 1.0, 2.0, 4.0, 8.0, 16.0, 32.0, 64.0, 128.0),
    registry=REGISTRY,
)

synth_requests_total = Counter(
    "voice_forge_synth_requests_total",
    "Synth calls handled",
    labelnames=("backend", "voice_id", "mode", "status"),  # status = "ok" | "fail"
    registry=REGISTRY,
)

backend_loaded = Gauge(
    "voice_forge_backend_loaded",
    "1 if backend instance is loaded in this process; 0 otherwise",
    labelnames=("backend",),
    registry=REGISTRY,
)

voices_registered = Gauge(
    "voice_forge_voices_registered",
    "Total voices in the registry directory",
    registry=REGISTRY,
)

active_ws_connections = Gauge(
    "voice_forge_active_ws_connections",
    "WebSocket clients currently connected to /v1/tts/stream",
    registry=REGISTRY,
)

ws_sentences_total = Counter(
    "voice_forge_ws_sentences_total",
    "Sentences synthesized through the WebSocket layer-2 stream",
    labelnames=("backend", "voice_id"),
    registry=REGISTRY,
)


def render() -> tuple[bytes, str]:
    """Return (body, content_type) for the /metrics endpoint."""
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST
