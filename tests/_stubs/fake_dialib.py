"""Fake `transformers` Dia classes for DiaBackend unit tests.

DiaBackend imports `from transformers import AutoProcessor, DiaForConditionalGeneration`
inside `load()`. We monkeypatch those two names directly on the real
`transformers` module so tests don't need a 1.6 GB model download.

This is a slightly different pattern from fake_neuttslib / fake_f5lib because
transformers is already imported (the test runner has it loaded for fastapi
plumbing). Replacing `sys.modules["transformers"]` would break everything
else; instead we just swap the two specific class names.
"""

from __future__ import annotations

import torch

DIA_NATIVE_RATE = 44_100


class FakeDiaModel:
    """Stand-in for ``DiaForConditionalGeneration``. Returns a fake token tensor."""

    @classmethod
    def from_pretrained(cls, model_name: str, **kwargs) -> FakeDiaModel:
        inst = cls()
        inst.model_name = model_name
        return inst

    def to(self, device: str) -> FakeDiaModel:
        self.device = device
        return self

    def generate(self, **kwargs) -> torch.Tensor:
        """Return a fake token tensor. Records the kwargs for test inspection."""
        self.last_generate_kwargs = kwargs
        # Shape doesn't matter — processor.batch_decode is also faked.
        return torch.zeros((1, 100), dtype=torch.long)


class FakeDiaProcessor:
    """Stand-in for the AutoProcessor instance Dia loads."""

    @classmethod
    def from_pretrained(cls, model_name: str, **kwargs) -> FakeDiaProcessor:
        inst = cls()
        inst.model_name = model_name
        return inst

    def __call__(self, text, audio=None, padding=True, return_tensors="pt", **kwargs):
        """Mimic DiaProcessor.__call__; returns an obj with .to() chainable."""
        self.last_call_text = text
        self.last_call_audio = audio
        # Return a tiny inputs-like object that has .to() and the attrs
        # that the backend pulls out.
        return _FakeInputs(decoder_attention_mask=torch.zeros((1, 50), dtype=torch.long))

    def get_audio_prompt_len(self, decoder_attention_mask, **kwargs) -> int:
        return 10

    def batch_decode(
        self, decoder_input_ids: torch.Tensor, audio_prompt_len: int | None = None, **kwargs
    ) -> list[torch.Tensor]:
        """Return 0.5s of silence at 44.1 kHz, as a single-element list."""
        return [torch.zeros(int(DIA_NATIVE_RATE * 0.5), dtype=torch.float32)]


class _FakeInputs:
    """Object that mimics the BatchFeature returned by the processor."""

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)
        self._kwargs = kwargs

    def to(self, device: str) -> _FakeInputs:
        self.device = device
        return self

    def keys(self):
        return self._kwargs.keys()

    def __getitem__(self, key):
        return self._kwargs[key]

    # Make **inputs work in generate(**inputs):
    def __iter__(self):
        return iter(self._kwargs)


def install(monkeypatch) -> None:
    """Monkeypatch the transformers Dia exports + force backend module re-import."""
    import sys

    import transformers

    monkeypatch.setattr(transformers, "AutoProcessor", FakeDiaProcessor)
    monkeypatch.setattr(transformers, "DiaForConditionalGeneration", FakeDiaModel)
    # If the backend module is already imported in this pytest session,
    # evict it so the lazy `from transformers import ...` inside load() re-runs.
    monkeypatch.delitem(sys.modules, "voice_forge.backends.dia", raising=False)
