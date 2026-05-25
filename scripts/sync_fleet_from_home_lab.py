#!/usr/bin/env python3
"""Sync the Asgard fleet manifest from infiquetra/home-lab into tests/functional/fleet.yaml.

Reads ``ansible/roles/hermes_neutts_daemon/defaults/main.yml`` from the home-lab
checkout (path passed via ``--home-lab-path``), extracts
``neutts_daemon_personas``, and writes ``tests/functional/fleet.yaml`` with
unique Norse-god targets assigned per sister.

The fleet.yaml is **generated** — do not hand-edit. Re-run this script when
home-lab adds/removes sisters (or when you want to refresh target assignments).

Usage:
    python scripts/sync_fleet_from_home_lab.py \\
        --home-lab-path ~/workspace/infiquetra/home-lab
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml

# Output path is fixed relative to this script's grandparent (repo root).
REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_PATH = REPO_ROOT / "tests" / "functional" / "fleet.yaml"

# Path inside the home-lab repo where the persona list lives.
PERSONAS_RELPATH = Path("ansible/roles/hermes_neutts_daemon/defaults/main.yml")
PERSONAS_KEY = "neutts_daemon_personas"

# Male Norse deities for target_agent assignment. We pull in fleet order so
# the assignment is deterministic. Must be at least len(fleet) long; expand
# this pool if home-lab grows beyond 9 sisters.
NORSE_TARGETS = [
    "Thor",
    "Loki",
    "Odin",
    "Heimdall",
    "Tyr",
    "Baldur",
    "Bragi",
    "Vidar",
    "Vali",
    "Forseti",
    "Hodr",
    "Ull",
]


def _display_name_from_description(description: str) -> str:
    """'Freya — team lead (V3 prompt voice)' → 'Freya'."""
    # The home-lab convention: persona description starts with the capitalized
    # Norse name, followed by ' — ' and a role description.
    return description.split("—")[0].strip().split()[0]


def _load_personas(home_lab_path: Path) -> list[dict[str, str]]:
    personas_file = home_lab_path / PERSONAS_RELPATH
    if not personas_file.is_file():
        raise SystemExit(
            f"error: expected home-lab persona file at {personas_file}, but it does not exist. "
            f"Pass --home-lab-path pointing at a valid checkout of infiquetra/home-lab."
        )
    with personas_file.open() as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict) or PERSONAS_KEY not in data:
        raise SystemExit(f"error: {personas_file} does not contain top-level key {PERSONAS_KEY!r}.")
    personas = data[PERSONAS_KEY]
    if not isinstance(personas, list) or not personas:
        raise SystemExit(f"error: {PERSONAS_KEY} in {personas_file} is empty or not a list.")
    return personas


def _build_fleet(personas: list[dict[str, str]]) -> list[dict[str, Any]]:
    if len(personas) > len(NORSE_TARGETS):
        raise SystemExit(
            f"error: fleet has {len(personas)} sisters but only {len(NORSE_TARGETS)} "
            f"Norse target names are available. Expand NORSE_TARGETS in this script."
        )
    fleet: list[dict[str, Any]] = []
    for persona, target in zip(personas, NORSE_TARGETS, strict=False):
        profile = persona.get("profile")
        description = persona.get("description", "")
        if not profile or not description:
            raise SystemExit(f"error: persona entry is missing profile or description: {persona!r}")
        fleet.append(
            {
                "id": profile.split("-")[0],  # 'freya-pa' → 'freya'
                "display_name": _display_name_from_description(description),
                "voice_id": profile,
                "backend": "neutts",
                "target_agent": target,
                "description": description,
            }
        )
    return fleet


def _validate_unique_targets(fleet: list[dict[str, Any]]) -> None:
    targets = [row["target_agent"] for row in fleet]
    if len(set(targets)) != len(targets):
        raise SystemExit(f"error: target_agent uniqueness violated; targets are {targets!r}")


def _write_fleet(fleet: list[dict[str, Any]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    header = (
        "# GENERATED — do not hand-edit. Re-run scripts/sync_fleet_from_home_lab.py\n"
        "# Source: infiquetra/home-lab\n"
        "#   ansible/roles/hermes_neutts_daemon/defaults/main.yml :: "
        "neutts_daemon_personas\n"
        "#\n"
        "# To refresh after home-lab adds/removes sisters:\n"
        "#   python scripts/sync_fleet_from_home_lab.py "
        "--home-lab-path ~/workspace/infiquetra/home-lab\n"
        "\n"
    )
    body = yaml.safe_dump(fleet, sort_keys=False, default_flow_style=False, allow_unicode=True)
    output_path.write_text(header + body)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--home-lab-path",
        type=Path,
        required=True,
        help="Path to a checkout of infiquetra/home-lab (e.g. ~/workspace/infiquetra/home-lab).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=OUTPUT_PATH,
        help=f"Output path for the fleet manifest (default: {OUTPUT_PATH})",
    )
    args = parser.parse_args(argv)

    home_lab_path = args.home_lab_path.expanduser().resolve()
    if not home_lab_path.is_dir():
        raise SystemExit(f"error: --home-lab-path {home_lab_path} is not a directory.")

    personas = _load_personas(home_lab_path)
    fleet = _build_fleet(personas)
    _validate_unique_targets(fleet)
    _write_fleet(fleet, args.output)

    print(
        f"wrote {len(fleet)} sister(s) to {args.output} (targets: "
        f"{', '.join(r['target_agent'] for r in fleet)})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
