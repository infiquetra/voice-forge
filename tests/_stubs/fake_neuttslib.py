"""Fake `neutts` + `llama_cpp` modules for NeuTTS backend tests.

NeuTTSBackend does ``from neutts import NeuTTS`` and ``from llama_cpp import Llama``
**inside function bodies** (lazy imports to avoid hard-deping on those packages).
The right way to test the body is to pre-inject fake modules into ``sys.modules``
BEFORE the backend imports them — module-attribute monkeypatching wouldn't catch
the lazy import paths.

Usage:

    def test_something(monkeypatch):
        from tests._stubs.fake_neuttslib import install
        install(monkeypatch)
        from voice_forge.backends.neutts import NeuTTSBackend
        backend = NeuTTSBackend()
        backend.load({})
        ...
"""

from __future__ import annotations

import sys
import types

import numpy as np

SAMPLE_RATE = 24_000


class FakeNeuTTS:
    """Stand-in for ``neutts.NeuTTS``. Produces deterministic silence.

    ``_load_backbone`` is a real (unbound) method so the patching code in
    ``_apply_neutts_patches`` can swap it for a wrapper without TypeErrors.
    """

    def __init__(self, *args, **kwargs):
        self.watermarker = "fake-watermarker"  # set non-None so the disable-step has work to do
        self.max_context = None

    def _load_backbone(self, backbone_repo, backbone_device):
        # Patched in real use; here we don't actually load anything.
        return None

    def encode_reference(self, ref_audio_path):
        # Deterministic short code list.
        return [10, 20, 30]

    def infer(self, text, codes, ref_text):
        # ~0.5 second of silence.
        return np.zeros(int(SAMPLE_RATE * 0.5), dtype=np.float32)

    def infer_stream(self, text, codes, ref_text):
        # 3 chunks × 0.1 second each.
        for _ in range(3):
            yield np.zeros(int(SAMPLE_RATE * 0.1), dtype=np.float32)


class FakeLlama:
    """Stand-in for ``llama_cpp.Llama``. The patches read ``Llama.__call__``."""

    def __call__(self, *args, **kwargs):
        return None


def install(monkeypatch) -> None:
    """Inject fake `neutts` + `llama_cpp` modules into sys.modules.

    Also clears any pre-existing patches on the fake classes so each test
    starts from a clean state — the patches set ``_voice_forge_patched``
    attributes that would otherwise leak between tests.
    """
    # Reset patch flags so the patches re-run in each test.
    for attr in ("_load_backbone",):
        method = getattr(FakeNeuTTS, attr, None)
        if method is not None and hasattr(method, "_voice_forge_patched"):
            delattr(method, "_voice_forge_patched")
    if hasattr(FakeLlama.__call__, "_voice_forge_patched"):
        try:
            delattr(FakeLlama.__call__, "_voice_forge_patched")
        except AttributeError:
            pass

    fake_neutts = types.ModuleType("neutts")
    fake_neutts.NeuTTS = FakeNeuTTS
    fake_llama = types.ModuleType("llama_cpp")
    fake_llama.Llama = FakeLlama
    monkeypatch.setitem(sys.modules, "neutts", fake_neutts)
    monkeypatch.setitem(sys.modules, "llama_cpp", fake_llama)

    # Force the backend module to re-import so the patches see our fakes.
    # If a prior test already imported it, evict it.
    monkeypatch.delitem(sys.modules, "voice_forge.backends.neutts", raising=False)
