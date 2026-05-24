# Engineering Journal

> The decision + lessons trail behind voice-forge. When something turns out
> to be true that wasn't obvious, or when a design choice gets made worth
> remembering, or when an idea surfaces that we're not building right now —
> it goes here.

## The four files + one folder

### `LEARNINGS.md`

Empirical findings + mechanisms + fixes + validations. When something turns out to be true that wasn't obvious — about the model, the API, a benchmark result, a deploy gotcha — it goes here. Include the **evidence** (commit / experiment / file:line) and the **mechanism** (why it's true), not just the observation. Append-only; most-recent-first.

### `DECISIONS.md`

ADR-style records of architectural / API / process choices. When you commit a chosen path over alternatives, capture rationale + tradeoff + revisit-when condition + commit hash. The point is to make revisit conditions explicit so future-you (or a future contributor) gets the answer cold.

### `QUEUED.md`

Future-work items by priority with explicit "worth it when" triggers. When a promising idea surfaces but we don't build it right now, it goes here. **Don't skip the entry just because it feels minor** — the whole point of QUEUED is to externalize work memory.

### `ARCHIVE.md`

Where QUEUED items go to die — either as **SHIPPED** (with date + commit) or **REJECTED** (with reason + revisit condition) or **SUPERSEDED** (with link to whatever replaced it). Never silently delete from QUEUED.

### `narratives/`

Long-form companion docs: design walkthroughs, post-incident write-ups, the story of how a non-obvious decision came together. One file per topic; filename pattern `YYYY-MM-DD-topic.md`. Link to them from the relevant LEARNINGS / DECISIONS entries.

## Format conventions

All files include a format header at the top with the entry template. New entries go at the TOP (most-recent-first). When an entry is invalidated, update it inline AND move the pre-correction version to ARCHIVE.md as SUPERSEDED — never silently overwrite history.

The home-lab repo (which this project span out of) has been using this pattern for ~6 months and has built up substantial institutional memory. See `infiquetra/home-lab/docs/engineering-journal/` for an example of what this looks like after sustained use.
