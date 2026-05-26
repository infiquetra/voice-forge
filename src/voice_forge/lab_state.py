"""Persistence for the /lab voice tuning workstation.

Two JSON files committed in the repo so edits are diff-able + claude can
read them directly for analysis:

- ``tests/functional/voice_scorecard.json`` — the editable match-against-original
  scorecard, keyed by persona then backend.
- ``tests/functional/persona_prompts.json`` — per-persona text in three lengths
  (short / medium / long) used by the /lab "speak" buttons.

Both files start as ``{}`` when absent. Writes are serialized via a module
Lock so concurrent PUTs from multiple browser tabs don't corrupt the file.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import threading
from pathlib import Path
from typing import Any, Literal

# Lives next to fleet.yaml under tests/functional/ — same repo-relative
# convention that the audition harness uses. Overridable via env vars for
# test sandboxing.
_DEFAULT_BASE = Path("tests/functional")
_SCORECARD_FILENAME = "voice_scorecard.json"
_PROMPTS_FILENAME = "persona_prompts.json"

_SCORECARD_ENV = "VOICE_FORGE_SCORECARD_PATH"
_PROMPTS_ENV = "VOICE_FORGE_PROMPTS_PATH"

_LOCK = threading.Lock()

MatchValue = Literal["yes", "no", "partial"] | None
"""4-state per scorecard cell: yes / no / partial / None (unrated)."""


def _scorecard_path() -> Path:
    return Path(
        os.environ.get(_SCORECARD_ENV, str(_DEFAULT_BASE / _SCORECARD_FILENAME))
    ).expanduser()


def _prompts_path() -> Path:
    return Path(os.environ.get(_PROMPTS_ENV, str(_DEFAULT_BASE / _PROMPTS_FILENAME))).expanduser()


def _read_json(path: Path) -> dict:
    """Read a JSON file; return {} on any read/parse error or missing file."""
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True))


def _now_iso() -> str:
    return _dt.datetime.now(_dt.UTC).isoformat()


# ----- scorecard -----


def read_scorecard() -> dict[str, dict[str, dict]]:
    """Full scorecard. Shape:

    .. code-block:: json

        {
          "saga": {
            "f5":    {"matches_original": "yes", "notes": "...", "updated_at": "..."},
            "neutts": {...}
          }
        }
    """
    return _read_json(_scorecard_path())


def update_scorecard_cell(
    persona: str, backend: str, *, matches_original: MatchValue, notes: str | None
) -> dict:
    """Merge an update into one (persona, backend) cell. Returns the new cell."""
    if not persona or not backend:
        raise ValueError("persona and backend must be non-empty strings")
    with _LOCK:
        data = _read_json(_scorecard_path())
        persona_block = data.setdefault(persona, {})
        cell = persona_block.setdefault(backend, {})
        if matches_original is not None:
            if matches_original not in ("yes", "no", "partial"):
                raise ValueError(
                    f"matches_original must be one of yes/no/partial, got {matches_original!r}"
                )
            cell["matches_original"] = matches_original
        else:
            cell.pop("matches_original", None)
        if notes is not None:
            cell["notes"] = notes
        cell["updated_at"] = _now_iso()
        _write_json(_scorecard_path(), data)
    return cell


# ----- persona prompts -----


def read_persona_prompts() -> dict[str, dict]:
    """Full persona-prompts dict. Shape:

    .. code-block:: json

        {
          "saga": {
            "short": "...",
            "medium": "...",
            "long": "...",
            "updated_at": "..."
          }
        }
    """
    return _read_json(_prompts_path())


def update_persona_prompts(persona: str, *, short: str, medium: str, long: str) -> dict:
    """Replace the prompts block for one persona. Returns the new block."""
    if not persona:
        raise ValueError("persona must be a non-empty string")
    with _LOCK:
        data = _read_json(_prompts_path())
        data[persona] = {
            "short": short,
            "medium": medium,
            "long": long,
            "updated_at": _now_iso(),
        }
        _write_json(_prompts_path(), data)
    return data[persona]


def get_persona_prompt(persona: str, length: Literal["short", "medium", "long"]) -> str | None:
    """Pull one length's text for a persona; ``None`` if absent."""
    block = read_persona_prompts().get(persona, {})
    return block.get(length)


def __all_for_typecheck() -> list[Any]:  # pragma: no cover — alias so MatchValue stays in scope
    return [MatchValue]
