#!/usr/bin/env python3
"""One-time bootstrap: persona_prompts.json from responses.yaml.

The audition harness already maintains ``tests/functional/responses.yaml``
with cached per-persona responses to the canonical p1/p2/p3 prompts. The
voice-lab page (/lab) wants the same content under a different schema —
per-persona ``{short, medium, long}`` — so reviewers can speak each length
through any backend.

This script does the one-time conversion. After it runs, edits go through
the /lab UI's PUT /v1/personas/prompts/<persona> endpoint, which writes
back to the same JSON file.

Mapping:
    p1_hear_me     → short  ("Can you hear me?" — the audition's p1 template)
    p2  (response) → medium (~200-300 char persona intro)
    p3  (response) → long   (~1000 char narrative)

Idempotent — re-running with existing prompts only fills in keys that
are missing in the current persona_prompts.json. Use ``--overwrite`` to
replace existing entries.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RESPONSES = REPO_ROOT / "tests" / "functional" / "responses.yaml"
DEFAULT_OUTPUT = REPO_ROOT / "tests" / "functional" / "persona_prompts.json"
SHORT_TEXT = "Can you hear me?"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--responses", type=Path, default=DEFAULT_RESPONSES)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace existing persona entries; default is fill-missing-only",
    )
    args = parser.parse_args(argv)

    if not args.responses.is_file():
        print(f"error: responses file missing at {args.responses}", file=sys.stderr)
        return 1

    responses = yaml.safe_load(args.responses.read_text())
    if not isinstance(responses, dict):
        print(
            f"error: responses.yaml top-level is not a dict (got {type(responses).__name__})",
            file=sys.stderr,
        )
        return 1

    existing: dict[str, dict] = {}
    if args.output.is_file():
        try:
            existing = json.loads(args.output.read_text())
            if not isinstance(existing, dict):
                existing = {}
        except json.JSONDecodeError:
            existing = {}

    now = datetime.now(UTC).isoformat()
    created = 0
    skipped = 0
    for persona_id, persona_data in responses.items():
        if not isinstance(persona_data, dict):
            continue
        if persona_id in existing and not args.overwrite:
            skipped += 1
            continue
        existing[persona_id] = {
            "short": SHORT_TEXT,
            "medium": persona_data.get("p2", "") or "",
            "long": persona_data.get("p3", "") or "",
            "updated_at": now,
        }
        created += 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(existing, indent=2, sort_keys=True))
    print(
        f"wrote {len(existing)} personas to {args.output} "
        f"({created} new, {skipped} skipped existing)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
