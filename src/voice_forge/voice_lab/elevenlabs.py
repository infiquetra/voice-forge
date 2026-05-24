"""ElevenLabs Voice Lab puller.

Fetches the FROZEN preview MP3 (not fresh synthesis) so we get the original
accent that the Voice Design generated. Fresh synthesis strips the accent —
this is the workaround discovered during the home-lab NeuTTS investigation
(see narratives/2026-05-24-voice-forge-spin-out.md in home-lab).
"""

from __future__ import annotations

import os
from pathlib import Path


def pull_preview(voice_id: str, api_key: str | None = None) -> Path:
    """Download the Voice Lab preview MP3 for a given ElevenLabs voice.

    Args:
        voice_id: ElevenLabs voice_id (e.g., "c7qAAWgc7aGYHCLDzd8Y")
        api_key: ElevenLabs API key. Falls back to env ELEVENLABS_API_KEY.

    Returns:
        Path to the downloaded MP3 in /tmp.

    Raises:
        ValueError: if no API key found.
        httpx.HTTPError: on API failure.
    """
    # TODO Phase D: port regenerate_freya_v2_ref.py from home-lab
    raise NotImplementedError
