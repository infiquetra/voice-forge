"""Fake `TTS.api` module for XTTSBackend unit tests.

XTTSBackend does ``from TTS.api import TTS`` inside ``load()`` (lazy import
to avoid hard-deping on Coqui's heavy install chain). Tests pre-inject this
fake module into ``sys.modules`` so they run without coqui-tts installed.

Usage:

    def test_something(monkeypatch):
        from tests._stubs.fake_xttslib import install
        install(monkeypatch)
        from voice_forge.backends.xtts import XTTSBackend
        backend = XTTSBackend()
        backend.load({})
        ...
"""

from __future__ import annotations

import sys
import types

import numpy as np

SAMPLE_RATE = 24_000


class FakeTTS:
    """Stand-in for ``TTS.api.TTS``. Returns deterministic silence on tts()."""

    def __init__(
        self,
        model_name: str = "",
        *,
        model_path: str | None = None,
        config_path: str | None = None,
        vocoder_name: str | None = None,
        vocoder_path: str | None = None,
        vocoder_config_path: str | None = None,
        encoder_path: str | None = None,
        encoder_config_path: str | None = None,
        speakers_file_path: str | None = None,
        language_ids_file_path: str | None = None,
        progress_bar: bool = True,
        gpu: bool = False,
    ):
        self.model_name = model_name
        self.device: str | None = None
        self.calls: list[dict] = []  # tests can inspect what was passed

    def to(self, device: str) -> FakeTTS:
        """Mimic torch.nn.Module.to() — records the device, returns self."""
        self.device = device
        return self

    def tts(
        self,
        text: str,
        speaker: str | None = None,
        language: str | None = None,
        speaker_wav: str | None = None,
        emotion: str | None = None,
        split_sentences: bool = True,
        **kwargs,
    ):
        """Return a 0.5s silence array at 24kHz."""
        self.calls.append(
            {
                "text": text,
                "speaker_wav": speaker_wav,
                "language": language,
                "split_sentences": split_sentences,
            }
        )
        return np.zeros(int(SAMPLE_RATE * 0.5), dtype=np.float32)


def install(monkeypatch) -> None:
    """Inject the fake TTS package + api submodule into sys.modules."""
    fake_api = types.ModuleType("TTS.api")
    fake_api.TTS = FakeTTS

    fake_pkg = types.ModuleType("TTS")
    fake_pkg.api = fake_api

    monkeypatch.setitem(sys.modules, "TTS", fake_pkg)
    monkeypatch.setitem(sys.modules, "TTS.api", fake_api)
    # Force re-import of the backend module so its lazy `from TTS.api import TTS`
    # picks up our fake the first time it runs in each test.
    monkeypatch.delitem(sys.modules, "voice_forge.backends.xtts", raising=False)
