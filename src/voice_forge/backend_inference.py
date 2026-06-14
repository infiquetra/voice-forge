"""U6 — backend inference for the Forge clone-create path.

Encodes the journal's architectural rule (LEARNINGS.md 2026-05-26): LLM-backbone
backends preserve a distinct/non-default accent; diffusion backends cannot. When
the source voice has a distinct accent, route the clone to an INSTALLED
LLM-backbone backend; otherwise use the system default.
"""

from __future__ import annotations

# Ordered by journal-validated accent-preservation reliability (LEARNINGS.md
# 2026-05-26 + 2026-06-14). higgs is the production accent path; neutts is the
# in-production Llama-1B fallback; higgs-mlx is demoted under neutts until the
# retry-on-silence guard (QUEUED #61) lands; orpheus last (cloning unconfirmed).
LLM_BACKBONE_PREFERENCE: tuple[str, ...] = ("higgs", "neutts", "higgs-mlx", "orpheus")


def infer_backend(
    accent_distinct: bool,
    installed: list[str],
    default: str,
) -> tuple[str, str]:
    """Pick a backend for a clone-create + return a one-line rationale.

    Args:
        accent_distinct: the source voice carries a distinct/non-default accent
            that must survive cloning.
        installed: backend names installed on this host (the ``installed=True``
            set from GET /v1/backends).
        default: the system default backend (config.get_default_backend()).

    Returns:
        (backend, why) — ``backend`` is always a usable name; ``why`` is a short
        human-readable reason for the cold-start one-tap to surface.
    """
    if not accent_distinct:
        return default, f"default backend ({default}) — no distinct accent to preserve"

    installed_set = set(installed)
    for name in LLM_BACKBONE_PREFERENCE:
        if name in installed_set:
            return name, (
                f"{name} (LLM-backbone) preserves the distinct accent that "
                f"diffusion backends strip"
            )

    # Degrade gracefully: no LLM-backbone backend installed -> default, say so.
    return default, (
        f"no LLM-backbone backend installed; falling back to default ({default}), "
        f"which may not preserve the accent"
    )
