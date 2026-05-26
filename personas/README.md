# personas/

Per-user persona fleets. Each subdirectory is one fleet (e.g.
`personas/asgard/` is Jeff's Asgard fleet — 9 Norse goddesses + Mimir,
all Voice-Designed against ElevenLabs).

**This directory is NOT installed when voice-forge is `pip install`ed.**
It lives in the repo because it's the dev-side source of truth for the
maintainer's own fleet, but everything under `personas/` is excluded
from the wheel (see `pyproject.toml :: [tool.hatch.build.targets.wheel]`
— only `src/voice_forge/` ships).

## To use your own fleet

You don't put your fleet under `personas/` inside the installed
package. Put it anywhere on your filesystem:

```
~/my-voices/
├── fleet.yaml
└── <voice_id>/
    ├── ref.wav
    └── ref.txt
```

Then point voice-forge's CLI at it:

```bash
voice-design list --fleet ~/my-voices/fleet.yaml
voice-design audition --fleet ~/my-voices/fleet.yaml --persona narrator
```

The schema for `fleet.yaml` is documented in
`src/voice_forge/voice_design/fleet.py` (the docstring on the module).
Best-practices guidance for writing the per-persona Voice Design specs
lives in `docs/voice-design-guide.md`.

## Why `personas/asgard/` is in the repo at all

So the maintainer's own dev workflow doesn't require a separate private
repo or a sibling directory floating loose. It's a working real-world
fleet you can read as an example of the schema.
