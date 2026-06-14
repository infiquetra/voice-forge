---
date: 2026-06-14
topic: the-forge
maturity: requirements-ready
source: docs/ideation/2026-06-14-the-forge-ideation.md (The Forge — composed, 13 survivors)
---

# The Forge — Requirements

## Summary

Replace the patchwork `/lab` tuning page with `/forge`: a self-hosted, empty-state-first voice-design studio where a user arrives with nothing and leaves with a bound, API-callable agent voice — design or clone it, hear it, bind it to a persona, copy the call. v1 ships the complete canonical happy path on a no-build Web Components shell with a dark-studio-plus-ember-accent identity; power-user tuning surfaces and the one-call substrate endpoints layer on after.

## Problem Frame

Today the only interface is `src/voice_forge/static/lab.html` — 772 lines of single-file vanilla JS that opens to a blank `#personas` div for anyone without a fleet, stacks a persona×backend matrix, scorecard, and preset browser down a long scroll, and buries audio output in a log at the very bottom. It is a maintainer tuning surface that assumes voices already exist; there is no way to *create* a voice in it, and the design-from-description pipeline isn't even exposed on the server. `STRATEGY.md` reframed voice-forge as a public "local ElevenLabs Voice Design" whose headline surface is exactly this studio — so the gap between "debug page that tunes an existing fleet" and "the place strangers forge their first agent voice" is the thing this work closes.

## Key Decisions

- **MVP cut = the full happy path.** v1 carries the complete canonical path (design/clone → audition → bind → serve) and all six interface survivors, not a thin slice. Only the substrate niceties and the power-user pillars defer.
- **Visual identity = dark studio + restrained ember/forge accents.** A modern dark-neutral studio base (Linear/ElevenLabs register) with ember as the signature accent and the forge metaphor carried in language and one mark — not a heavy smithy theme. "A little more than glowing cards," nowhere near heavy.
- **Architecture = no-build, ships-ready.** Web Components + Lit (~6KB vendored ESM) + design tokens + manifest-driven rendering. The interface ships complete inside the package; running the server and opening the page yields the working studio with no Node, bundler, or build step — ever.
- **Persona = a 1:1 registry binding.** Promote the half-wired `persona` field into a real, persisted, settable binding: each voice is bound to exactly one persona. A full persona-as-entity (one persona owning many voice versions) is deferred.
- **Backend selection = inferred + visible + overridable.** The Forge auto-picks a backend per voice, always shows a one-line "why," and lets the user override in one action. The signal it infers from is a planning detail.
- **`/lab` stays as the legacy power-user surface** during the transition so the maintainer's Asgard tuning tools don't vanish; the pillars port into `/forge`'s Bench mode as fast-follows.
- **Design-from-description routes via ElevenLabs in v1** (capability-gated when absent); fully-local design arrives with the local design model (QUEUED #60).

## Actors

- A1. **Voice-agent builder (primary human)** — arrives to forge voices for their agents; designs or clones, auditions, binds, serves. Often an engineer, not an audio professional.
- A2. **Conversational agent (runtime consumer)** — calls the API to speak its bound persona voice; never touches the UI.
- A3. **Maintainer / fleet power-user** — operates a multi-voice fleet (the Asgard reference deployment) via Bench mode and the legacy `/lab` tools.
- A4. **TTS backends** — the diffusion and LLM-backbone engine families; per-voice selection is forced by their differing accent-preservation.
- A5. **ElevenLabs (external)** — the design-from-description + voice-pull source until the local design model ships.

## Key Flows

- F1. **Cold start (empty → first voice).** **Trigger:** a user opens `/forge` with an empty registry. Hear the seeded default voice → choose design or clone (entry adapts to what's installed) → audition the candidate set → pick a take → name the persona it's bound to → copy or run the API call. **Covers R5, R6, R7, R8, R10, R15, R16, R17.**
- F2. **Clone path.** **Trigger:** user drops or records a reference clip. The clip is prepared (transcribed as needed), candidates are auditioned, the pick becomes a bound voice with an inferred backend. **Covers R9, R11, R13.**
- F3. **Design path.** **Trigger:** user types a voice description. Candidates are generated (via ElevenLabs in v1), auditioned, the pick becomes a bound voice. **Covers R9, R10.**
- F4. **Tune & re-audition.** **Trigger:** user selects an existing voice and drags a control or edits its description. The voice re-auditions on release / on edit-pause, output playing in place. **Covers R12, R20.**
- F5. **Loaded / fleet.** **Trigger:** the registry holds many voices. The same shell shows them at higher density (Calm→Bench by toggle); power-user tuning is the deferred pillar set. **Covers R1, R2, R3.**

## Requirements

**Shell & information architecture**

R1. The Forge is a single surface where the empty-state newcomer and the loaded fleet are the *same* layout at different fill levels — never a separate "empty mode" versus "dashboard mode."

R2. The canonical design→bind→serve flow occupies the center; power-user surfaces are disclosed by data-state or on demand, never pre-placed as permanent chrome.

R3. The shell offers two density modes — **Calm** (newcomer default: spacious, single-column, pillars hidden) and **Bench** (power-user: compact, multi-column, tuning surfaces revealed) — switched by one control, sharing the same components.

R4. Audio output and timing/status are visible adjacent to the controls that produce them — never requiring a scroll to a separate region.

**Cold-start & entry**

R5. On first load with an empty registry, the Forge presents an audible, ready-to-use default voice (playable in one action) requiring no key, model download, or configuration.

R6. The first-run experience is a fully-worked example — a voice that is designed, bound, and callable — that the user can hear and then reforge, not a blank canvas.

R7. The entry adapts to the live install: when a design-from-description engine is available the "describe a voice" path is primary; when it is not, "clone from a clip" is primary and the describe path is visibly gated with a reason, never a dead or erroring control.

R8. A user can complete the entire canonical path — empty to a bound, API-callable voice — without dropping to the CLI or hand-editing any file.

**Forging: design, clone, audition**

R9. A user can create a voice two ways: design-from-description (a text prompt) and clone-from-reference (an uploaded or recorded clip).

R10. Auditioning presents N candidate takes for a single forge action as a selectable set; choosing a take is the act that creates the voice, not a separate confirm step.

R11. Degenerate takes (silent / collapsed output) are detected and visibly de-emphasized before the user evaluates them, and the system retries rather than presenting only a dead result.

R12. A user can tune a voice by direct manipulation (draggable controls) with the result re-auditioned on release, and iterate by editing the description and hearing the change — without hunting for a separate play control.

**Backend selection**

R13. The Forge selects a backend per voice automatically, biased by the voice's needs (a distinct/non-default accent routes to an accent-preserving backend family; a neutral voice uses the default), and never requires a newcomer to choose a backend to succeed.

R14. The auto-selected backend is always shown with a one-line plain-language rationale, and is overridable in one action.

**Bind & serve**

R15. A voice is bound to exactly one persona; the binding is a first-class, persisted registry property settable at creation and changeable afterward via an API action — not a fleet-file edit.

R16. The persona is the entry noun of the canonical path — a user forges *a persona's voice* — so a voice is never created in an unbound/orphaned state on the happy path.

R17. The serve step presents the exact, copy-pasteable API call (and streaming call) for the focused voice, kept current with selection, with a one-action copy and an inline run-and-hear.

**Audio & interaction**

R18. All playback flows through one consistent custom audio component (waveform + progress), not native browser audio controls; a silent/collapsed take renders as a visibly distinct (flat) waveform.

R19. Playback is anchored so it persists while the user scrolls or changes controls — it does not scroll away with the content that triggered it.

R20. Generation shows live progress on the control that triggered it (driven by the existing per-sentence stream) and is cancelable.

**Identity & visual language**

R21. The visual base is a modern dark studio (dark-neutral, restrained, credible) with a single ember/warm accent as the signature color; the forge metaphor is carried through language (forge/bind/temper/cold-hot), one wordmark, and a small themed icon set — not heavy skeuomorphic theming.

R22. Heat/ember is a functional signal for active synthesis: a card warms while a voice is being forged, the empty-state hero is a "cold forge" that warms when the first voice lands, and forge-complete shows a brief spark.

**Architecture & packaging**

R23. The Forge ships as a complete, predefined, ready-to-use interface inside the installed package; running the server and opening the page yields the working studio with no build, bundle, Node, or asset-assembly step at install, run, or contribute time.

R24. The interface is composed of individually-testable components on a no-build, standards-based browser foundation, and adapts to each install by reading server-advertised capability rather than hard-coded assumptions.

## Acceptance Examples

AE1. **Capability-aware door (covers R7).** When a local design engine is installed → the describe path is primary. When none is installed and no ElevenLabs key is configured → the clone path is primary and the describe path is gated with "needs a design engine" plus how to enable it. When an ElevenLabs key is present but no local engine → the describe path is offered, labeled as routing through ElevenLabs.

AE2. **Silence-collapse (covers R11, R18).** When a take returns silence/collapsed output → it appears pre-greyed with a flat waveform and the system has already retried; the user never sees only a dead result with no path forward.

AE3. **Empty registry (covers R5, R6).** When the registry is empty on first load → an audible default voice and a worked example are present and playable with no key or configuration.

AE4. **Backend inference (covers R13, R14).** When a cloned clip carries a distinct accent → an accent-preserving backend is chosen and the rationale says why; the user can override in one action.

AE5. **Same surface, 0→N (covers R1, R3).** When the registry grows from zero to many voices → the layout is the same shell at higher density (Calm→Bench by toggle), not a different screen.

## Scope Boundaries

**In scope (v1):** R1–R24 — the full canonical happy path, the new shell + identity, and the persona-bind endpoint the back half needs.

**Deferred (fast-follow, eventually but not v1):**
- The forge-as-substrate endpoints: a one-call forge endpoint, a dedicated `/v1/forge/capabilities` manifest, and per-voice provenance/recipe. v1 reads the existing `/v1/backends` for capability-awareness instead.
- The power-user pillars: scorecard, persona×backend matrix, preset browser, secrets/credentials panel, external-LLM prompt-assist contract — ported into `/forge` Bench mode after v1.
- Fully-local design-from-description (depends on QUEUED #60).
- Retiring `/lab` (kept as the legacy surface until the pillars land in `/forge`).

**Outside this effort's identity:** new TTS backends; STT; a hosted/SaaS Forge; multi-tenant auth (tracked separately in `STRATEGY.md`).

## Success Criteria

- **The empty-state-first test:** a stranger with an empty registry reaches a bound, API-callable voice on the *same* path the maintainer runs loaded, with no CLI or file edits.
- First audio is hearable within the cold-start flow with no configuration.
- The interface ships and runs with **zero build step** — install, `serve`, open, working studio.
- A silence-collapse never presents as a dead end — always retried or visibly handled.
- It reads as one coherent dark studio (not the current debug page), with restrained ember/forge accents — more than glowing cards, nowhere near heavy.
- `/doc-review` and `/plan` can act on this doc without re-deriving product behavior.

## Dependencies / Assumptions

- The existing `WS /v1/tts/stream` per-sentence event stream is the real-time substrate for live audio/progress (verified in `src/voice_forge/server.py`).
- `GET /v1/backends` (`installed: bool`) is the capability signal v1 reads for the capability-aware door (verified); the dedicated forge-capabilities manifest is deferred.
- `VoiceInfo.persona` exists but is read-only/overlay today (`server.py:199`, echoed at 637/658/764); promoting it to a settable 1:1 binding requires a new bind endpoint plus a create-time setter — the gap is verified.
- The audition contact-sheet builds on the existing 3-preview generation + swappable `PickerFn` in `src/voice_forge/voice_design/audition.py` (verified).
- Design-from-description depends on ElevenLabs (cloud, API key) until the local model (#60) ships — assumption: #60 not yet available.
- Silence-collapse detection reuses the QUEUED #61 silence-check harness — assumption: concrete threshold/retry count decided in `/plan`.
- One vendored runtime dependency (Lit, ~6KB ESM) is acceptable given it requires no build step — decided.

## Outstanding Questions

**Resolve before planning:** none — the two design forks and the three product decisions are settled (see Key Decisions).

**Deferred to planning (answered during `/plan` or codebase exploration):**
- The accent-detection signal behind R13 — auto-detect from the clip, a one-tap "distinct accent?" prompt, or parse the design description.
- The silence-collapse threshold and retry count (R11).
- The persona-bind endpoint shape and whether persona names are enforced unique (R15).
- The concrete component boundaries — which `<forge-*>` tags exist and how they compose (R24).
- Whether the seeded default voice (R5) is a bundled preset or generated, and how it's marked disposable.
- The `/lab → /forge` transition mechanics (alias, deprecation timing).
- Whether the Calm/Bench density choice persists per session or is stored (R3).

## Sources / Research

- `STRATEGY.md` — voice-forge as a public-OSS local "ElevenLabs Voice Design" owning design→bind→serve.
- `docs/office-hours/2026-06-14-the-forge-frame.md` — the empty-state-first frame and the #60 key-assumption analysis.
- `docs/ideation/2026-06-14-the-forge-ideation.md` — the 13 survivors and the two resolved forks this doc composes.
- `docs/engineering-journal/QUEUED.md` — P1 "The Forge" (the six pillars), #59 (generic mlx_audio), #60 (Qwen3-TTS local Voice Design), #61 (higgs-mlx silence retry guard).
- `docs/engineering-journal/LEARNINGS.md` — the diffusion-vs-LLM-backbone accent ceiling; higgs-mlx ~50% silence-collapse.
- `docs/engineering-journal/DECISIONS.md` — 2026-06-14 ADR (public-OSS voice-forging-studio direction).
- `src/voice_forge/static/lab.html` — current 772-LOC surface being replaced. `src/voice_forge/server.py` — `WS /v1/tts/stream`, `GET /v1/backends`, `/voices/*`, `VoiceInfo.persona`, `/v1/scorecard`, `/v1/personas/prompts`. `src/voice_forge/voice_design/audition.py` — the `PickerFn` audition seam.
