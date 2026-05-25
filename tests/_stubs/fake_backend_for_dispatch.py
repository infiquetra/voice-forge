"""Test-only backend module. Imported by name to verify load_backend_module's side-effect.

When tests temporarily add ``"fake_dispatch" -> "tests._stubs.fake_backend_for_dispatch"``
to ``_BACKEND_MODULES`` and call ``load_backend_module("fake_dispatch")``, this module's
import-time ``register_backend(...)`` call must run, leaving ``FakeDispatchBackend``
discoverable via ``get_backend("fake_dispatch")``.
"""

from voice_forge.backends import register_backend


class FakeDispatchBackend:
    name = "fake_dispatch"

    def load(self, config: dict) -> None:
        pass

    def encode_reference(self, ref_audio_path: str) -> list | None:
        return None

    def synthesize(self, text, ref):
        return None

    def synthesize_stream(self, text, ref):
        yield None

    def health(self) -> dict:
        return {"name": self.name}


register_backend("fake_dispatch", FakeDispatchBackend)
