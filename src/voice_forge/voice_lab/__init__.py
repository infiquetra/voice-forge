"""Voice Lab — ref WAV sourcing + refinement utilities.

Two sub-modules:
  - elevenlabs: pull voice previews from ElevenLabs Voice Lab
  - whisper:    transcribe + trim ref WAVs at clean sentence boundaries

Phase D fills out implementations.
"""

from . import elevenlabs as elevenlabs
from . import whisper as whisper
