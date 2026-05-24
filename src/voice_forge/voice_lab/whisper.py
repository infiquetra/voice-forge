"""Whisper-based ref WAV refinement (transcribe + sentence-boundary trim).

The trim_to_sentence_boundary function is the key insight from home-lab's
NeuTTS investigation: saga's voice initially produced garbage because her ref WAV
was Whisper-transcribed at a 10s cap that hit mid-sentence. Trimming to the last
".!?" boundary within the cap fixed the cloning quality entirely.
"""

from __future__ import annotations

from pathlib import Path


def transcribe(wav_path: Path | str, language: str = "en") -> str:
    """Transcribe a WAV file via faster-whisper. Forces language to skip auto-detect.

    Auto-detect mis-flags Norwegian-accented English as Swedish/Norwegian
    (see home-lab LEARNINGS 2026-05-24). Always pass language explicitly.
    """
    # TODO Phase D: faster_whisper.WhisperModel("base").transcribe(...)
    raise NotImplementedError


def trim_to_sentence_boundary(
    wav_path: Path | str,
    max_seconds: float = 14.0,
    language: str = "en",
) -> tuple[Path, str]:
    """Trim a WAV to the last complete sentence within max_seconds.

    Process:
      1. Transcribe full WAV with segment timestamps
      2. Find segments ending in ".!?"
      3. Pick the LAST one that ends before max_seconds
      4. ffmpeg-trim WAV to that segment's end timestamp
      5. Return (trimmed_path, matching_text)

    Returns:
        (trimmed_wav_path, ref_text matching the trimmed audio)
    """
    # TODO Phase D: port regen_saga_ref_clean.py from home-lab
    raise NotImplementedError
