"""Voice Lab — ref WAV sourcing + refinement utilities.

Public surface:
    - ``elevenlabs.pull_preview(voice_id)``           pull frozen preview MP3
    - ``elevenlabs.pull_and_prepare(voice_id)``       MP3 + WAV + trim in one shot
    - ``whisper.transcribe(wav)``                     get full transcript
    - ``whisper.trim_to_sentence_boundary(wav, ...)`` sentence-aligned trim
"""

from . import elevenlabs as elevenlabs
from . import whisper as whisper

__all__ = ["elevenlabs", "whisper"]
