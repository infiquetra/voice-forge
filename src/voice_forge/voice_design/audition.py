"""Voice Design audition orchestrator: generate previews → pick → persist.

Bridges :mod:`voice_forge.voice_design.elevenlabs` (the REST API),
:mod:`voice_forge.voice_design.prompt_builder` (the structured spec
→ Voice Design prompt translation), and the user's pick.

Two pick modes:
- **interactive** (default): saves previews to ``out_dir/<voice_id>/{1,2,3}.mp3``,
  prompts on stdin for the choice, returns the selection.
- **auto**: takes the first preview without listening — useful when
  shipping a whole fleet and tuning cosmetics later.

The chosen preview is then persisted via ``create_voice_from_preview``
and the new permanent ``voice_id`` is returned (this is what gets
written back to fleet.yaml under ``elevenlabs_voice_id``).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .elevenlabs import Preview, create_voice_from_preview, create_voice_previews
from .fleet import PersonaSpec
from .prompt_builder import build_voice_design_prompt

logger = logging.getLogger("voice_forge.voice_design.audition")

# Callback signature for swapping the picker — useful in tests + the CLI.
PickerFn = Callable[[list[Path], list[Preview]], int | None]

# Manifest filename written alongside the preview MP3s so a later
# ``persist`` call can find each preview's ephemeral generated_voice_id
# without having to re-call create-previews (which would re-bill).
PREVIEWS_MANIFEST = "previews.json"


@dataclass(frozen=True)
class AuditionResult:
    """Outcome of a single persona audition."""

    voice_id: str
    persisted_voice_id: str | None  # None = skipped/regenerated/cancelled
    chosen_index: int | None
    chosen_audio_path: Path | None
    description: str
    sample_text: str


def _save_previews(
    persona_id: str,
    previews: list[Preview],
    out_dir: Path,
    *,
    display_name: str = "",
    description: str = "",
    sample_text: str = "",
) -> list[Path]:
    """Persist each preview to disk + a JSON manifest. Returns audio paths.

    The manifest at ``out_dir/<persona_id>/previews.json`` carries each
    preview's ephemeral ``generated_voice_id`` alongside its MP3 path,
    plus the prompt context (description, sample_text). Two callers need
    this:
      1. :func:`audition_persona` (interactive) — could just hold the
         Preview objects in memory.
      2. The CLI's ``persist`` subcommand — runs in a separate process
         from the original audition, so it needs the IDs on disk to
         finalize a user-chosen preview without re-billing for new ones.
    """
    persona_dir = out_dir / persona_id
    persona_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    manifest_previews: list[dict] = []
    for i, p in enumerate(previews, start=1):
        path = persona_dir / f"{i}.mp3"
        path.write_bytes(p.audio)
        paths.append(path)
        manifest_previews.append(
            {"index": i, "generated_voice_id": p.generated_voice_id, "audio": path.name}
        )
    manifest = {
        "persona_id": persona_id,
        "display_name": display_name,
        "description": description,
        "sample_text": sample_text,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "previews": manifest_previews,
    }
    (persona_dir / PREVIEWS_MANIFEST).write_text(json.dumps(manifest, indent=2))
    return paths


def pick_interactive(paths: list[Path], previews: list[Preview]) -> int | None:
    """Prompt the user on stdin. Returns chosen index (1-based) or None.

    Returns None for 'r' (regenerate) and 's' (skip); the caller decides
    what to do (loop and re-audition, or move on). The distinction lives
    one level up — :func:`audition_persona` interprets it.
    """
    print("\n  previews saved:")
    for path in paths:
        print(f"    {path}")
    while True:
        choice = input(f"  pick 1-{len(paths)}, 'r' regenerate, 's' skip: ").strip().lower()
        if choice in ("s", "r"):
            return None
        if choice.isdigit() and 1 <= int(choice) <= len(paths):
            return int(choice)
        print(f"  unrecognized: {choice!r}")


def pick_auto(paths: list[Path], previews: list[Preview]) -> int | None:
    """Auto-pick the first preview (always returns 1)."""
    print("  --auto: taking preview 1 without listening")
    return 1


def audition_persona(
    spec: PersonaSpec,
    *,
    out_dir: Path,
    api_key: str | None = None,
    picker: PickerFn = pick_interactive,
    regen_budget: int = 3,
    sample_text_override: str | None = None,
) -> AuditionResult:
    """Run a full Voice Design audition for one persona.

    Flow:
      1. Build the prompt from ``spec`` (best-practices ordering applied).
      2. Call create-previews; save MP3s to ``out_dir/<voice_id>/``.
      3. Run ``picker`` to choose one (interactive or auto).
      4. If picked, persist via create-voice-from-preview.
      5. If picker returned None and we have regen budget left, re-audition.
      6. Otherwise return a result with ``persisted_voice_id=None``.

    The caller is responsible for writing ``persisted_voice_id`` back
    into the fleet config — this function doesn't mutate the fleet.
    """
    description = build_voice_design_prompt(spec.design_spec())
    sample_text = sample_text_override or spec.sample_text
    if not sample_text:
        raise ValueError(f"persona {spec.voice_id!r} has no sample_text and no override given")

    attempts_left = max(1, regen_budget)
    while attempts_left > 0:
        print(f"\n[{spec.voice_id}] auditioning (attempts left: {attempts_left})…")
        previews = create_voice_previews(description, sample_text, api_key=api_key)
        if not previews:
            logger.warning("ElevenLabs returned no previews for %s", spec.voice_id)
            return AuditionResult(
                voice_id=spec.voice_id,
                persisted_voice_id=None,
                chosen_index=None,
                chosen_audio_path=None,
                description=description,
                sample_text=sample_text,
            )
        paths = _save_previews(
            spec.voice_id,
            previews,
            out_dir,
            display_name=spec.display_name,
            description=description,
            sample_text=sample_text,
        )
        choice = picker(paths, previews)
        if choice is not None:
            picked = previews[choice - 1]
            print(f"[{spec.voice_id}] persisting {paths[choice - 1]}…")
            persisted = create_voice_from_preview(
                voice_name=spec.display_name,
                description=description,
                generated_voice_id=picked.generated_voice_id,
                api_key=api_key,
            )
            print(f"[{spec.voice_id}] ✓ voice_id = {persisted}")
            return AuditionResult(
                voice_id=spec.voice_id,
                persisted_voice_id=persisted,
                chosen_index=choice,
                chosen_audio_path=paths[choice - 1],
                description=description,
                sample_text=sample_text,
            )
        attempts_left -= 1
        if attempts_left:
            print(f"[{spec.voice_id}] regenerating ({attempts_left} attempts left)…")

    return AuditionResult(
        voice_id=spec.voice_id,
        persisted_voice_id=None,
        chosen_index=None,
        chosen_audio_path=None,
        description=description,
        sample_text=sample_text,
    )


def generate_previews_only(
    spec: PersonaSpec,
    *,
    out_dir: Path,
    api_key: str | None = None,
    sample_text_override: str | None = None,
) -> AuditionResult:
    """Generate Voice Design previews + write to disk, NO pick/persist.

    Use this when the audition needs to run in a non-interactive context
    (CI, background agent, etc.). The caller listens to the saved MP3s
    out-of-band, then runs :func:`persist_preview` with their chosen
    index to finalize.

    Same billing as a normal audition (3 previews × sample_text chars).
    Returns an AuditionResult with ``persisted_voice_id=None`` and
    ``chosen_index=None`` — the caller knows it must follow up.
    """
    description = build_voice_design_prompt(spec.design_spec())
    sample_text = sample_text_override or spec.sample_text
    if not sample_text:
        raise ValueError(f"persona {spec.voice_id!r} has no sample_text and no override given")
    print(f"\n[{spec.voice_id}] generating previews (save-only mode)…")
    previews = create_voice_previews(description, sample_text, api_key=api_key)
    if not previews:
        logger.warning("ElevenLabs returned no previews for %s", spec.voice_id)
        return AuditionResult(
            voice_id=spec.voice_id,
            persisted_voice_id=None,
            chosen_index=None,
            chosen_audio_path=None,
            description=description,
            sample_text=sample_text,
        )
    paths = _save_previews(
        spec.voice_id,
        previews,
        out_dir,
        display_name=spec.display_name,
        description=description,
        sample_text=sample_text,
    )
    print(f"[{spec.voice_id}] {len(paths)} previews saved:")
    for path in paths:
        print(f"  {path}")
    print(f"[{spec.voice_id}] manifest: {out_dir / spec.voice_id / PREVIEWS_MANIFEST}")
    print(
        f"[{spec.voice_id}] listen, then run "
        f"`voice_design persist --persona {spec.voice_id} --preview <N>` to finalize"
    )
    return AuditionResult(
        voice_id=spec.voice_id,
        persisted_voice_id=None,
        chosen_index=None,
        chosen_audio_path=None,
        description=description,
        sample_text=sample_text,
    )


def persist_preview(
    spec: PersonaSpec,
    preview_index: int,
    *,
    out_dir: Path,
    api_key: str | None = None,
) -> AuditionResult:
    """Finalize a save-only audition by persisting one of the saved previews.

    Reads ``out_dir/<spec.voice_id>/previews.json`` to look up the
    ephemeral ``generated_voice_id`` for ``preview_index`` (1-based),
    calls create-voice-from-preview, and returns the resulting permanent
    ``voice_id``. Caller writes it back into fleet.yaml.

    Raises ``FileNotFoundError`` if no manifest exists for this persona,
    ``IndexError`` if ``preview_index`` is out of range.
    """
    persona_dir = out_dir / spec.voice_id
    manifest_path = persona_dir / PREVIEWS_MANIFEST
    if not manifest_path.is_file():
        raise FileNotFoundError(
            f"no previews manifest at {manifest_path}; run audition with --save-only first"
        )
    manifest = json.loads(manifest_path.read_text())
    previews = manifest.get("previews") or []
    if not 1 <= preview_index <= len(previews):
        raise IndexError(
            f"preview index {preview_index} out of range; manifest has {len(previews)} previews"
        )
    chosen = previews[preview_index - 1]
    gen_id = chosen["generated_voice_id"]
    audio_path = persona_dir / chosen["audio"]
    description = manifest.get("description") or build_voice_design_prompt(spec.design_spec())
    sample_text = manifest.get("sample_text") or spec.sample_text

    print(f"[{spec.voice_id}] persisting preview {preview_index} ({audio_path})…")
    persisted = create_voice_from_preview(
        voice_name=spec.display_name,
        description=description,
        generated_voice_id=gen_id,
        api_key=api_key,
    )
    print(f"[{spec.voice_id}] ✓ voice_id = {persisted}")
    return AuditionResult(
        voice_id=spec.voice_id,
        persisted_voice_id=persisted,
        chosen_index=preview_index,
        chosen_audio_path=audio_path,
        description=description,
        sample_text=sample_text,
    )
