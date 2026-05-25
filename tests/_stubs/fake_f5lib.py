"""Fake `f5_tts` module for F5Backend unit tests.

F5Backend does ``from f5_tts.api import F5TTS`` inside ``load()`` (lazy import
to avoid hard-deping on heavy torch / diffusion deps). Tests pre-inject this
fake module into ``sys.modules`` so they run without F5-TTS installed.

Usage:

    def test_something(monkeypatch):
        from tests._stubs.fake_f5lib import install
        install(monkeypatch)
        from voice_forge.backends.f5 import F5Backend
        backend = F5Backend()
        backend.load({})
        ...
"""

from __future__ import annotations

import sys
import types

import numpy as np

SAMPLE_RATE = 24_000


class FakeF5TTS:
    """Stand-in for ``f5_tts.api.F5TTS``. Returns deterministic silence."""

    def __init__(
        self,
        model: str = "F5TTS_v1_Base",
        ckpt_file: str = "",
        vocab_file: str = "",
        ode_method: str = "euler",
        use_ema: bool = True,
        vocoder_local_path: str | None = None,
        device: str | None = None,
        hf_cache_dir: str | None = None,
    ):
        self.model = model
        self.device = device or "auto"
        self.calls: list[dict] = []  # tests can inspect what was passed

    def infer(
        self,
        ref_file: str,
        ref_text: str,
        gen_text: str,
        show_info=print,
        progress=None,
        target_rms: float = 0.1,
        cross_fade_duration: float = 0.15,
        sway_sampling_coef: float = -1,
        cfg_strength: float = 2,
        nfe_step: int = 32,
        speed: float = 1.0,
        fix_duration: float | None = None,
        remove_silence: bool = False,
        file_wave: str | None = None,
        file_spec: str | None = None,
        seed: int | None = None,
    ):
        """Return (wav, sr, spec) — 0.5s of silence at 24kHz, dummy spec."""
        self.calls.append(
            {"ref_file": ref_file, "ref_text": ref_text, "gen_text": gen_text, "nfe_step": nfe_step}
        )
        wav = np.zeros(int(SAMPLE_RATE * 0.5), dtype=np.float32)
        spec = np.zeros((80, 100), dtype=np.float32)  # dummy mel-spectrogram
        return wav, SAMPLE_RATE, spec


def install(monkeypatch) -> None:
    """Inject the fake f5_tts package + api submodule into sys.modules."""
    fake_api = types.ModuleType("f5_tts.api")
    fake_api.F5TTS = FakeF5TTS

    fake_pkg = types.ModuleType("f5_tts")
    fake_pkg.api = fake_api

    monkeypatch.setitem(sys.modules, "f5_tts", fake_pkg)
    monkeypatch.setitem(sys.modules, "f5_tts.api", fake_api)
    # Force the backend module to re-import so the lazy `from f5_tts.api import F5TTS`
    # picks up our fake.
    monkeypatch.delitem(sys.modules, "voice_forge.backends.f5", raising=False)
