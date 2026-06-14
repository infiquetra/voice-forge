---
date: 2026-06-14
target: docs/plans/2026-06-14-the-forge-plan.md
reviewed_revision: working tree
kind: readiness-review
blocked: false
plan: docs/plans/2026-06-14-the-forge-plan.md
source: docs/brainstorms/2026-06-14-the-forge-requirements.md
---

# Readiness Review — The Forge v1 Plan

## Readiness summary

**Not blocked — clear to route to `/work`.** The plan is well-grounded (load-bearing seams verified against source) and dependency-ordered. The readiness pass found one load-bearing gap (the empty-state first sound could not be honored by live synthesis) plus six smaller issues; all but one are resolved by safe in-place fixes. The single remaining open item is a non-blocking P2 (a missing capability signal) already flagged as a named sub-task inside U7.

The upstream-fixed constraints (no-build WC architecture, dark-studio+ember identity, 1:1 persona binding, `/lab` stays, ElevenLabs-until-#60) were treated as settled and not re-litigated, per the review brief.

## Applied fixes

| # | Fix | Where |
|---|-----|-------|
| 1 | First-paint sound is a **pre-rendered bundled clip**, not live synthesis; live forging requires ≥1 backend extra; no-backend state shows an install hint instead of failing silently | KTD6, U7 |
| 2 | UI tests split into CI-gating (`pytest` endpoint/registry) vs `/qa`-phase (browser-driven); browser scenarios are not CI blockers (no browser driver wired) | KTD9 |
| 3 | Persona promotion preserves the existing `_derive_persona()` fallback (explicit overrides derived), so the fleet's derived personas keep working | KTD3 |
| 4 | Accent-inference reworded: the one-tap affordance is the real mechanism; no reliable cheap accent detector is assumed (Whisper detects language, not accent) | KTD4 |
| 5 | R16 (persona-as-entry-noun) mapped to U7, not only the U5 server seam | U7 covers |
| 6 | Incremental-value note: Phase A is internal foundation; first user-functional slice is end-of-Phase-B | Implementation Units intro |

## Remaining findings

| id | priority | finding | status |
|----|----------|---------|--------|
| F1 | P1 | R5 ("audible default, no model download, zero config") was unachievable via live synthesis — every backend needs a model/system-dep, and a bare install has none | resolved (fix 1) |
| F2 | P2 | The capability-aware door (U7) needs to know whether an ElevenLabs key is configured, but no endpoint exposes that today | open — flagged as a named sub-task in U7 (add an `elevenlabs_configured` flag on `/v1/backends` or a small `/v1/capabilities` probe); non-blocking |
| F3 | P2 | UI test scenarios are browser-driven but CI runs pytest only — gate expectation was ambiguous | resolved (fix 2) |
| F4 | P2 | Persona-bind promotion could shadow the existing `_derive_persona` fallback | resolved (fix 3) |
| F5 | P3 | Accent-detection wording oversold a "Whisper signal" that doesn't exist | resolved (fix 4) |
| F6 | P3 | R16's UX half mapped only to the server seam | resolved (fix 5) |
| F7 | P3 | "Land a working slice incrementally" — Phase A alone is not user-functional | resolved (fix 6) |

## Residual risk

The browser-driven UI scenarios run in `/qa`, not CI, so UI regressions are caught at the QA gate rather than on every push — acceptable for v1 given the no-build constraint, but worth a follow-up to wire a headless browser into CI. F2 is a small, well-scoped addition the implementer resolves inside U7; it does not block planning or execution.
