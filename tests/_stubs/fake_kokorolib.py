"""Fake `kokoro` module for KokoroBackend tests.

KokoroBackend does ``from kokoro import KPipeline`` inside ``load()`` to
defer the heavy torch import. Tests pre-inject this fake module into
``sys.modules`` so they don't need the real ``kokoro`` package (or its
transitive ``torch`` / ``transformers`` deps) installed.

Usage:

    def test_something(monkeypatch):
        from tests._stubs.fake_kokorolib import install
        install(monkeypatch)
        from voice_forge.backends.kokoro import KokoroBackend
        backend = KokoroBackend()
        backend.load({})
        ...
"""

from __future__ import annotations

import sys
import types

import numpy as np

SAMPLE_RATE = 24_000


class FakeKPipeline:
    """Stand-in for ``kokoro.KPipeline``.

    Callable; when called as ``pipeline(text, voice=..., speed=...)``,
    returns a generator yielding one ``(gs, ps, audio)`` tuple per
    "segment". For unit tests we keep this simple and yield a single
    1-second silence chunk so synthesize() / synthesize_stream() can be
    differentiated by chunk-count.
    """

    def __init__(self, lang_code: str = "a", **kwargs):
        self.lang_code = lang_code
        self.call_log: list[dict] = []  # tests can inspect what was passed

    def __call__(self, text: str, voice, speed: float = 1.0, **kwargs):
        self.call_log.append({"text": text, "voice": voice, "speed": speed, **kwargs})
        # Yield two short chunks so synthesize() exercises concatenation
        # and synthesize_stream() exercises iteration.
        for _ in range(2):
            audio = np.zeros(int(SAMPLE_RATE * 0.25), dtype=np.float32)  # 0.25s each
            yield (None, None, audio)


def install(monkeypatch, *, with_espeak_ng: bool = True) -> None:
    """Inject the fake kokoro module + optionally satisfy the espeak-ng pre-flight.

    ``with_espeak_ng=True`` (default) makes ``shutil.which("espeak-ng")``
    return a fake path so ``KokoroBackend.load()`` doesn't bail. Set to
    False to exercise the missing-binary error path.
    """
    fake_kokoro = types.ModuleType("kokoro")
    fake_kokoro.KPipeline = FakeKPipeline
    monkeypatch.setitem(sys.modules, "kokoro", fake_kokoro)
    monkeypatch.delitem(sys.modules, "voice_forge.backends.kokoro", raising=False)

    if with_espeak_ng:
        import shutil as _shutil

        original_which = _shutil.which

        def _fake_which(name, *args, **kwargs):
            if name == "espeak-ng":
                return "/usr/local/bin/espeak-ng"  # any non-None string works
            return original_which(name, *args, **kwargs)

        monkeypatch.setattr(_shutil, "which", _fake_which)
