"""Whisper-based ref WAV refinement.

Two operations:

- ``transcribe(wav)`` — get a transcript matching the audio (faster-whisper).
  Always forces language="en" to skip auto-detect; auto-detect mis-flags
  Norwegian-accented English as Swedish/Norwegian (see home-lab LEARNINGS
  2026-05-24).

- ``trim_to_sentence_boundary(wav)`` — find the last complete sentence
  within max_seconds and trim. Critical insight: cloning quality drops
  dramatically when ref_audio extends past ref_text. Trim audio so the
  Whisper-transcribed text matches what the audio ACTUALLY says, with no
  trailing mid-sentence fragments.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

SENTENCE_TERMINATORS = (".", "!", "?")
DEFAULT_MAX_SECONDS = 14.0


@dataclass
class TranscriptSegment:
    """One Whisper segment with start/end timestamps."""

    text: str
    start: float
    end: float


def _find_ffmpeg() -> str:
    """Locate ffmpeg binary; raise RuntimeError if absent."""
    ffmpeg = shutil.which("ffmpeg") or shutil.which("/opt/homebrew/bin/ffmpeg")
    if not ffmpeg:
        raise RuntimeError(
            "ffmpeg not found in PATH. Install via `brew install ffmpeg` (macOS) "
            "or `apt-get install ffmpeg` (Linux)."
        )
    return ffmpeg


def _whisper_model(model_name: str = "base"):
    """Lazy-load faster-whisper. Raises ImportError with install hint."""
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise ImportError(
            "faster-whisper not installed. Install voice-forge with the [voice-lab] "
            "extra: `uv pip install voice-forge[voice-lab]`"
        ) from exc
    # int8 compute is faster on CPU + minimal quality loss
    return WhisperModel(model_name, compute_type="int8")


def transcribe(
    wav_path: Path | str,
    language: str = "en",
    model: str = "base",
) -> str:
    """Transcribe a WAV file. Returns concatenated text (no segment timestamps).

    Use ``segments()`` if you need start/end times.
    """
    segs = segments(wav_path, language=language, model=model)
    return " ".join(s.text.strip() for s in segs).strip()


def segments(
    wav_path: Path | str,
    language: str = "en",
    model: str = "base",
) -> list[TranscriptSegment]:
    """Transcribe and return segment-by-segment timing.

    Args:
        wav_path: input WAV file
        language: ISO 639-1 code; always pass explicitly (auto-detect is unreliable
            for accented English — see home-lab LEARNINGS 2026-05-24).
        model: faster-whisper model size. ``"base"`` is fine for ref-trimming.
    """
    whisper = _whisper_model(model)
    raw_segments, _ = whisper.transcribe(
        str(Path(wav_path).expanduser()),
        language=language,
        beam_size=5,
    )
    return [
        TranscriptSegment(text=seg.text.strip(), start=seg.start, end=seg.end)
        for seg in raw_segments
    ]


def trim_to_sentence_boundary(
    wav_path: Path | str,
    max_seconds: float = DEFAULT_MAX_SECONDS,
    language: str = "en",
    model: str = "base",
    output_path: Path | str | None = None,
) -> tuple[Path, str]:
    """Trim a WAV at the last complete-sentence boundary within ``max_seconds``.

    Process:
        1. Transcribe full WAV with segment timestamps.
        2. Find the LAST segment that ends with .!? AND ends at or before
           ``max_seconds``.
        3. ffmpeg-trim to that segment's end timestamp.
        4. Return ``(trimmed_path, text_matching_trimmed_audio)``.

    Args:
        wav_path: input WAV (any sample rate; output is always 24kHz mono)
        max_seconds: don't include audio past this timestamp
        language: forced Whisper language (don't auto-detect — see LEARNINGS 2026-05-24)
        model: Whisper model size
        output_path: where to write trimmed WAV. If None, replaces input.

    Returns:
        (trimmed_wav_path, matching_text)

    Raises:
        ValueError: no complete sentence found within max_seconds.
    """
    wav_in = Path(wav_path).expanduser()
    if not wav_in.exists():
        raise FileNotFoundError(wav_in)
    segs = segments(wav_in, language=language, model=model)

    # Find the LAST segment ending in .!? that finishes <= max_seconds.
    last_good = None
    for seg in segs:
        if seg.end > max_seconds:
            break
        if seg.text.rstrip().endswith(SENTENCE_TERMINATORS):
            last_good = seg

    if last_good is None:
        raise ValueError(
            f"no complete-sentence boundary found within {max_seconds:.1f}s "
            f"in {wav_in} (transcribed {len(segs)} segments)"
        )

    # Reconstruct matching text from segments 0..last_good_inclusive
    last_idx = segs.index(last_good)
    matching_text = " ".join(s.text.strip() for s in segs[: last_idx + 1]).strip()

    # ffmpeg-trim the WAV
    if output_path is None:
        output_path = wav_in
    output_path = Path(output_path).expanduser()
    if output_path == wav_in:
        # Need a temp path then move into place to avoid ffmpeg read/write conflict
        tmp_out = output_path.with_suffix(".trimmed.wav")
    else:
        tmp_out = output_path

    ffmpeg = _find_ffmpeg()
    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-i",
            str(wav_in),
            "-t",
            str(last_good.end),
            "-ar",
            "24000",
            "-ac",
            "1",
            "-loglevel",
            "error",
            str(tmp_out),
        ],
        check=True,
    )
    if tmp_out != output_path:
        shutil.move(tmp_out, output_path)
    return output_path, matching_text
