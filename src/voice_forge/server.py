"""FastAPI app — REST surface for voice-forge.

Endpoints (see docs/API_SPEC.md for full spec):
  - POST /v1/audio/speech      Synthesize text → audio (OpenAI-compatible)
  - GET  /v1/audio/voices      List registered voices
  - POST /voices/{id}          Register a new voice
  - POST /voices/from-elevenlabs   Pull from ElevenLabs Voice Lab
  - DELETE /voices/{id}        Remove a voice
  - GET  /voices/{id}          Get voice metadata
  - GET  /health               Service health

Phase D fills out implementations. This file is a skeleton.
"""

from __future__ import annotations

from fastapi import FastAPI


app = FastAPI(
    title="voice-forge",
    version="0.1.0.dev0",
    description="Pluggable TTS service for agent voices",
)


@app.get("/health")
async def health() -> dict:
    """Service health endpoint."""
    # TODO Phase D: include backend states + registry voice count
    return {"ok": True, "version": "0.1.0.dev0"}


# TODO Phase D: implement /v1/audio/speech, /v1/audio/voices, /voices/*, etc.
