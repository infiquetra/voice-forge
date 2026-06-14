"""U6 — the pure backend-inference rule.

Encodes the journal's LLM-backbone-vs-diffusion finding (LEARNINGS.md
2026-05-26): accent-distinct clones route to an installed LLM-backbone backend
in the documented preference order; otherwise the system default. The no-LLM-
backbone graceful-degrade branch returns the default with an explanatory why.
"""

from __future__ import annotations

from voice_forge.backend_inference import infer_backend


def test_accent_distinct_picks_first_installed_llm_backbone() -> None:
    b, why = infer_backend(True, installed=["f5", "neutts", "higgs"], default="f5")
    assert b == "higgs"  # higgs precedes neutts in the preference order
    assert "LLM-backbone" in why


def test_accent_distinct_falls_through_to_neutts_when_higgs_absent() -> None:
    b, _why = infer_backend(True, installed=["f5", "neutts"], default="f5")
    assert b == "neutts"


def test_accent_distinct_respects_full_preference_order() -> None:
    # only higgs-mlx + orpheus installed -> higgs-mlx wins (precedes orpheus)
    b, _why = infer_backend(True, installed=["higgs-mlx", "orpheus", "f5"], default="f5")
    assert b == "higgs-mlx"


def test_not_accent_distinct_returns_default() -> None:
    b, why = infer_backend(False, installed=["higgs", "neutts"], default="f5")
    assert b == "f5"
    assert "default" in why


def test_no_llm_backbone_installed_falls_back_to_default_with_explanatory_why() -> None:
    # accent_distinct=True but ONLY diffusion/preset backends installed
    b, why = infer_backend(True, installed=["f5", "kokoro", "xtts"], default="f5")
    assert b == "f5"
    assert "no LLM-backbone backend installed" in why
    assert "may not preserve" in why
