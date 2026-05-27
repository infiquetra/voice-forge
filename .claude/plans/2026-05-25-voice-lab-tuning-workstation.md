# Project: voice-forge `/lab` — voice testing + tuning workstation

Date: 2026-05-25
Checkpoint: 2026-05-25-pre-execute

## Overview

`/demo` does what it was built for: a clean LLM-streaming surface that anyone can hit to hear the WS layer-2 work. But it's not the right tool for *tuning* — the user needs a workstation: pick a persona, hear the original ref WAV, hear it through every installed backend side-by-side, mark which clones match the original, take notes, edit the persona's stories, and have the scorecard be both human-editable + machine-readable so Claude can analyze patterns and recommend tunings.

This plan keeps `/demo` exactly as-is and adds a new `/lab` page + the server infrastructure to back it. No knobs / output / timing get removed — they show up in the new surface too.

## Locked decisions (from AskUserQuestion 2026-05-25 + follow-up clarifications)

1. **Backend scope** — All 8 backends visible in `/lab`. Provisioned backends are interactive; un-provisioned subprocess backends (Piper / Chatterbox / MeloTTS) appear greyed with an "install command" hint.
2. **Missing persona×backend coverage** — Pre-registered idempotently on server startup using the existing `ref.wav` from each persona's audition-registry entry. **Strictly opt-in via the presence of `tests/functional/fleet.yaml`** — when absent (outside-user installs), the lifespan event logs "no fleet.yaml, skipping persona coverage" and does nothing. Voice-forge runtime never imports anything home-lab-specific.
3. **Preset browser** — Separate panel inside `/lab`. On-the-fly preset sampler via a new `/v1/presets/{backend}/sample` endpoint that synthesizes without touching the registry. **Covers Kokoro AND Piper AND MeloTTS** (the user wants to compare across all three preset backends to pick which fits where).
4. **Scorecard** — JSON at `tests/functional/voice_scorecard.json`. New REST endpoints PUT/GET it. Lives in the repo so edits are diff-able. Claude reads the file directly when asked to analyze. 4-state match field: `yes` / `partial` / `no` / `null`.
5. **Per-persona texts** — JSON at `tests/functional/persona_prompts.json`. Page has three textareas (short / medium / long) + Save button; PUT writes back. Lives in the repo.
6. **Original clone-source WAV** — New endpoint `GET /v1/voices/{voice_id}/reference` serves `ref.wav` as `audio/wav` from the registry. Page renders `<audio>` alongside synth output for A/B.
7. **UI surface** — New page at `/lab`. `/demo` stays as the simple LLM-streaming demo.
8. **Auto-registration timing** — Server startup lifespan event. Idempotent. Fast (just writes metadata.json; no model loads).
9. **F5 default flip: nfe_step=16 is now the F5 default** (was 32). The 11-sentence stress test (LEARNINGS 2026-05-25) found no audible difference; the user wants the speed win baked in. The `*-fast` voices in `.audition-registry/` (saga/heid/hnoss × f5) become redundant with the new default and get removed. The 32-step "quality preset" is still reachable via the knob panel.
10. **`sync_fleet_from_home_lab.py` is a PERSONAL DEV SCRIPT, not a voice-forge feature.** It pulls the Asgard persona list from `infiquetra/home-lab` into `tests/functional/fleet.yaml`. Outside users have no home-lab; for them voice-forge has zero concept of "Asgard personas" — registry stays empty until they register their own voices.

## Scope summary

| Item | Backend | Frontend | Effort |
|---|---|---|---|
| Auto-register persona × installed-cloning-backend at startup | server.py lifespan | — | ~2 hr |
| `GET /v1/voices/{voice_id}/reference` | server.py | — | ~30 min |
| Scorecard endpoints (GET/PUT `/v1/scorecard`) | new module | — | ~1 hr |
| Persona-prompts endpoints (GET/PUT `/v1/personas/prompts`) | new module | — | ~1 hr |
| Preset sampler endpoint (`/v1/presets/{backend}/sample`) | new route | — | ~2 hr |
| `/lab` page + JS | new static html | full UI | ~6-8 hr |
| Initial persona_prompts.json seeding from existing responses.yaml | one-time script | — | ~1 hr |
| Tests + journal hygiene | — | — | ~3 hr |

**Total focused work: ~2-3 days.**

## Phase A — Server foundations [SEQ]

These are independent of each other in terms of code, but they all touch `server.py`, so simpler to do sequentially to avoid merge conflicts in the same file.

### A1. Auto-registration at startup (opt-in via fleet.yaml presence)

- [ ] Source of truth for the persona list: `tests/functional/fleet.yaml` if present. **No fleet.yaml → no-op, log info-level skip message, voice-forge runs normally.**
- [ ] New module `src/voice_forge/persona_coverage.py` with `ensure_full_coverage(registry, fleet_path) -> dict` that:
    - Returns early with `{"skipped": "no fleet.yaml"}` when `fleet_path` is missing
    - Reads fleet.yaml when present
    - For each persona × each installed cloning backend (f5, neutts, xtts, dia, chatterbox), checks if `<persona>-<role>-<backend>` exists in the registry
    - If not, creates it using the existing `<persona>-<role>` voice's `ref.wav` + `ref.txt`
    - Returns a summary dict: `{"created": [...], "skipped_existing": [...], "skipped_missing_ref": [...]}`
    - Idempotent: re-running creates nothing new
- [ ] Wire as a FastAPI lifespan event in `server.py` (`@asynccontextmanager async def lifespan(app): ... yield`)
- [ ] Log the summary at INFO level on startup
- [ ] **Important**: voice-forge code MUST NOT depend on home-lab in any way. The sync script (`scripts/sync_fleet_from_home_lab.py`) is a personal dev tool that writes fleet.yaml; runtime only reads what's been written.
- [ ] Tests:
    - Temp registry, no fleet.yaml → ensure_full_coverage returns `{"skipped": "..."}`, no writes
    - Temp registry with 2 personas + 1 mock cloning backend → run `ensure_full_coverage` → verify the missing combo is created with correct metadata
- Commit: `feat(server): auto-register persona × cloning-backend coverage at startup (opt-in via fleet.yaml)`

### A2. `GET /v1/voices/{voice_id}/reference`

- [ ] In `server.py`, add endpoint returning `FileResponse` of `registry.get(voice_id).ref_audio_path`
- [ ] 404 if voice_id not in registry OR backend is preset-only (no ref WAV)
- [ ] media_type=`audio/wav`
- [ ] Tests: GET a known cloning voice → 200 + wav bytes; GET a kokoro voice → 404
- Commit: `feat(server): GET /v1/voices/{id}/reference serves the clone source WAV`

### A3. Scorecard + persona-prompts persistence layer

- [ ] New module `src/voice_forge/lab_state.py` with:
    - `read_scorecard() -> dict`, `write_scorecard(data: dict)` — backed by `tests/functional/voice_scorecard.json`
    - `read_persona_prompts() -> dict`, `write_persona_prompts(data: dict)` — backed by `tests/functional/persona_prompts.json`
    - Thread-safe writes via a module-level Lock
    - On read, return `{}` if file doesn't exist; create on first write
- [ ] Schema sketch — scorecard:
    ```json
    {
      "<persona>": {
        "<backend>": {
          "matches_original": "yes" | "no" | "partial" | null,
          "notes": "...",
          "tested_at": "ISO8601",
          "knobs_used": {"nfe_step": 16, ...}
        }
      }
    }
    ```
- [ ] Schema sketch — persona_prompts:
    ```json
    {
      "<persona>": {
        "short": "...",
        "medium": "...",
        "long": "...",
        "updated_at": "ISO8601"
      }
    }
    ```
- [ ] REST endpoints (`server.py`):
    - `GET /v1/scorecard` → full dict
    - `PUT /v1/scorecard/{persona}/{backend}` → body: row update (partial merge)
    - `GET /v1/personas/prompts` → full dict
    - `PUT /v1/personas/prompts/{persona}` → body: {short, medium, long}
- [ ] Tests: round-trip read/write, partial update merge, concurrent-write safety
- Commit: `feat(server,lab): scorecard + persona-prompts persistence + REST endpoints`

### A4. Preset sampler — all three preset backends covered

- [ ] Each preset-capable backend (`kokoro`, `piper`, `melotts`) declares a `KNOWN_PRESETS: list[dict]` class attribute alongside `KNOWN_TUNABLES`. Each entry is `{"id": "af_bella", "language": "en-us", "gender": "f", "label": "Bella"}` so the UI can group + label cleanly.
- [ ] **Kokoro**: hardcoded list of ~54 preset names from upstream (`af_bella`, `af_heart`, ... `am_adam`, `bf_emma`, `bm_george`, `bf_lily`, ...). Already-known set; no on-the-fly discovery.
- [ ] **Piper**: hardcoded curated list of ~20 voices from `huggingface.co/rhasspy/piper-voices`. Coverage: en_US (amy, ryan, lessac, libritts), en_GB (alan, semaine, southern_english_female), es_ES (sharvard), fr_FR (siwis), de_DE (thorsten), zh_CN (huayan), ja_JP (no-named). Each preset downloads the ONNX model on first sample call (~30-50 MB); piper-tts has a built-in download helper. The Piper backend's child-venv impl gets `preset_id` → resolves voice name → calls `PiperVoice.load_or_download(voice_name)`.
- [ ] **MeloTTS**: same pattern. KNOWN_PRESETS hardcoded for `EN-US`, `EN-BR`, `EN-INDIA`, `EN-AU`, `ES`, `FR`, `ZH`, `JP`, `KR`. **NOTE**: MeloTTS provisioning is still blocked on the arm64-tokenizers wheel issue (LEARNINGS 2026-05-25). Spec the surface anyway; sampling returns 503 with the install-blocker explanation until provisioning works. Try-harder install attempt during execution (rust toolchain + maybe pin transformers differently) — if it works, MeloTTS is fully live; if not, the UI surfaces the blocker clearly.
- [ ] `GET /v1/presets/{backend}` → returns the KNOWN_PRESETS list. Available for any backend that declares it, including unprovisioned subprocess backends (so the UI can still show the menu even when the backend isn't installable yet).
- [ ] `POST /v1/presets/{backend}/sample` → body: `{"preset_id": "...", "text": "..."}` → returns WAV; uses the backend's `synthesize` with a transient VoiceRef (not persisted to the registry). Returns 503 with `SubprocessBackendNotInstalled.message` if the backend isn't provisioned.
- [ ] Tests: list presets for each backend, sample a kokoro preset returns wav; sample a piper preset (provisioned) returns wav; sample melotts returns 503 if not provisioned
- Commit: `feat(server,lab): preset browser endpoints — list + on-the-fly sample for kokoro/piper/melotts`

## Phase B — `/lab` page UI [SEQ]

One file: `src/voice_forge/static/lab.html`. Big — probably 500-800 lines incl. CSS + JS. Build it in logical groups.

### B1. Page skeleton + persona/backend matrix

- [ ] Vertical layout per persona (accordion-style; one open at a time):
    ```
    ▼ Saga              [▶ play original ref]   [edit texts ▼]
        ┌─────────────────────────────────────────────────────────────────────────┐
        │ Backend       short  medium  long  knobs  match  notes                  │
        ├─────────────────────────────────────────────────────────────────────────┤
        │ f5            ▶     ▶      ▶     [▼]   [yes▼] [...]                     │
        │ f5-fast       ▶     ▶      ▶     [▼]   [yes▼] [...]                     │
        │ neutts        ▶     ▶      ✗     [-]   [par▼] [30s cliff]               │
        │ dia           ▶     ▶      ▶     [▼]   [no▼]  [acc lost]                │
        │ xtts          ▶     ▶      ▶     [▼]   [no▼]  [no accent]               │
        │ chatterbox    ▶     ▶      ▶     [▼]   [...]  [...]                     │
        │ piper         (preset-only — see preset browser)                        │
        │ kokoro        (preset-only — see preset browser)                        │
        │ melotts       (not provisioned)  voice-forge backend install melotts    │
        └─────────────────────────────────────────────────────────────────────────┘
    ▶ Heid
    ▶ Hnoss
    ...
    ```
- [ ] Persona list comes from `GET /v1/audio/voices` grouped by persona (already shipped)
- [ ] Backend rows come from `GET /v1/backends` (already shipped)
- [ ] "Original ref" button: `<audio>` element pointing at `/v1/voices/<persona-canonical-voice-id>/reference`
- [ ] "Speak short/medium/long" buttons: each is a WS connect → send the chosen text → play streaming PCM. Reuses the existing Web Audio scheduling code from /demo (factor into a shared `static/voice_audio.js` module? optional — inline first iteration).
- [ ] Per-row knob editor opens an inline panel with the backend's `KNOWN_TUNABLES` (re-uses the demo's existing knob-rendering logic).

### B2. Per-persona text editor

- [ ] "Edit texts" toggle reveals three textareas (short/medium/long) pre-loaded with the persona's current prompts from `GET /v1/personas/prompts`
- [ ] Save button → PUT to `/v1/personas/prompts/{persona}` with the three fields
- [ ] Per-row "▶ short / ▶ medium / ▶ long" buttons send the corresponding text via WS

### B3. Scorecard editor

- [ ] Per-cell `match` dropdown: yes / no / partial / (blank). PUT to `/v1/scorecard/{persona}/{backend}` on change.
- [ ] Per-cell `notes` text input (small). PUT on blur.
- [ ] Aggregate view at the bottom of the page:
    ```
    ┌─────────────────────────────────────────────┐
    │ Aggregate (match rate per backend)          │
    │  f5         8/9 personas ✓  (89%)            │
    │  neutts     6/9 ✓                            │
    │  dia        3/9 ✓                            │
    │  ...                                         │
    │                                              │
    │  match-rate per persona                      │
    │  saga      5/7 backends ✓                    │
    │  heid      2/7 ✓                             │
    │  ...                                         │
    └─────────────────────────────────────────────┘
    ```
- [ ] Refresh aggregate when any scorecard cell changes

### B4. Preset browser panel (separate section in /lab)

- [ ] Backend picker (kokoro for v0.3.x; piper/melotts greyed)
- [ ] Preset name dropdown populated from `GET /v1/presets/{backend}`
- [ ] Text input (default: "Can you hear me?")
- [ ] "Sample" button → POST to `/v1/presets/{backend}/sample` → play returned WAV inline
- [ ] "Copy name" button → puts the preset name on the clipboard so the user can `voice-forge voice add` it elsewhere

### B5. Wire-protocol streaming for speak buttons

- [ ] Each `▶` button opens a WS to `/v1/tts/stream`, sends `{"voice": <voice_id>, "sampling": <knob overrides>}`, streams text via the simplest possible flow (no token-trickle in /lab — text is known up front)
- [ ] Show first-audio + total-time per click (small inline label)
- [ ] Bonus: a "play in stream mode" toggle that adds the trickle from /demo — for testing the WS pipelining
- Commit: `feat(static,lab): /lab voice tuning workstation — persona grid + ref playback + scorecard + preset browser`

## Phase X — F5 default flip + `-fast` variant cleanup

Pre-requisite for Phase B's UI so the matrix doesn't show duplicate F5 rows. Runs before or alongside Phase A.

- [ ] Flip `DEFAULT_NFE_STEP` in `src/voice_forge/backends/f5.py` from `32` → `16`
- [ ] Update `F5Backend.KNOWN_TUNABLES["nfe_step"]["default"]` from `32` → `16`
- [ ] Update the `nfe_step` description in KNOWN_TUNABLES to reflect the new default ("16 = streaming default; 24-32 = higher-quality preset")
- [ ] Remove the `*-fast` voices from `.audition-registry/` (saga-comms-f5-fast, heid-research-f5-fast, hnoss-books-f5-fast) — they're redundant now that nfe_step=16 is the parent default
- [ ] Update DECISIONS.md: add a 2026-05-26 entry recording the default flip + the user-validation evidence from the 2026-05-25 long-form A/B
- [ ] Update LEARNINGS.md: note that the previous "nfe_step=16 is the streaming preset" learning is now superseded — 16 is the regular default; 32 is the opt-in "quality preset"
- [ ] Verify nothing in the existing tests was asserting `nfe_step == 32` as the F5 default — update if so
- Commit: `feat(backends,f5): flip nfe_step default from 32 to 16; drop redundant *-fast voices`

## Phase C — Initial seeding

### C1. Bootstrap persona_prompts.json from responses.yaml

- [ ] One-time script `scripts/bootstrap_persona_prompts.py` that:
    - Reads `tests/functional/responses.yaml`
    - For each persona, maps `p1_hear_me.template` → `short`, `responses[persona].p2` → `medium`, `responses[persona].p3` → `long`
    - Writes `tests/functional/persona_prompts.json`
- [ ] Run it once + commit the resulting JSON
- [ ] Document the script in a code comment as "ran once for v0.3; texts now edited via /lab"

### C2. Initial empty scorecard

- [ ] `tests/functional/voice_scorecard.json` starts as `{}`. Gets populated by user clicks in /lab.

## Phase D — Tests + journal

- [ ] Unit tests for each new endpoint (covered in Phase A)
- [ ] One integration test: server boot triggers persona-coverage, GET /v1/audio/voices then shows the auto-registered entries
- [ ] LEARNINGS entry: "Auto-registered persona × backend grid on startup — moved 30 voices into the registry in <1s"
- [ ] ARCHIVE entry: SHIPPED for the voice-lab work
- [ ] ROADMAP tick: add v0.3.x "/lab voice tuning workstation" + close it
- [ ] BACKENDS.md update: short note about the /lab surface + how to use the scorecard

## Critical files

**New:**
- `src/voice_forge/persona_coverage.py`
- `src/voice_forge/lab_state.py`
- `src/voice_forge/static/lab.html`
- `tests/functional/persona_prompts.json` (seeded from responses.yaml)
- `tests/functional/voice_scorecard.json` (starts empty)
- `scripts/bootstrap_persona_prompts.py`
- `tests/unit/test_persona_coverage.py`
- `tests/unit/test_lab_state.py`
- `tests/unit/test_lab_endpoints.py`

**Modify:**
- `src/voice_forge/server.py` — lifespan event, 6 new endpoints, KNOWN_PRESETS handling
- `src/voice_forge/backends/kokoro.py` — add KNOWN_PRESETS class attribute
- `docs/API_SPEC.md` — document the new endpoints
- `docs/engineering-journal/LEARNINGS.md` — auto-registration learning
- `docs/engineering-journal/ARCHIVE.md` — SHIPPED entry
- `docs/ROADMAP.md` — tick boxes

## Out of scope (call out so it's clear)

- **Cross-persona scorecard analytics** ("F5 matches best for these accents") — needs more data than scorecard can hold today. Punt.
- **Multi-user scorecards** — single scorecard per host, no per-user state. Punt.
- **Real-time scorecard collaboration** (multiple browsers editing simultaneously) — last-write-wins is fine. Punt.
- **Piper voice model auto-download UI** — Piper downloads voice ONNX files on first sample call. Should "just work" but might take 30-50 MB per voice. No UI for "preload all", "manage cache" yet — punt.

## Risks + mitigations

- **Auto-registration at startup adds boot-time work.** Mitigation: it's just metadata.json writes, no model loads. Should be sub-second for 30 voices. No-op when fleet.yaml absent.
- **Big `/lab` JS file.** Mitigation: keep it vanilla JS (no framework). Factor shared streaming code into a small reusable function. ~800 lines is fine; harder to maintain past 1500.
- **Persona-prompts schema drift if we add new text-length tiers later.** Mitigation: schema is open dict; new keys (e.g. `xshort`, `dialogue`) just slot in.
- **Scorecard write races between multiple tabs.** Mitigation: server-side lock during write; last write wins; reload on focus to pick up other-tab changes.
- **MeloTTS provisioning still blocked.** Mitigation: ship the preset list + sampler endpoint anyway; sampling returns 503 with a clear blocker message until provisioning works. Re-attempt install with rust toolchain during Phase A4 — if it works, full coverage; if not, document precise blocker.
- **F5 default flip breaks any external caller assuming nfe_step=32.** Mitigation: the per-voice sampling override still works; anyone wanting 32-step explicitly sets it. Changelog entry in ARCHIVE makes the flip visible.
- **Piper voice ONNX downloads on first sample call may take 30-50 MB + network.** Mitigation: first-call latency is the user's choice (they clicked Sample). Subsequent calls reuse the cached model.

## Verification

After all phases land:

1. `voice-forge serve` starts cleanly; logs show "ensure_full_coverage: created N voices, skipped M existing"
2. `curl http://127.0.0.1:9876/v1/audio/voices | jq '.data | length'` → ≥ 30
3. `open http://127.0.0.1:9876/lab` → page renders the persona accordion
4. Click "▶ play original" on Saga → ref WAV plays
5. Click "▶ short" on Saga × F5 → synth WAV plays
6. Edit Saga's medium text → Save → reload page → text persists
7. Set Saga × F5 match=yes, notes="great" → reload → persists; aggregate updates
8. Preset browser: pick Kokoro, pick `af_bella`, click Sample → wav plays
9. `cat tests/functional/voice_scorecard.json | jq` → looks structured and readable
10. `pre-commit run --all-files` + `pytest tests/ -q` → all gates green

## Notes

- `/demo` is untouched. Existing knob panel logic from `/demo` is duplicated in `/lab` (vanilla JS; no shared module needed for v1).
- Server startup time may grow by ~1-2s due to ensure_full_coverage. Acceptable.
- Persona list authoritative source: `tests/functional/fleet.yaml` (synced from home-lab Ansible). If the home-lab adds a sister, run the sync script, then restart voice-forge to pick it up.

## Review

[To be filled in after execution with a summary of what shipped, commit hashes, and any deviations from this plan.]
