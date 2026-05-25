# Learnings — voice-forge

> **Empirical findings + mechanisms + fixes + validations.** When something turns out to be true that wasn't obvious — about a backend's behavior, a sampling-knob tradeoff, a deploy gotcha, a benchmark — it goes here. Include the **evidence** (commit / experiment / file:line) and the **mechanism** (why it's true), not just the observation.
>
> **Append new entries to the top.** Most-recent first.
>
> Format:
>
> ```markdown
> ## YYYY-MM-DD
>
> ### Short descriptive title
>
> **Context.** One paragraph framing the situation.
> **Evidence.** Specific commit / experiment / file:line.
> **Mechanism.** Why it happened (or why it's true) — root cause, not symptoms.
> **Fix (or queued).** Concrete action + commit hash, OR a QUEUED.md ref.
> **Validation (if applicable).** What later run proved the fix.
> **What surprised (optional).** The thing that wasn't in the original mental model.
> **Generalizable rule.** The lesson stripped of this specific incident.
> **Refs.** Cross-links to DECISIONS / QUEUED / narratives / other LEARNINGS.
> ```
>
> If a prior learning is invalidated by new evidence, **update inline AND move the pre-correction version to `ARCHIVE.md` as SUPERSEDED**. Never silently overwrite history.

---

## 2026-05-24

### First production cutover (2026-05-24 same day as v0.1.0 ship) — design validated

**Context.** v0.1.0 shipped at ~17:30 (home-lab time) on 2026-05-24. By ~20:00 the same day, all 4 NeuTTS sisters in the infiquetra/home-lab Asgard fleet were running on voice-forge in production. The end-to-end loop (uv pip install from git tag → register voices → run as launchd service → hermes-agent integration via HTTP-shim) all worked first try after one pip-syntax fix.

**Evidence.** Home-lab repo PRs #134-138 + voice-forge v0.1.0 tag. Cutover narrative at `infiquetra/home-lab/docs/engineering-journal/narratives/2026-05-24-voice-forge-phase-g-cutover.md`.

**What worked.**
- Backend Protocol with VoiceRef union handled the NeuTTS case cleanly. No abstraction-mismatch surprises.
- FastAPI /v1/audio/speech endpoint integrated with OpenAI-SDK-style clients (the home-lab HTTP-shim uses urllib.request POST).
- FS-backed registry was trivial to seed from existing daemon's persona ref files (shell copy + metadata.json template).
- CLI `voice-forge synth` direct-synth mode was the validation interface — text→WAV without HTTP, without Discord. This was the design principle made literal.

**What needed fixing during deploy.**
- pip 26 rejected `#egg=name[extras]` URL fragment syntax — fixed in home-lab PR #137 (the ansible role's install command). Voice-forge itself is fine; the fix is in the consumer's deployment.
- Hermes-agent's `PROVIDER_MAX_TEXT_LENGTH[neutts]=2000` cap was too conservative for voice-forge's chunker capability. Fixed in home-lab PR #138 (consumer-side hermes-agent patch).

**Generalizable rule.** Design principles ("test without Discord", "pluggable backend Protocol", "CLI surface for direct testing") earn their cost during integration. The first downstream consumer is when you find out whether the abstractions match reality. Spending the planning time upfront (Phase B prior-art research, Phase C scaffolding, devil's-advocate verification pass) paid off — no architectural surprises in the cutover.

**Refs.** v0.1.0 release notes. Home-lab Phase G cutover narrative. Plan at `~/.claude/plans/i-am-under-the-merry-finch.md` (the user's plans directory, not committed here).

### voice-forge inherits 8 LEARNINGS from the home-lab NeuTTS investigation

The empirical findings that motivated this project live in the home-lab repo (where the NeuTTS daemon was first prototyped). Rather than duplicate them here, cross-reference them. As voice-forge gains its own LEARNINGS, those will be appended above this entry.

Inherited findings (from `infiquetra/home-lab/docs/engineering-journal/LEARNINGS.md` § 2026-05-24):

1. **NeuTTS-Air on M4 Pro: Q4+CPU+Accelerate beats MPS**; daemon architecture beats monkey-patch; context truncation is real
2. **Perth watermarker is a per-chunk artifact source**; disabling it cuts streaming clicks 15× — this is why voice-forge's NeuTTS backend disables the watermarker
3. **FFmpeg default MP3 bitrate for mono is 32 kbps** — explicit `-b:a 192k` required (informs voice-forge's MP3 encoder defaults)
4. **NeuTTS streaming drops 15-21% of audio content vs batch** on long inputs — informs voice-forge's `synthesize_stream` documentation + default-to-batch decision
5. **NeuTTS-Air degrades into incoherent phonemes on >30s sustained narrative** — informs voice-forge's ROADMAP (need different backends for long-form)
6. **Plugin routing first-in-list vs first-in-text** (from asgard_voice_arbiter, doesn't apply to voice-forge directly but the pattern is worth remembering)
7. **Whisper STT auto-detect mis-flags Norwegian-accented English** — informs voice-forge's voice_lab.whisper module which forces `language="en"`
8. **Decision to spin TTS out of home-lab into voice-forge** — the meta-decision that birthed this project

**Refs.** [Companion narrative](narratives/2026-05-24-voice-forge-spin-out.md) summarizes the spin-out reasoning. Original entries: `infiquetra/home-lab/docs/engineering-journal/LEARNINGS.md` (search `## 2026-05-24`).
