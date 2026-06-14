---
kind: frame-note
date: 2026-06-14
topic: the-forge
mode: builder+wedge
next-command: /ideate
---

# Frame: The Forge — empty-state-first voice-design studio

## The real problem

The QUEUED P1 "`/lab → /forge` redesign" is framed as cleaning up the maintainer's personal
voice-tuning workbench — six pillars: rename, UX recomposition, a secrets/credentials panel, an
external-LLM prompt contract, a dedicated audition tab, and "scan the workflows *we* actually execute."
The root `STRATEGY.md` committed 2026-06-14 reframes The Forge as the public product's headline surface:
"a local, agent-aware ElevenLabs Voice Design" owning the design→bind→serve lifecycle. Those are
different products with different design centers, and all six pillars silently assume an *existing
fleet*.

Settled frame: design for **the job, not the person** — held to the **empty-state-first** discipline.
The canonical path starts from zero (no voices, no ElevenLabs key, no `fleet.yaml`): *arrive with
nothing → design or clone a voice → hear it → bind it to an agent persona → call it from the API.* The
maintainer's 10-sister workflow is that **same path with data already in it**. Forcing function: if a
feature only makes sense once you have a fleet, it is power-user surface layered on top — not the
canonical path. The six pillars get re-sequenced against this spine rather than treated as the design.

## Key assumptions / hypotheses

- **The local design-from-description model makes cold-start design real.** "Arrive with nothing, leave
  with a voice, locally" depends on a local Voice Design provider (Qwen3-TTS-VoiceDesign, QUEUED #60 —
  not yet shipped). Cheapest test: re-design one existing persona (e.g. Mimir) via the local model and
  ear-compare to its ElevenLabs design. If it underperforms on phonetic-imperative prompts, the
  empty-state frame degrades from *design-first* to *clone-first* (a reference clip becomes the
  starting requirement), which changes the headline promise. Same bet the strategy's local-design-share
  metric and the 2026-06-14 DECISIONS ADR revisit-when already track.
- **A stranger with nothing can finish on the same path the maintainer runs loaded.** Falsifiable by a
  cold-start walkthrough: empty registry → a bound, callable voice, with no CLI or `fleet.yaml`
  detours. If the happy path requires dropping to the CLI or hand-editing YAML, the frame isn't met.
- **The design→bind→serve loop is one surface, not three.** Today it's fragmented across CLI + file
  edits + the `/lab` page. The bet is that unifying it is the leverage; if the steps are genuinely
  better as separate tools, the "studio" framing is wrong.

## What got ruled out / reframed

- **"Maintainer is primary" (dogfood-first, outsiders later)** — set aside. Dogfooding still happens
  (the maintainer is the loaded-state user), but designing *for* the full fleet first reproduces the
  patchwork; the empty-state path is the design center.
- **"Full-state, stranger-compatible"** reading of "the job, not the person" — explicitly rejected as
  the trap: it makes the fleet-rich workflow the center and treats empty-state as a degraded entry,
  which is "the job" in name but "the maintainer's job" in practice.

## Route

**`/ideate`** — the frame is set (empty-state-first design→bind→serve studio), but the solution space is
wide open: what the cold-start first-run flow actually is; design-first vs clone-first as the opening
wedge (gated by the local-design-model bet above); how the six pillars re-sequence as power-user layers
over the canonical path; and what the empty-state UI looks like. Carry this frame in so `/ideate`
explores *shapes*, not whether the frame is right.
