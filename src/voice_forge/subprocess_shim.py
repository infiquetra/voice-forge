"""Child-process shim entrypoint for subprocess-isolated backends.

This module is installed into every per-backend venv via the
``voice-forge-tts[subprocess-shim]`` extra. The parent voice-forge
process spawns it with ``voice-forge-backend-shim <backend_name>`` and
talks to it over localhost HTTP.

Wire contract (must match ``backends/_subprocess.py``):

    GET  /health              → 200 {"loaded": bool, "model": str, ...}
    POST /synth               → 200 binary float32-LE PCM stream
        body: {"text": "...", "ref": {voice_id, ref_audio_path, ref_text,
                                       preset_id, metadata}}

The shim itself doesn't know how to synth — it imports the backend
module by name (``voice_forge.backends.<backend_name>``) and delegates
to the backend's ``synthesize_stream()``. The backend's heavy
dependencies (torch, piper-tts, etc.) live in the child venv only;
voice-forge's main venv never imports them.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from typing import Any

import numpy as np
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from .backends import VoiceRef, get_backend, load_backend_module

logger = logging.getLogger("voice_forge.subprocess_shim")


def _read_config_from_env() -> dict:
    """Pull VOICE_FORGE_BACKEND_CONFIG_* env vars into a config dict.

    Mirrors how SubprocessBackend._spawn_child() exports parent-side
    config to the child. Underscores stay; the leading prefix is
    stripped and the rest is lowercased.
    """
    config: dict[str, Any] = {}
    prefix = "VOICE_FORGE_BACKEND_CONFIG_"
    for k, v in os.environ.items():
        if k.startswith(prefix):
            config[k[len(prefix) :].lower()] = v
    return config


class SynthRequest(BaseModel):
    text: str
    ref: dict


def build_app(backend_name: str) -> FastAPI:
    """Build the child-process FastAPI app for ``backend_name``.

    Imports the backend module + instantiates + loads using config from env.
    """
    load_backend_module(backend_name)
    backend_cls = get_backend(backend_name)
    backend = backend_cls()
    config = _read_config_from_env()
    logger.info("[%s shim] loading backend with config=%r", backend_name, config)
    backend.load(config)
    logger.info("[%s shim] backend loaded", backend_name)

    app = FastAPI(title=f"voice-forge subprocess shim · {backend_name}")

    @app.get("/health")
    async def health() -> JSONResponse:
        return JSONResponse(backend.health())

    @app.post("/synth")
    async def synth(req: SynthRequest) -> StreamingResponse:
        try:
            voice_ref = VoiceRef(
                voice_id=req.ref.get("voice_id", ""),
                backend=backend_name,
                ref_audio_path=req.ref.get("ref_audio_path"),
                ref_text=req.ref.get("ref_text"),
                preset_id=req.ref.get("preset_id"),
                metadata=req.ref.get("metadata") or {},
            )
        except (TypeError, KeyError) as exc:
            raise HTTPException(status_code=400, detail=f"bad ref: {exc!r}") from exc

        def _gen():
            for chunk in backend.synthesize_stream(req.text, voice_ref):
                yield np.asarray(chunk, dtype=np.float32).tobytes()

        return StreamingResponse(_gen(), media_type="application/octet-stream")

    return app


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="voice-forge subprocess backend shim — child-process entrypoint",
    )
    parser.add_argument("backend_name", help="Backend to host (e.g. 'piper')")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args(argv)

    logging.basicConfig(level=os.environ.get("VOICE_FORGE_LOG_LEVEL", "INFO").upper())
    app = build_app(args.backend_name)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
