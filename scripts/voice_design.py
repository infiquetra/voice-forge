#!/usr/bin/env python3
"""voice_design.py — CLI for the Voice Design pipeline.

Subcommands:
  audition — Run ElevenLabs Voice Design for one or more personas in a
             fleet.yaml. Interactive pick-of-3 (or --auto to take 1 each).
             Writes the chosen elevenlabs_voice_id back into fleet.yaml.

  regen   — Re-render the reference WAV for an already-auditioned
             persona using its existing elevenlabs_voice_id +
             sample_text (or --text override). Writes the new audio to
             personas/<fleet>/<voice_id>/ref.wav. Useful when the
             current ref is bandwidth-limited or the underlying
             ElevenLabs voice changed.

  show    — Print the Voice Design prompt that would be sent for a
             persona (no API calls). Useful for sanity-checking the
             best-practices ordering before spending an audition slot.

  list    — List personas in the fleet with their audition status +
             ref-file presence.

Auth: reads ELEVENLABS_API_KEY from the environment. The audition path
fails fast if it's missing; show/list don't need it.

Examples:
    export ELEVENLABS_API_KEY=sk-...
    python scripts/voice_design.py list --fleet personas/asgard/fleet.yaml
    python scripts/voice_design.py show --fleet personas/asgard/fleet.yaml --persona freya-pa
    python scripts/voice_design.py audition \\
        --fleet personas/asgard/fleet.yaml --persona mimir-engineer
    python scripts/voice_design.py regen \\
        --fleet personas/asgard/fleet.yaml --persona freya-pa
"""

from __future__ import annotations

import argparse
import os
import sys
import wave
from pathlib import Path

import yaml

# Allow running this script without installing voice-forge by adding the
# project's src/ to sys.path. Works for `python scripts/voice_design.py …`
# from the repo root; harmless when voice-forge is pip-installed.
_HERE = Path(__file__).resolve().parent
_SRC = _HERE.parent / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from voice_forge.voice_design import (  # noqa: E402
    Fleet,
    PersonaSpec,
    audition_persona,
    build_voice_design_prompt,
    load_fleet,
    pick_auto,
    pick_interactive,
    text_to_speech,
)

AUDIT_DEFAULT_DIR = Path.home() / "voice-design-auditions"


def _select_personas(fleet: Fleet, args: argparse.Namespace) -> list[PersonaSpec]:
    """Resolve --persona / --all flags into a concrete persona list."""
    if args.all:
        return list(fleet.personas)
    selected: list[PersonaSpec] = []
    for ident in args.persona or []:
        # Accept either voice_id or display_name
        try:
            selected.append(fleet.by_voice_id(ident))
        except KeyError:
            try:
                selected.append(fleet.by_display_name(ident))
            except KeyError as e:
                sys.exit(str(e))
    if not selected:
        sys.exit("must specify --persona <id> (repeatable) or --all")
    return selected


def _write_back_fleet(fleet_yaml: Path, voice_id: str, persisted_id: str) -> None:
    """Update fleet.yaml in place — sets elevenlabs_voice_id for ``voice_id``.

    Uses yaml.safe_load/safe_dump round-trip. This preserves the persona
    ordering and most of the formatting; multi-line strings (sample_text)
    will be re-emitted in YAML's chosen block-scalar form. That's fine for
    our use case but if you've hand-formatted the YAML, diff before commit.
    """
    raw = yaml.safe_load(fleet_yaml.read_text()) or {}
    rows = raw.get("personas") or []
    found = False
    for row in rows:
        if isinstance(row, dict) and row.get("voice_id") == voice_id:
            row["elevenlabs_voice_id"] = persisted_id
            found = True
            break
    if not found:
        sys.exit(f"voice_id {voice_id!r} not found in {fleet_yaml} — refusing to write back")
    fleet_yaml.write_text(
        yaml.safe_dump(
            raw, sort_keys=False, allow_unicode=True, width=1000, default_flow_style=False
        )
    )
    print(f"  ↳ fleet.yaml updated: {voice_id}.elevenlabs_voice_id = {persisted_id}")


# ----- subcommand: list -----


def cmd_list(args: argparse.Namespace) -> int:
    fleet = load_fleet(Path(args.fleet))
    print(f"fleet: {fleet.root}")
    print(f"personas: {len(fleet.personas)}\n")
    print(f"  {'voice_id':<22} {'display':<12} {'audition':<22} {'ref':<6}")
    print("  " + "-" * 70)
    for p in fleet.personas:
        eid = p.elevenlabs_voice_id or "(awaiting)"
        ref = "✓" if p.has_ref_audio() else "—"
        print(f"  {p.voice_id:<22} {p.display_name:<12} {eid:<22} {ref:<6}")
    return 0


# ----- subcommand: show -----


def cmd_show(args: argparse.Namespace) -> int:
    fleet = load_fleet(Path(args.fleet))
    personas = _select_personas(fleet, args)
    for p in personas:
        prompt = build_voice_design_prompt(p.design_spec())
        print(f"\n=== {p.voice_id} ({p.display_name}) — len={len(prompt)} chars ===\n")
        print(prompt)
        print(f"\n--- sample_text ({len(p.sample_text)} chars) ---\n")
        print(p.sample_text.strip())
    return 0


# ----- subcommand: audition -----


def cmd_audition(args: argparse.Namespace) -> int:
    fleet_path = Path(args.fleet).expanduser().resolve()
    fleet = load_fleet(fleet_path)
    personas = _select_personas(fleet, args)
    out_dir = Path(args.out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    picker = pick_auto if args.auto else pick_interactive

    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        sys.exit("ELEVENLABS_API_KEY env var required for audition")

    results: list[tuple[str, str | None]] = []
    for spec in personas:
        try:
            res = audition_persona(
                spec,
                out_dir=out_dir,
                api_key=api_key,
                picker=picker,
                regen_budget=args.regen_budget,
                sample_text_override=args.text,
            )
        except KeyboardInterrupt:
            print(f"\n[{spec.voice_id}] interrupted — moving on")
            results.append((spec.voice_id, None))
            continue
        results.append((spec.voice_id, res.persisted_voice_id))
        if res.persisted_voice_id and not args.dry_run_writeback:
            _write_back_fleet(fleet_path, spec.voice_id, res.persisted_voice_id)

    print("\n=== summary ===")
    for vid, persisted in results:
        print(f"  {vid}: {persisted or '(skipped)'}")
    return 0 if all(p for _, p in results) else 1


# ----- subcommand: regen -----


def _pcm24k_to_wav(pcm_bytes: bytes, out_path: Path, sample_rate: int = 24000) -> None:
    """Wrap raw signed-16-bit PCM at ``sample_rate`` in a WAV header."""
    n_samples = len(pcm_bytes) // 2  # int16 = 2 bytes/sample
    with wave.open(str(out_path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm_bytes)
    # Sanity log
    print(f"  ↳ wrote {out_path} ({n_samples} samples = {n_samples / sample_rate:.2f}s)")


def cmd_regen(args: argparse.Namespace) -> int:
    fleet = load_fleet(Path(args.fleet))
    personas = _select_personas(fleet, args)
    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        sys.exit("ELEVENLABS_API_KEY env var required for regen")

    for spec in personas:
        if not spec.elevenlabs_voice_id:
            print(f"[{spec.voice_id}] no elevenlabs_voice_id — run `audition` first")
            continue
        text = args.text or spec.sample_text
        if not text:
            print(f"[{spec.voice_id}] no sample_text in fleet and no --text given; skipping")
            continue
        print(
            f"\n[{spec.voice_id}] regen via voice_id={spec.elevenlabs_voice_id}, {len(text)} chars"
        )
        pcm = text_to_speech(
            voice_id=spec.elevenlabs_voice_id,
            text=text,
            api_key=api_key,
            output_format="pcm_24000",
        )
        target = spec.ref_audio
        target.parent.mkdir(parents=True, exist_ok=True)
        _pcm24k_to_wav(pcm, target)
        # Also write ref.txt — what we actually asked it to say.
        # Strip leading/trailing whitespace so F5's text-alignment isn't
        # thrown off by indent artifacts from the YAML block scalar.
        spec.ref_text.parent.mkdir(parents=True, exist_ok=True)
        spec.ref_text.write_text(text.strip() + "\n")
        print(f"  ↳ wrote {spec.ref_text}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    common_persona = argparse.ArgumentParser(add_help=False)
    g = common_persona.add_mutually_exclusive_group(required=True)
    g.add_argument(
        "--persona",
        action="append",
        help="Persona voice_id or display_name (repeatable)",
    )
    g.add_argument("--all", action="store_true", help="Apply to every persona in the fleet")

    p_list = sub.add_parser("list", help="List personas + audition status")
    p_list.add_argument("--fleet", required=True, help="Path to fleet.yaml")
    p_list.set_defaults(func=cmd_list)

    p_show = sub.add_parser(
        "show", parents=[common_persona], help="Print the Voice Design prompt for a persona"
    )
    p_show.add_argument("--fleet", required=True, help="Path to fleet.yaml")
    p_show.set_defaults(func=cmd_show)

    p_audition = sub.add_parser(
        "audition", parents=[common_persona], help="Voice Design audition + persist"
    )
    p_audition.add_argument("--fleet", required=True, help="Path to fleet.yaml")
    p_audition.add_argument(
        "--out-dir",
        default=str(AUDIT_DEFAULT_DIR),
        help=f"Where to save preview MP3s (default: {AUDIT_DEFAULT_DIR})",
    )
    p_audition.add_argument(
        "--auto",
        action="store_true",
        help="Auto-pick first preview without prompting (useful for batch)",
    )
    p_audition.add_argument(
        "--regen-budget", type=int, default=3, help="Max audition re-rolls per persona"
    )
    p_audition.add_argument(
        "--text",
        help="Override sample_text — same text used for all selected personas",
    )
    p_audition.add_argument(
        "--dry-run-writeback",
        action="store_true",
        help="Persist voice via ElevenLabs but do NOT write voice_id back to fleet.yaml",
    )
    p_audition.set_defaults(func=cmd_audition)

    p_regen = sub.add_parser(
        "regen",
        parents=[common_persona],
        help="Re-render ref.wav from an already-auditioned voice",
    )
    p_regen.add_argument("--fleet", required=True, help="Path to fleet.yaml")
    p_regen.add_argument(
        "--text",
        help="Override sample_text — useful for shorter / different ref content",
    )
    p_regen.set_defaults(func=cmd_regen)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    sys.exit(main())
