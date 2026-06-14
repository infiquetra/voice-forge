---
date: 2026-06-14
topic: the-forge
focus: empty-state-first Forge — the /lab → /forge web studio redesign (QUEUED P1)
scope: broad
repo: voice-forge
maturity: idea-ready
---

# Ideation: The Forge — Empty-State-First Voice-Design Studio

/ Frame: [docs/office-hours/2026-06-14-the-forge-frame.md](../office-hours/2026-06-14-the-forge-frame.md) · Strategy: [STRATEGY.md](../../STRATEGY.md) · Source backlog item: QUEUED P1 "The Forge: full web-UI redesign" /

## Grounding Context

**Repo:** voice-forge is a public-OSS, self-hosted, Apache-2 pluggable TTS service (`voice-forge-tts` on PyPI; FastAPI + an FS-backed voice registry). Per `STRATEGY.md` (2026-06-14) it is a **local "ElevenLabs Voice Design"** owning the **design → bind → serve** lifecycle; The Forge is its headline human-facing surface. Core technical constraint (LEARNINGS): no single backend serves all voices — diffusion backends (F5 default, XTTS, Chatterbox) cannot preserve a non-default accent; only LLM-backbone backends (Higgs, NeuTTS) do — so per-voice backend selection is the spine.

**Current surface:** `/lab` (`src/voice_forge/static/lab.html`, 772 LOC single-file vanilla JS) is a maintainer tuning page — persona×backend matrix, scorecard, preset browser, output `#log` buried at the bottom; no design entry, no empty-state, no component system, hardcoded colors. The `voice_design/` pipeline (design-from-description) is CLI-only, not exposed on the server. `VoiceInfo.persona` already exists as a registry field but has no bind endpoint. `ref.backend` is already per-voice. `POST /voices/from-elevenlabs` already chains pull→trim→register. `audition.py` has a swappable `PickerFn`. `WS /v1/tts/stream` already emits per-sentence lifecycle events. `GET /v1/backends` reports `installed: bool` (the manifest pattern, proven).

**Context-libraries:** None consulted (single-repo run).

## Topic Axes

Behavioral/flow axes (batch 1): cold-start entry & first-run flow · opening wedge (design-from-description vs clone-from-clip, gated by the unshipped local design model) · bind-to-persona & serve handoff · IA & progressive disclosure.

UI/interface axes (batch 2): visual language & forge identity · interaction model & micro-interactions · component system · frontend architecture & build.

## Resolved Design Decisions (forks closed by operator, 2026-06-14)

- **Visual identity:** modern dark studio base (Linear/ElevenLabs register — dark-neutral, whitespace, hairline borders) with **restrained forge accents** — ember as the signature accent color, the metaphor in the verbs (forge / bind / temper / cold-hot), one forge wordmark + a small spark/anvil/hammer icon set, a "cold forge that warms" empty-state hero, and a brief spark on forge-complete + heat-shimmer on the actively-synthesizing card. Explicitly NOT a heavy smithy theme (no metal textures, anvil clipart, or all-orange UI). "A little more than glowing cards," nowhere near heavy.
- **Frontend architecture:** **no-build Web Components + Lit (~6KB, vendored ESM) + design tokens + manifest-driven rendering.** Hard rule: the Forge ships a complete, predefined, ready-to-use interface inside the `pip install` — run `voice-forge serve`, open it; a user NEVER builds or assembles a web page, and there is no Node/bundler step. Each pillar becomes a testable `<forge-*>` tag; the UI auto-adapts per install via the `/v1/backends`-style capability manifest.

## Ranked Survivors

The 13 survivors form two interlocking groups — **behavior** (what the Forge does, 1–7) and **interface** (what it is / feels like, U1–U6) — and compose into one build: U1's Voice Card hosts behavioral #2/#3; U5's contact-sheet is behavioral #5's body; U6's console is behavioral #1's body.

### 1. Close the bind→serve seam: persona-first binding + the missing endpoint + a live API snippet

Make the persona the entry noun (you forge *Mimir*, not "a voice you later attach"), so voices are born bound; back it with the missing `PUT /voices/{id}/persona` + `GET /v1/personas`; end the journey at a copy-paste curl/WS snippet pre-filled with that voice's id.

Closes the entire back half of the design→bind→serve loop the strategy is named for, and the "associate voices with agent personas" job the operator explicitly emphasized.

It is also the most uniquely grounded survivor — the seam is half-built already. The downside is a real data-model fork: is persona a true 1:1 registry concept or a fleet.yaml overlay?

| field | value |
|-------|-------|
| basis | `direct:` `VoiceInfo.persona` is a registry field returned by `from-elevenlabs`, but `register_voice` neither accepts nor returns it and no endpoint sets/lists bindings — half-wired in data, absent in API |
| confidence | 88 |
| complexity | Med |
| axis | bind & serve |
| status | Unexplored |

### 2. Booted, not blank — the empty state is an audible, key-free default voice you reforge

A cold install lands on a working default voice already speaking (F5 or a Kokoro preset — no download, no key), one Play audible on first paint; first run is a fully-worked example (designed → bound → serving). The first action is "make this mine," not "create from a void."

Highest value-per-effort on the board — it fixes the literal dead first screen.

The seed must be clearly disposable or it reads as demo clutter.

| field | value |
|-------|-------|
| basis | `direct:` `lab.html:124` renders blank with no fleet; `ensure_full_coverage` no-ops for every outside user; `POST /v1/presets/{backend}/sample` needs no key/registry write |
| confidence | 90 |
| complexity | Low |
| axis | cold-start |
| status | Unexplored |

### 3. Backend as inferred consequence, not a user choice

A newcomer cannot answer "F5 or Higgs?" — that knowledge is exactly what they lack. The Forge infers the backend from the voice's needs (non-default accent detected → route to an LLM-backbone backend that preserves it; plain neutral → diffusion default), writes `ref.backend`, and surfaces it only as an editable one-line "why" chip. The persona×backend matrix survives only as a power-user override.

The core technical finding turned into a product simplification only voice-forge can claim.

Needs accent-distinctiveness detection (a Whisper signal or an explicit toggle); a wrong auto-route is worse than none, so it needs the "why" + an easy override.

| field | value |
|-------|-------|
| basis | `direct:` "diffusion CANNOT preserve a non-default accent (architectural ceiling); only LLM-backbone preserve accent" (LEARNINGS); `ref.backend` already per-voice, read automatically by synth |
| confidence | 80 |
| complexity | Med |
| axis | IA / disclosure of the hardest concept |
| status | Unexplored |

### 4. Capability-aware front door — adapt the entry to what's installed; never dead-end on #60

The cold-start entry reshapes itself to the live install: local design model present → the describe box is the hero; absent (and no ElevenLabs key) → the clone path is the hero and the describe door is visibly gated, not a button that 500s.

The only survivor that directly de-risks the frame's load-bearing assumption — the Forge ships complete today whether or not the local design model (#60) ever lands.

Two live entry paths to maintain; the gated door needs strong "why + how to unlock" copy or it reads as a paywall.

| field | value |
|-------|-------|
| basis | `direct:` `GET /v1/backends` already reports `installed: bool`; design-from-description is ElevenLabs-only today. `reasoned:` empty-state-first means the UI must adapt to what this install can do |
| confidence | 85 |
| complexity | Med |
| axis | opening wedge + model gate |
| status | Unexplored |

### 5. Audition by contact-sheet — pick from N, silence-collapse pre-rejected; choosing IS the forge step

Replace "generate one, judge it" with a contact-sheet of N candidates rendered on the same line, with degenerate takes (Higgs-MLX ~50% silence-collapse) auto-detected and pre-rejected before the human ever hears them. Picking is the forge act.

Turns the worst known reliability bug into ordinary non-selection and lowers the taste burden for an engineer-not-audio-person.

N× synth cost per forge; auto-reject needs a defensible silence/quality threshold so it never discards a good take.

| field | value |
|-------|-------|
| basis | `direct:` `voice_design/audition.py` already generates 3 previews + has a swappable `PickerFn` (pick_interactive + pick_auto) — the web UI is just a third picker; silence-collapse is detectable |
| confidence | 84 |
| complexity | Med |
| axis | opening wedge / decision |
| status | Unexplored |

### 6. One shell, data-state disclosure — the canonical flow is the center; the six pillars fill in as layers

The Forge lands on the single design→bind→serve flow, output docked next to controls (not buried at the bottom of a 772-line scroll); the six pillars (matrix, scorecard, preset browser, secrets, prompt-assist) are disclosed by data-state — empty for a newcomer, dense for the 10-sister fleet. Same surface at different fill levels.

The load-bearing IA decision the whole redesign turns on; avoids rebuilding the single-scroll clutter.

It is the whole shell — the largest single build; "what data-state unlocks what" needs careful design or it becomes a hidden-features maze.

| field | value |
|-------|-------|
| basis | `direct:` current `/lab` is a 772-LOC single-scroll page with the `#log` at line 164 (buried) and the persona×backend matrix as landing content; forcing function "fleet features layer ON TOP" |
| confidence | 82 |
| complexity | High |
| axis | IA & progressive disclosure |
| status | Unexplored |

### 7. The Forge as substrate — one-call `POST /v1/voices/forge` (pluggable source) + capability manifest + provenance

Promote internals that already exist into stable contracts: a one-call forge endpoint whose first step is a swappable source (clip / elevenlabs / description), a `GET /v1/forge/capabilities` manifest the UI renders itself from, and a provenance/recipe block stamped on every voice (replayable when models improve).

Makes the #60 degradation a config flip (default source), and lets any third-party UI or agent stay correct as the system grows.

Most enabling-infra, least directly user-visible — sequence it after the happy path is proven, or risk gold-plating the API first.

| field | value |
|-------|-------|
| basis | `direct:` `POST /voices/from-elevenlabs` already chains pull→trim→register in one call; `register_voice` auto-transcribes; `GET /v1/backends` reports `installed`. `reasoned:` empty-state-first wants the loop as one atomic call |
| confidence | 80 |
| complexity | High |
| axis | substrate / cross-cutting |
| status | Unexplored |

### U1. The Voice Card primitive — one component, four data-driven faces

A single `<forge-voice-card>` renders ghost (the empty-state hero is a ghost card with a "forge a voice" CTA) / forging (skeleton + progress) / forged / bound — same shape, more data. Fleet view = N cards; carries the persona chip + the backend-"why" chip (the UI home of survivor #3).

The highest-leverage component — every other surface composes from it, and survivors #2 (empty-state) and #6 (disclosure) fall out for free when the empty state and the populated state are the same component.

Get its anatomy wrong and the rework cascades.

| field | value |
|-------|-------|
| basis | `direct:` no card abstraction today — a voice is an ad-hoc `<tr>` (`renderBackendRow`) and a preset is a separate `.preset-card` div |
| confidence | 88 |
| complexity | Med |
| axis | component system |
| status | Unexplored |

### U2. A real audio layer — WaveformChip + a persistent transport, drawn live from the WS stream

Kill every bare `<audio controls>`. One custom WaveformChip (peak bars + progress fill) plus a docked bottom transport bar that owns all playback and follows you as you scroll. Silence-collapse renders as a visible flat red line, not a buried log string.

The audio player is the most-touched component in a voice studio; leaving it as OS chrome is the biggest tell that this is a debug page, and a flat-line makes survivor #5's pre-rejection legible.

A custom player is real work and must handle browser audio quirks the native control gave for free.

| field | value |
|-------|-------|
| basis | `direct:` replaces scattered `<audio controls>` + the bottom `#log`; the WS already streams Float32 PCM + `sentence_start`/`sentence_done` events to draw real peaks |
| confidence | 86 |
| complexity | Med |
| axis | component system / interaction |
| status | Unexplored |

### U3. Single-shell IA — Linear invariant shell + Figma selection-inspector + Calm/Bench density

The concrete form of survivor #6: a fixed three-pane shell (rail / subject / inspector), a Figma-style inspector that reshapes to the selected voice, and one density toggle — Calm (newcomer: big cards, one column, pillars hidden) vs Bench (the fleet: compact grid, scorecard, timings). Empty and fleet are one layout, not two apps.

Locks the empty-state-first constraint and the fleet use case into a single maintainable layout — the demo and the maintainer's daily driver are the same code.

The whole shell — the largest build; the inspector + density add state-management surface.

| field | value |
|-------|-------|
| basis | `direct:` current `/lab` is Bench-only (8-col matrix, dual aggregate tables, no calm entry); `external:` Linear single-shell + Figma selection-inspector + Gmail density |
| confidence | 84 |
| complexity | High |
| axis | visual language / architecture |
| status | Unexplored |

### U4. Direct-manipulation tuning — instrument knobs + type-to-hear + in-place render progress

Make tuning feel like an instrument: knobs become draggable rack sliders (Ableton device-rack) that re-audition on release; the spec textarea auto-auditions on a debounced pause (type "warmer" → hear the delta, no button); render progress shows on the control you clicked, with `Esc` to cancel — all riding the per-sentence WS events.

Direct manipulation plus audition-on-release turns parameter tuning from a type-then-find-button chore into a tactile nudge-and-listen loop — the core of how voice tuning should feel.

Auto-audition can fire too often (cost/latency) — needs debounce + an off switch; overlaps the speculative sub-second describe-bar (R4).

| field | value |
|-------|-------|
| basis | `direct:` builds on the existing `tunables` schema + the WS init-frame `{voice, sampling}` override path; replaces today's numeric inputs + distant Speak button |
| confidence | 83 |
| complexity | Med |
| axis | interaction & micro-interactions |
| status | Unexplored |

### U5. Audition contact-sheet — keyboard-cullable grid, silence pre-greyed, tear-off keep

The UI home for survivor #5: N candidates as a photo-contact-sheet grid you cull by keyboard (Space play, J/K move, X reject, Enter keep — Lightroom). Silence-collapsed takes arrive pre-greyed and struck; the keep action visually tears the winner out and promotes it into a bound Voice Card.

Engineers want to clear a contact sheet fast; a keyboard cull is the fastest known interaction for "pick the keeper from N," and pre-rejection of silence feels like a head start rather than a wall.

N× synth cost; the cull keyboard model is unfamiliar to non-power users — needs a visible affordance, not just shortcuts.

| field | value |
|-------|-------|
| basis | `direct:` nearest today is the flat `.preset-grid` with no keep/reject/rejection-state; reuses per-candidate WS playback; `external:` Lightroom cull + Midjourney contact-sheet |
| confidence | 84 |
| complexity | Med |
| axis | interaction / component system |
| status | Unexplored |

### U6. The serve console — a persistent Postman/Stripe snippet panel

The UI home for survivor #1's serve handoff: a docked console showing the exact call for the focused voice — curl/Python/JS tabs, one-click copy, and a ▶ "run this" that executes inline and plays the result. Reclaims the buried dark `#log` as its home (right material, wrong job today).

For an API-builder primary user, the call IS the deliverable; making it always-visible and always-current closes the design→serve gap that is the product's thesis.

Keeping the snippet perfectly in sync with focus/state is fiddly; "run inline" needs auth/host assumptions handled.

| field | value |
|-------|-------|
| basis | `direct:` `#log` is already a `#1e1e1e` console pinned at the bottom; `external:` Postman/Stripe live request→snippet pane |
| confidence | 85 |
| complexity | Med |
| axis | component system / interaction |
| status | Unexplored |

## Did not survive (revivable)

| id | title | summary | reason | status |
|----|-------|---------|--------|--------|
| R1 | Fork-a-voice / remix gallery | Empty state as a gallery of seed clips (own refs + CC0 + ElevenLabs shared-voice search) you remix | duplicates "Booted, not blank" (#2) as a clone-first flavor; `search_shared_voices` exists — revive if clone-first becomes the confirmed wedge | rejected |
| R2 | The Forge is a TUI/REPL | describe/clone/play/bind/serve as shell verbs, no web UI | off-frame — the "local ElevenLabs Voice Design" strategy implies a visual studio; real value is verb-clarity + CLI/web parity | rejected |
| R3 | Develop-in-hand / Polaroid latency UX | Candidate tile "develops" as audio streams; a silent take = a blank exposure to re-shoot | folded into #5 / U2 as the loading + failure treatment; revive as standalone polish | rejected |
| R4 | Sub-second live describe-bar (north-star) | Re-synth on every keystroke-pause if the local model is instant | speculative — depends on an unshipped AND fast #60; keep so today's IA doesn't over-bake preview flows | rejected |
| R5 | (reverted demotion) | "raise the bar" briefly demoted survivors #6/#7 here | operator reverted — all 7 behavioral survivors restored | revisited |
| R6 | (reverted demotion) | see R5 | operator reverted | revisited |
| R7 | Type-to-hear on every keystroke | Auto-audition on every keystroke-pause | folded into U4 as a setting; overlaps R4 | rejected |
| R8 | Arc-style capability-tinted ambient theme | Accent glows hotter for GPU/clone-capable backends | couples identity to backend tier — speculative; revive under the chosen heat-as-signal identity if wanted | rejected |
| R9 | htmx server-rendered partials | Render HTML partials from FastAPI, swap via htmx | best for static pillars, worst for the streaming audition/snippet (the product's signature); surfaced under F-architecture, not chosen | rejected |

## Co-ideation log

| source | entered | idea / seed | outcome |
|--------|---------|-------------|---------|
| frame (office-hours) | Phase 0 | empty-state-first — "the job, not the person" (carried in as the governing constraint) | shaped every survivor; not judged, it IS the frame |
| frame-agent | Phase 2 | 6 behavioral frames (pain, inversion, assumption-breaking, leverage, analogy, constraint-flip) × ~7 | survived as #1–#7 |
| user-direction | Phase 6 | "we have nothing on the UI/Interface — it needs a serious overhaul" | spawned batch 2 |
| frame-agent | Phase 6 (batch 2) | 4 UI frames (interaction, visual/components, UI analogy, frontend architecture) × ~8 | survived as U1–U6 + the 2 forks |
| user-decision | Phase 6 | "raise the bar" → briefly demoted #6/#7; operator reverted | all 7 behavioral restored (R5/R6 revisited) |
| user-decision | Phase 6 | resolve F-identity → dark studio + restrained ember/forge accents; F-architecture → no-build Web Components + Lit, ships a predefined interface | recorded under "Resolved Design Decisions" |

## Notes

- Survivor count is intentionally 13 (two coherent groups: 7 behavioral + 6 UI), per the operator's explicit direction to expand UI coverage — above the usual 5–7 because the run covered two distinct surfaces (what the Forge does + what it is).
- Next: `/brainstorm` on the composed Forge (all survivors + both resolved forks) → a requirements doc with MVP-vs-later cut lines. Likely MVP spine: U3 shell + U1 Voice Card + the cold-start trio (#2 booted → #4 capability door → #5/U5 contact-sheet) + #3 backend-inference + #1/U6 bind→serve, on the no-build Web Components substrate; #7 substrate endpoints and the fleet/power-user pillars sequenced behind the proven happy path.
