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
