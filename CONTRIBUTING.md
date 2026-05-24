# Contributing to voice-forge

Thanks for considering a contribution. This project is in v0 / pre-release, so
the most useful contributions right now are:

1. **New TTS backends** — implement the `TTSBackend` Protocol for F5-TTS, XTTS-v2, Kokoro, Dia, Kitten, MeloTTS, Chatterbox, etc.
2. **Bug reports** with concrete reproductions (text input, voice config, expected vs actual)
3. **Documentation** improvements — particularly the ARCHITECTURE / API_SPEC docs as they evolve

## Getting set up

```bash
git clone https://github.com/infiquetra/voice-forge.git
cd voice-forge
uv venv
source .venv/bin/activate
uv pip install -e ".[dev,neutts,voice-lab]"
voice-forge --help
```

## Adding a new TTS backend

1. Read [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — specifically the `TTSBackend` Protocol section
2. Create `src/voice_forge/backends/<backend_name>.py` with a class implementing the Protocol
3. Handle the `VoiceRef` shape your model needs (see existing `neutts.py` for the `(ref_codes, ref_text)` pattern)
4. Add tests at `tests/unit/backends/test_<backend_name>.py`
5. Update [`docs/ROADMAP.md`](docs/ROADMAP.md) marking your backend as shipped

A good first-backend PR adds Kokoro: it's CPU-only, ships with preset voices (validates the `preset_id` arm of `VoiceRef`), and has a well-defined Python API.

## Engineering journal

This project follows the [LEARNINGS / DECISIONS / QUEUED / ARCHIVE](docs/engineering-journal/README.md) pattern. If you make a non-obvious design decision while implementing something, add it to `docs/engineering-journal/DECISIONS.md` with the standard format. Long-form narratives go under `docs/engineering-journal/narratives/`.

## Code style

- `ruff` for linting + `black` for formatting (config in `pyproject.toml`)
- Type hints encouraged but not strictly required for v0 (will tighten later)
- Async/await throughout (no blocking I/O in request handlers)
- Tests use `pytest` with `pytest-asyncio`

## CI

Push to your branch and the GitHub Actions CI runs ruff, black --check, mypy, and pytest. Green CI is required before merge to `main`.

## License

By contributing, you agree your contributions are licensed under the Apache License 2.0 (the project license). The CLA is implicit via the standard `Signed-off-by` git footer if you want to add one, but it's not required.
