---
title: The Forge — v1 Implementation Plan
type: feat
status: active
date: 2026-06-14
origin: docs/brainstorms/2026-06-14-the-forge-requirements.md
---

# The Forge — v1 Implementation Plan

## Summary

Build `/forge` — the empty-state-first voice-design studio — as a set of no-build Web Components (Lit, vendored) served from the package with zero build step, replacing the patchwork `/lab` as the primary UI while `/lab` stays as the legacy power-user surface. Ten dependency-ordered units across three phases land the foundation (shell + primitives + the persona-bind server seam), then the cold-start happy path (booted → capability door → contact-sheet audition + backend inference), then tuning, the serve console, and identity polish.

## Problem Frame

The WHAT is settled in [the requirements doc](../brainstorms/2026-06-14-the-forge-requirements.md) (R1–R24) and grounded in [the frame](../office-hours/2026-06-14-the-forge-frame.md) and [ideation](../ideation/2026-06-14-the-forge-ideation.md). This plan answers HOW: the current surface is `src/voice_forge/static/lab.html` (772 LOC single-file vanilla JS, served as a `FileResponse` at `server.py:961`), with `VoiceInfo.persona` half-wired (`server.py:199`, read at 637/658/764, no setter) and the design pipeline CLI-only. The studio gets rebuilt component-by-component on a standards-based no-build foundation, with exactly one new server seam (persona binding) in v1.

## Requirements

The authoritative WHAT is R1–R24 in the origin doc. Grouped for the implementer's checklist:

- **Shell & IA (R1–R4):** one surface for empty and loaded; canonical flow centered; Calm/Bench density; output adjacent to controls.
- **Cold-start (R5–R8):** audible key-free default on first paint; worked-example first run; capability-aware entry; no CLI/file-edit on the happy path.
- **Forging (R9–R12):** design + clone; N-candidate audition where picking creates the voice; silence-collapse pre-rejected + retried; direct-manipulation tuning.
- **Backend (R13–R14):** inferred per-voice, never newcomer-chosen; shown with an editable "why," one-click override.
- **Bind & serve (R15–R17):** 1:1 persona binding as a settable registry property; persona is the entry noun; live copy/run API snippet.
- **Audio & interaction (R18–R20):** one custom audio component; anchored playback; in-place cancelable progress.
- **Identity (R21–R22):** dark studio + restrained ember accents; ember as the active-synthesis signal.
- **Architecture (R23–R24):** ships ready, zero build; composable testable components, manifest-adaptive.

## Key Technical Decisions

**KTD1 — No-build serving.** Vendor Lit (~6KB, pinned) as a static ESM file under `src/voice_forge/static/forge/`; serve `GET /forge` as a `FileResponse` exactly like `/lab` (`server.py:961`) and `/demo`; all assets ship in the wheel via `[tool.hatch.build.targets.wheel]` (`pyproject.toml:238`). No Node, bundler, or build step at install, run, or contribute time. Honors R23.

**KTD2 — Component decomposition.** A small set of `<forge-*>` Lit components — `forge-app` (shell + density), `forge-empty-hero`, `forge-voice-card`, `forge-waveform` (+ transport), `forge-contact-sheet`, `forge-backend-chip`, `forge-spec-editor`, `forge-serve-console` — composed under `forge-app` with a tiny shared reactive store. The Voice Card is the atomic primitive; each pillar is a tag; each is individually testable.

**KTD3 — Persona binding.** Promote `metadata.json["persona"]` to a settable 1:1 binding: add `Registry.set_persona()` mirroring the existing `tune()` write pattern (`registry/__init__.py:164`), a `PUT /voices/{id}/persona` endpoint, a `GET /v1/personas` list, and a `persona` form field on `POST /voices/{id}`. Persona names are NOT enforced globally unique in v1 (a persona is a label on a voice; persona-as-entity is deferred). The field already exists and is read at load (`registry/__init__.py:81`), so this is a minimal promotion. **Preserve the existing fallback:** an explicit `metadata["persona"]` already overrides the `_derive_persona()` derivation (`registry/__init__.py:82`), so the existing Asgard fleet's derived personas keep working — `set_persona()` only writes the explicit field, it does not touch derivation.

**KTD4 — Backend-inference signal.** The **one-tap "distinct accent?" affordance at forge time is the real mechanism** — always user-visible, defaulting to a sensible guess. Any pre-check hint (an accent token in the design description) is a weak nicety only; do NOT assume a reliable accent-strength signal exists (Whisper detects language, not accent — there is no proven cheap accent detector, which is exactly why the affordance is user-driven). The choice routes accented voices to an LLM-backbone backend and neutral voices to the F5 default, writing `ref.backend`, with the editable why-chip + one-click override as the safety net. Deeper auto-detection is deferred.

**KTD5 — Silence-collapse handling.** Reuse the QUEUED #61 thresholds: peak amplitude < 0.05 = silence; retry up to 3× at audition; pre-grey/strike collapsed takes in the contact-sheet. #61 already verified these empirically — do not re-derive.

**KTD6 — Seeded default voice + zero-config first sound.** The first-paint audio (R5) is a **pre-rendered bundled audio clip** shipped as a static asset, NOT live synthesis — because every backend needs a model download (F5/Higgs) or a system dep (Kokoro → espeak-ng), so a bare `pip install voice-forge-tts` with no backend extra cannot synthesize anything. The empty-state hero plays that bundled clip with zero dependencies; a small `example: true`-flagged registry voice backs the "forge your own / reforge this" affordance. **Live forging (clone/design/audition) requires at least one backend extra installed** — when none is present, the Forge stays in its booted-but-unforgeable state and tells the user which extra to install (it never silently fails). Generation is never used for the seed.

**KTD7 — `/lab → /forge` transition.** Serve `/forge` as the new primary UI; keep `/lab` serving the legacy page unchanged (no deprecation in v1) with a cross-link banner. Preserves the maintainer's Asgard tuning tools until the pillars port; additive and zero-risk.

**KTD8 — Density persistence.** Store the Calm/Bench choice in `localStorage` (per-browser), default Calm. Trivial, no server state.

**KTD9 — UI testing without a build.** Two tiers, because the existing CI runs `pytest` only (no browser driver wired): (a) **CI-gating** — the Python-side endpoint/registry tests in `pytest` (U5 and the server halves of U6–U8) run in CI as the hard gate; (b) **`/qa`-phase** — the browser-driven UI behavior scenarios (the `test_forge_*.py` files marked "browser-driven") run via the installed browser MCP during `/qa`, not in CI, until/unless a headless browser is added to CI. No Node-based JS unit runner is introduced (it would violate KTD1). Implementers should treat the browser-driven scenarios as `/qa` acceptance checks, not CI blockers — wiring a headless browser into CI is deferred follow-up.

**KTD10 — Carried-fixed (decided upstream, recorded as constraints).** Identity = dark-studio base + ember-as-active-synthesis accent (not heavy smithy); architecture = no-build Web Components + Lit + design tokens + capability-adaptive rendering (reads existing `GET /v1/backends`, not a new manifest). Settled in ideation/brainstorm; not re-opened here.

## High-Level Technical Design

The Forge is a static asset bundle (HTML entry + vendored Lit + `forge/*.js` component modules + `design-tokens.css`) served unbuilt from `src/voice_forge/static/forge/`. `forge-app` owns a small reactive store (voices, focused voice, density, capability snapshot from `GET /v1/backends`) and renders the rail/subject/inspector shell; child `<forge-*>` components subscribe to slices of it. Live audio + progress consume the existing `WS /v1/tts/stream` per-sentence event stream (`session → sentence_start → PCM → sentence_done → complete`); the only new server surface in v1 is the persona-bind seam (KTD3). Everything else reuses existing endpoints (`/v1/audio/speech`, `/v1/backends`, `/voices/*`, `/v1/presets/*`, `voice_design/audition.py`'s `PickerFn`).

## Implementation Units

Ten units, dependency-ordered. Note the incremental-value shape: **Phase A is internal foundation** (a shell that can render but cannot yet forge a voice) — the first *user-functional* slice is end-of-Phase-B (U8), when forging works end to end. Plan demos/checkpoints accordingly; do not expect a usable Forge after Phase A alone.

### Phase A — Foundation

### U1. No-build Web Components foundation + design tokens

**Summary:** Stand up the `/forge` static surface, vendored Lit, the design-token system, and a `forge-app` shell stub — proving zero-build serving from the package before any behavior.

**Approach:** Add `src/voice_forge/static/forge/` (entry HTML, vendored `lit.min.js` ESM pinned, `design-tokens.css` with the dark-studio + ember palette, `forge-app.js` stub). Serve `GET /forge` as a `FileResponse` mirroring the `/lab` handler. Confirm the wheel picks up the new assets (hatchling package-data).

**Covers:** R23, R24, KTD1, KTD2.

**Depends on:** none.

**Test scenario:** `tests/functional/test_forge_serving.py` — `GET /forge` returns 200 + the entry HTML; the vendored Lit + token assets resolve; a wheel-build smoke check asserts `static/forge/` is included and no build artifact is referenced. `Test expectation: none` for the token CSS file itself (asset, not behavior).

### U2. Shell IA + Calm/Bench density

**Summary:** `forge-app` renders the rail / subject / inspector layout with a one-control density toggle; the empty registry and a populated fleet are the same surface at different fill.

**Approach:** Build the shell layout + the reactive store; density in `localStorage` (KTD8), default Calm; Calm hides pillars/compaction, Bench reveals them. Output region docked adjacent to the subject (R4).

**Covers:** R1, R2, R3, R4.

**Depends on:** U1.

**Test scenario:** `tests/functional/test_forge_shell.py` (browser-driven, KTD9) — empty registry renders the Calm hero; seeding N voices renders Bench rows; the toggle flips density and persists across reload.

### U3. Audio layer — `forge-waveform` + persistent transport

**Summary:** One custom waveform+progress component and a docked transport that owns all playback, drawn live from the WS per-sentence stream; a silent take renders as a visibly flat waveform.

**Approach:** Consume `WS /v1/tts/stream` events (`sentence_start`/PCM/`sentence_done`) to paint peaks + a playhead; transport persists across scroll/selection (R19); replace any `<audio controls>` usage. Silence (peak < 0.05, KTD5) → flat-line render.

**Covers:** R18, R19, R20.

**Depends on:** U1.

**Test scenario:** `tests/functional/test_forge_audio.py` (browser-driven) — playback works and progress advances per sentence event; a synthesized silent PCM renders flat; the transport survives a scroll.

### U4. Voice Card primitive — `forge-voice-card` + empty hero

**Summary:** The atomic `<forge-voice-card>` with four data-driven faces (ghost / forging / forged / bound), slotting a persona chip and a backend-why chip; `<forge-empty-hero>` is a ghost card.

**Approach:** One component, faces selected by voice state; the empty-state hero (R6) is the ghost face wired to the seeded default (KTD6, delivered in U7). Fleet = N cards.

**Covers:** R6 (worked-example shape) + the Voice Card UI primitive.

**Depends on:** U2, U3.

**Test scenario:** `tests/functional/test_forge_voice_card.py` (browser-driven) — each of the four faces renders from representative state; the bound face shows the persona + backend chips.

### U5. Persona bind seam (server)

**Summary:** Promote the half-wired `persona` field to a settable 1:1 binding: a registry method, a bind endpoint, a list endpoint, and a create-time setter.

**Approach:** Add `Registry.set_persona(voice_id, persona)` mirroring `tune()` (`registry/__init__.py:164`); `PUT /voices/{id}/persona`; `GET /v1/personas` (voice→persona list); a `persona` form field on `POST /voices/{id}`. No global uniqueness enforcement (KTD3).

**Covers:** R15, R16.

**Depends on:** none (server-only; parallelizable with U1–U4).

**Test scenario:** `tests/unit/test_registry_persona.py` — `set_persona` writes + persists to `metadata.json`; re-bind overwrites; absent voice raises. `tests/integration/test_persona_bind.py` — `PUT` binds and round-trips through `GET /voices/{id}`; `GET /v1/personas` lists; create accepts `persona`; missing voice → 404.

### Phase B — The cold-start happy path

### U6. Backend-inference + `forge-backend-chip`

**Summary:** Infer the backend per voice (one-tap accent affordance → LLM-backbone vs F5 default), always shown as an editable "why" chip with one-click override.

**Approach:** Inference helper writes `ref.backend` from the accent signal (KTD4); `<forge-backend-chip>` renders the choice + a one-line rationale and flips to an override control in place. Reads installed backends from `GET /v1/backends`.

**Covers:** R13, R14.

**Depends on:** U4, U5.

**Test scenario:** `tests/functional/test_backend_inference.py` (browser-driven) — an accented input routes to an LLM-backbone backend with a matching why; a neutral input uses the default; override changes `ref.backend` in one action.

### U7. Cold-start entry — booted-not-blank + capability-aware door

**Summary:** First load with an empty registry presents an audible seeded default and a worked example; the entry reshapes to what's installed (describe-hero vs clone-hero), gating describe when no design engine is present.

**Approach:** First paint plays the bundled pre-rendered clip (KTD6); the `example: true` seed backs the reforge affordance. `forge-empty-hero` reads `GET /v1/backends` (`installed: bool`) to choose describe-hero vs clone-hero and gate the other with a reason (R7); when NO backend extra is installed it shows the booted-but-unforgeable state with the install hint. The persona is named at entry so the forged voice is born bound (R16). The whole path stays CLI-free (R8).

**Open dependency (see review P2):** detecting whether an ElevenLabs key is configured (to decide if the describe path can route to cloud) needs a capability signal NOT currently exposed by the server — add a minimal flag (an `elevenlabs_configured: bool` on `GET /v1/backends`, or a tiny `/v1/capabilities` probe). The exact shape is a small implementation decision for this unit.

**Covers:** R5, R7, R8, R16 (persona-as-entry-noun).

**Depends on:** U4, U6.

**Test scenario:** `tests/functional/test_cold_start.py` (browser-driven) — empty registry yields an audible default from the bundled clip with no key/backend (AE3); with a design engine installed the describe path is primary; with none + no ElevenLabs key the clone path is primary and describe is gated with how-to-enable (AE1); with no backend at all the unforgeable state names the install hint.

### U8. Forging + audition contact-sheet — `forge-contact-sheet`

**Summary:** Both create paths (clone-from-clip; design-from-description via ElevenLabs, gated) feed an N-candidate contact-sheet where degenerate takes are pre-rejected and retried, and picking a take creates the bound voice.

**Approach:** Wire clone + design intake onto the existing 3-preview generation + swappable `PickerFn` (`voice_design/audition.py`); `<forge-contact-sheet>` renders the grid with keyboard cull, pre-greys/strikes silence-collapsed takes (KTD5) after up to 3 retries, and tear-off "keep" promotes the winner to a bound Voice Card (using U5 + U6).

**Covers:** R9, R10, R11.

**Depends on:** U6, U7.

**Test scenario:** `tests/functional/test_forge_audition.py` (browser-driven) + `tests/integration/test_forge_create.py` — clone path yields a bound, backend-assigned voice; design path is gated without an ElevenLabs key; a silence-collapsed take is pre-greyed and retried, never the only result (AE2); picking a take binds and persists.

### Phase C — Tune, serve, polish, transition

### U9. Direct-manipulation tuning — `forge-spec-editor`

**Summary:** Tune a voice by dragging controls that re-audition on release and by editing the description to hear the change, with in-place cancelable progress.

**Approach:** `<forge-spec-editor>` renders controls from each backend's `tunables` schema; release triggers a re-audition through the transport; a debounced description edit re-auditions; the triggering control shows live progress (R20) and `Esc` cancels.

**Covers:** R12.

**Depends on:** U3, U8.

**Test scenario:** `tests/functional/test_forge_tuning.py` (browser-driven) — dragging a control then releasing re-auditions; an edit-pause re-auditions; `Esc` aborts an in-flight render.

### U10. Serve console + identity polish + `/lab` transition

**Summary:** A live, copy/run API-snippet console for the focused voice; the ember active-synthesis identity touches; and `/forge` promoted to the default UI with `/lab` kept as legacy.

**Approach:** `<forge-serve-console>` shows the exact curl/Python/JS call for the focused voice (kept current with selection), with copy + inline run-and-hear (R17); add the ember signals — cold-forge-warms hero, heat-shimmer on the synthesizing card, a forge-complete spark, the wordmark + icon set (R21, R22); serve `/forge` as primary and keep `/lab` with a cross-link banner (KTD7).

**Covers:** R17, R21, R22.

**Depends on:** U8, U9.

**Test scenario:** `tests/functional/test_forge_serve_console.py` (browser-driven) — the snippet reflects the focused voice and copies; run-inline plays the result; the synthesizing card shows the heat state; both `/forge` and `/lab` still serve.

## Scope Boundaries

**In scope (v1):** U1–U10 — the full happy-path `/forge` on the no-build WC foundation + the persona-bind server seam.

**Deferred to follow-up work:**
- The forge-as-substrate endpoints: a one-call `POST /v1/voices/forge`, a dedicated `GET /v1/forge/capabilities` manifest, per-voice provenance/recipe.
- The power-user pillars ported into `/forge` Bench mode: scorecard, persona×backend matrix, preset browser, secrets panel, external-LLM prompt-assist.
- Fully-local design-from-description (depends on QUEUED #60); retiring `/lab`.

**True non-goals:** new TTS backends; STT; a hosted/SaaS Forge; multi-tenant auth.

## Risk Analysis & Mitigation

- **No-build UI testing is browser-driven, which can be flaky.** Mitigate: keep scenarios behavior- and smoke-level (KTD9); Python-side endpoint/registry logic stays in fast `pytest` units (U5).
- **Replacing `/lab` could disrupt the maintainer's fleet workflow.** Mitigate: `/lab` stays unchanged in v1 (KTD7); `/forge` is additive.
- **Design-from-description depends on ElevenLabs (cloud, key).** Mitigate: capability-gated (U7); clone-first always works locally (the frame's #60 analysis).
- **Backend-inference can mis-route.** Mitigate: always-visible why-chip + one-click override (KTD4); never a silent decision.
- **Higgs-MLX silence-collapse (~50% on edge voices).** Mitigate: audition retry + pre-grey using the #61 thresholds (KTD5).
- **Lit as a vendored runtime dep could drift.** Mitigate: pin the vendored file; no bundler means the surface is one auditable asset.

## Alternatives Considered

The two load-bearing forks — frontend architecture (no-build Web Components vs a vendored framework vs htmx) and visual identity (dark-studio vs heavy-forge vs clean-only) — were decided upstream in [ideation](../ideation/2026-06-14-the-forge-ideation.md) and locked in [the requirements doc](../brainstorms/2026-06-14-the-forge-requirements.md). This plan carries them as fixed constraints (KTD1, KTD10) and does not re-litigate them.

## Success Metrics

- A stranger with an empty registry reaches a bound, API-callable voice on the same path the maintainer runs loaded, with no CLI or file edits (the empty-state-first acceptance).
- `voice-forge serve` → open `/forge` → working studio, with no build step anywhere.
- First audio is hearable in the cold-start flow with no configuration.
- A silence-collapse never presents as a dead end.
- The surface reads as one coherent dark studio with restrained ember accents.
- `/doc-review` and `/work` can act on this plan without re-asking the operator.
