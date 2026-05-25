# Archive — Shipped + Rejected + Superseded Items

> Where QUEUED items go to die. **Never silently delete from QUEUED.md** — always move here so the trail stays intact.
>
> Conventions:
> - `## SHIPPED YYYY-MM-DD — Title` for completed work (include commit hash, PR link, brief recap)
> - `## REJECTED YYYY-MM-DD — Title` for items we decided against (include reason + revisit conditions)
> - `## SUPERSEDED YYYY-MM-DD — Title` for items replaced by a different approach (link to the replacement)

---

## REJECTED 2026-05-25 — VibeVoice backend (Microsoft pulled the model)

**From QUEUED P2:** "VibeVoice backend (long-form narrative quality)"
**From ROADMAP v0.3:** "VibeVoice backend (if licensing checks out)"

**Why rejected.** Microsoft removed `VibeVoice-TTS-1.5B` from the
`microsoft/VibeVoice` public repository in September 2025, citing
"instances where the tool was used in ways inconsistent with the stated
intent" (deepfake misuse). The 1.5B TTS model with cloning + long-form
multi-speaker coherence — the variant voice-forge would have wanted —
**is no longer obtainable from upstream**. Even if weights could be found
mirrored elsewhere, depending on a deliberately-withdrawn model is the
wrong move for a downstream library.

**What's still available from the VibeVoice family (and why it doesn't
fit voice-forge's mission):**
- **VibeVoice-Realtime-0.5B**: Streaming + 10-minute long-form context.
  MIT code, available on HF. **But preset voices only** — Microsoft
  explicitly designed it with "voice prompts in embedded format" to
  prevent cloning misuse. ~11 English + 9 multilingual stock voices.
  Could be added as a "Kokoro with streaming" preset backend, but
  doesn't address voice-forge's core use case (cloning the Asgard
  fleet's personas).
- **VibeVoice-ASR-7B**: Speech recognition, not synthesis. Out of scope
  for voice-forge entirely — that's `infiquetra/voice-listen` territory.

**What replaces VibeVoice in the long-form-cloning niche.**
**F5-TTS** (shipped in v0.2 commit `60db36a`) closes the same gap:
clean cloning + no 30-second cliff. The v0.2 audition shows F5 reading
71-86 s coherently with the Asgard sister refs (Saga + Hnoss held;
Heid drifted, traced to a ref-WAV issue and not a backend problem).
F5 is MIT-wrapper + Apache-2 weights — no withdrawal risk.

**Revisit-when.** If Microsoft releases a non-clone-capable but
streaming preset model (VibeVoice-Realtime expansion) we like better
than Kokoro, **and** voice-forge needs streaming-text-during-synth
behavior we can't get from Kokoro's per-segment yielding. Until then,
no further evaluation effort spent on the VibeVoice line.

**Generalizable rule.** **Track "backend candidate" status against
upstream availability, not just license + capability.** A model that
WAS shipped + accessible can become unavailable. The audition
infrastructure can't help us reach a model the original publisher
has withdrawn. PRIOR_ART.md gets a hygiene pass: every candidate
needs a "still actively published" check column, not just license.

**Refs.** Microsoft's official statement on the removal is in the
`microsoft/VibeVoice` README dated 2025-09-05 ("we have removed the
VibeVoice-TTS code from this repository"). Upstream URLs:
- https://github.com/microsoft/VibeVoice — repo (now ASR + Realtime only)
- https://huggingface.co/microsoft/VibeVoice-Realtime-0.5B — the
  preset-only streaming variant that survived

---

## SHIPPED 2026-05-25 — v0.2: Dia-1.6B backend (Nari Labs, multi-speaker + cloning, Apache-2)

**Commit:** (this commit; latest on the `worktree-v0.2-pluggable-proof` branch)
**From ROADMAP v0.3 (pulled forward):** "Dia backend (first community wrapper; multi-speaker via [S1]/[S2] tags)"

Adds `src/voice_forge/backends/dia.py` using the **native HuggingFace Transformers integration** (no separate pip install — `transformers>=4.46` ships `DiaForConditionalGeneration` directly). Apache-2 model weights + Apache-2 repo. Voice-forge's first multi-speaker-capable backend (`[S1]`/`[S2]` tags in input text).

13 new tests in `tests/unit/test_dia_backend.py` cover load, the Dia-specific prompt format (`[S1] {ref_text} [S1] {gen_text}`), sample-rate resampling (44.1 → 24 kHz), sampling params threading, guard rails. Fake stub at `tests/_stubs/fake_dialib.py` monkey-patches `transformers.AutoProcessor` + `transformers.DiaForConditionalGeneration` rather than swapping the whole `sys.modules["transformers"]` (which would break fastapi imports). Full suite: 113 passed.

Audition (`tests/functional/output/v0.2-dia-20260525T055909Z/`) on the 3-sister test fleet (saga/heid/hnoss) revealed material caveats:

| Aspect | Outcome |
|---|---|
| Cloning fidelity | **Mixed** — Heid wrong-gender; Saga/Hnoss closer to ref but not at F5's level |
| Long-form (p3 ~80s text) | **Truncated to 18-21 s** by default `max_new_tokens=3072` cap |
| Heid p1 short utterance | **0.19 s broken** — same failure mode as NeuTTS p1 |
| Audio pacing | **Faster than NeuTTS/F5/Kokoro/XTTS** on same text — Dia's documented "long input → unnaturally fast speech" behavior |
| RTF on M2 Ultra MPS | ~3-5 (slowest backend voice-forge ships) |
| Cold load | ~120 s including 3 GB HF download |

User listening verdict 2026-05-25: "voices [are] too fast and even wrong gender in heid's case."

**Three new LEARNINGS captured:**
1. **Heid's ref WAV breaks autoregressive sampling specifically** — third backend (NeuTTS + Dia + reproduction) to fail on Heid p1 with 0.16-0.20 s output. F5 + Kokoro + XTTS (all non-autoregressive samplers) handle the same ref cleanly. The ref WAV is the bug, not the backend.
2. **Dia `max_new_tokens=3072` empirically caps at ~18-21 s** (not theoretical 35.7 s) because the ref-transcript prefix consumes budget. First concrete use case for per-voice tunable params.
3. (XTTS finding from earlier) ... unchanged.

`pyproject.toml`: `[dia] = ["transformers>=4.46,<5", "librosa>=0.10"]` — no new heavy install since transformers + librosa are already in the venv via other backends. `all` extra includes dia. `_BACKEND_MODULES` registers `"dia"`. mypy override adds `soundfile` + `librosa` (now actually used).

`docs/BACKENDS.md` gets a full Dia section with the four-caveat list (max_new_tokens cap, Heid ref-WAV failure, faster pacing, 15-min audition wall-clock) and a "when to use Dia anyway" subsection focused on the unique multi-speaker capability. `docs/ROADMAP.md` ticks Dia as shipped early.

**v0.2 status after Dia:** 5 backends shipped (NeuTTS, Kokoro, F5, XTTS, Dia). The pluggable abstraction validated across 5 architectural paradigms (autoregressive llama-cpp / encoder-decoder / diffusion / decoder-with-CFG / autoregressive transformer-token).

---

## SHIPPED 2026-05-25 — v0.2: XTTS-v2 backend (Coqui idiap fork, multilingual cloning)

**Commit:** (this commit; latest on the `worktree-v0.2-pluggable-proof` branch)
**From ROADMAP v0.3 (pulled forward):** "XTTS-v2 backend (Coqui, MPL-2, multilingual + voice cloning)"

Adds `src/voice_forge/backends/xtts.py` wrapping `coqui-tts==0.27.5` from the [idiap fork](https://github.com/idiap/coqui-ai-TTS) of the now-discontinued upstream Coqui project. Library license MPL-2; **model weights are CPML (non-commercial)** — backend's `load()` requires `COQUI_TOS_AGREED=1` env var as the consent gate.

Cross-backend audition results (XTTS-only fleet at `tests/functional/output/v0.2-xtts-20260525T053201Z/`, comparison to F5/Kokoro/NeuTTS at the prior triple-backend dir):

| Aspect | Outcome |
|---|---|
| Audio quality | **Cleanest of the four backends** — no stutter, no artifacts |
| 30-second cliff | None — all p3 stories ran 61-66 s coherently |
| Voice-identity cloning | **0/3 sisters preserved** — pitch + gender adapt, accent + persona character lost |
| RTF (M2 Ultra CPU) | 1.57 |
| RTF (M2 Ultra MPS) | 8.18 (5× slower than CPU due to per-op fallback churn) |
| Resident RSS | ~2.0 GB |

User listening verdict 2026-05-25: "All sounded good, no accent on a single one. But no stutter or poor quality." → XTTS is the right backend for "any clean female voice" use cases (system notifications, generic narration) but **does not replace NeuTTS for persona TTS**.

13 new tests in `tests/unit/test_xtts_backend.py` cover load, device pick, the CPML preflight (positive + negative paths), language threading from metadata, missing-ref-audio rejection, ref_text-not-needed behavior, and the synthesize_stream single-chunk degradation. Fake stub at `tests/_stubs/fake_xttslib.py` (mirrors fake_f5lib pattern). Full suite: 100 passed.

Three substantive LEARNINGS captured from XTTS bring-up:
1. **Cloning fidelity is a spectrum, not binary** — XTTS's failure to preserve accent surfaces a classification axis (identity-preserving vs pitch/gender-adapter vs no-clone) that PRIOR_ART had been glossing over.
2. **XTTS license is split** — library MPL-2 vs model CPML. PRIOR_ART had it as just MPL-2.
3. **MPS is 5× slower than CPU on M2 Ultra for XTTS** — opposite of F5, which prefers MPS. Device picks are per-backend codebase-coverage-dependent, not just per-model.

Pyproject: `[xtts] = ["coqui-tts>=0.27,<0.30", "transformers<5"]` (the transformers pin is doc'd inline). `all` extra includes xtts. mypy override for `TTS` + `TTS.*`. `_BACKEND_MODULES` registers `"xtts": "voice_forge.backends.xtts"`.

`docs/BACKENDS.md` gets a full XTTS section with the license split called out explicitly + the device-pick warning + the cloning-fidelity disclaimer at the comparison table. `docs/ROADMAP.md` ticks XTTS as shipped early.

**Effort.** ~3 hours including the license-prompt debugging detour, the transformers version conflict, and the controlled CPU-vs-MPS bench. Net new tests: 13. Files touched: 9.

---

## SHIPPED 2026-05-25 — v0.2: F5-TTS backend (cloning + long-form, diffusion-based)

**Commit:** (this commit; latest on the `worktree-v0.2-pluggable-proof` branch)
**From ROADMAP v0.3 (pulled forward):** "F5-TTS backend (Apache-2, diffusion-based, voice cloning)"

Adds `src/voice_forge/backends/f5.py` wrapping `f5-tts==1.1.20` (MIT wrapper from `SWivid/F5-TTS`; Apache-2 model weights). Drop-in to the cloning-arm of `VoiceRef` — same `(ref_audio_path, ref_text)` shape as NeuTTS, so the registry / dispatch / CLI / audition all work unchanged.

Cross-backend audition (`tests/functional/output/v0.2-triple-20260525T045249Z/`) on identical Asgard sister refs from `infiquetra/home-lab`. **Bench numbers vs NeuTTS + Kokoro on M2 Ultra:**

| Backend | Cold load | Resident RSS | RTF | Long-form |
|---|---|---|---|---|
| NeuTTS Q8 | 26.1 s | 5.6 GB | 0.80 | rots past ~30 s |
| Kokoro 82M | 3.6 s | 1.4 GB | 0.07 | preset only |
| **F5-TTS** | **37.6 s** (incl. weight DL) | **1.5 GB** | **1.05** | **clean 71-86 s** |

F5 closes the gap NeuTTS leaves open: cloning **and** long-form coherence. The user's audition verdict: "F5 sounds great. Held saga and hnoss's, but lost heid's." Heid drift is a voice-fidelity-variance finding (see [LEARNINGS § F5 voice-fidelity variance](../engineering-journal/LEARNINGS.md)) — tracked for follow-up via seed + CFG sweep + per-voice tuning.

11 new tests in `tests/unit/test_f5_backend.py` cover load, synthesize, synthesize_stream degradation, missing-ref guard rails, nfe_step plumbing, and the not-loaded RuntimeError. `tests/_stubs/fake_f5lib.py` uses sys.modules injection (same pattern as fake_neuttslib + fake_kokorolib).

`pyproject.toml` gets `[project.optional-dependencies] f5 = ["f5-tts>=1.1,<2.0"]`; `all` extra includes it; mypy override entries for `f5_tts` + `f5_tts.*`. `_BACKEND_MODULES` registers `"f5": "voice_forge.backends.f5"`.

Three LEARNINGS entries: F5 resource profile (bench), F5 voice-fidelity variance (Heid drift), and a separate "NeuTTS HTTP 500 on hnoss-books p1" entry capturing the **first hard NeuTTS failure** seen during the combined-backend audition (root cause TBD — evidence-toward-NeuTTS-retirement).

`docs/BACKENDS.md` gets a full F5 section with the bench table, F5-specific quirks (slow-but-realtime RTF, no cliff, voice-fidelity variance, `speed=` not yet plumbed), and an updated deployment-host capacity table reflecting the M2 Ultra (128 GB) dev host. `docs/ROADMAP.md` ticks F5 as shipped early.

---

## SHIPPED 2026-05-24 — v0.2: Asgard audition harness + PyPI publish workflow

**Commit:** (this commit; latest on the `worktree-v0.2-pluggable-proof` branch)
**From v0.2 plan §5+§6** — closes "PyPI publishing pipeline" QUEUED P3 + delivers the audio-audition surface user-asked for during planning.

Adds two operator scripts under `scripts/`:

- `sync_fleet_from_home_lab.py` reads `infiquetra/home-lab/ansible/roles/hermes_neutts_daemon/defaults/main.yml :: neutts_daemon_personas` and writes `tests/functional/fleet.yaml` with the 9 Asgard sisters, each assigned a unique male Norse-god `target_agent` (Thor, Loki, Odin, Heimdall, Tyr, Baldur, Bragi, Vidar, Vali). Idempotent; re-run on home-lab inventory changes.

- `asgard_audition.py` starts `voice-forge serve` in the background, POSTs 27 synth requests (9 sisters × 3 prompts), writes WAVs to `tests/functional/output/<run_id>/`, generates an HTML index with `<audio controls>` rows grouped by sister, and SIGTERMs the server on exit. Gracefully handles `(not registered)` and `(no response cached)` rows — partial runs are still reviewable.

Three companion files under `tests/functional/`:

- `prompts.yaml` — 3 hand-authored prompts per sister (p1 sanity check, p2 30-second introduction, p3 free-form story).
- `responses.yaml` — pre-captured persona responses keyed by sister `id`, each carrying a `captured:` date that surfaces in the HTML index.
- `README.md` — full review procedure, what to listen for per prompt (including the expected NeuTTS 30-second cliff on p2), and the refresh procedure for `responses.yaml`.

Adds `.github/workflows/publish.yml` — tag-triggered OIDC trusted publishing. Tags matching `v*.*.*` build wheel + sdist with `python -m build`; release tags (no `-rc.* / -alpha.* / -beta.*` suffix) go to PyPI's `voice-forge-tts` project; pre-release tags route to TestPyPI for dry runs. **One-time manual setup before first tag push:** create a Pending Publisher on pypi.org and (optionally) test.pypi.org per the procedure in `docs/RELEASING.md`.

CI matrix and gates updated: `ruff` and `black --check` now cover `src tests scripts` (was `src tests`); `mypy src` still no-error-tolerated; pytest unchanged.

**Verification.** `voice-forge --version` reports `0.2.0` from the wheel; `scripts/sync_fleet_from_home_lab.py --home-lab-path ~/workspace/infiquetra/home-lab` produces a 9-sister fleet.yaml with unique targets; `scripts/asgard_audition.py --help` works; tests 68 passed / 4 skipped; ruff + black + mypy clean.

---

## SHIPPED 2026-05-24 — v0.2: Kokoro backend (validates preset_id arm of VoiceRef)

**Commit:** `679e23b`
**From QUEUED P2:** "Kokoro backend (validates preset_id arm of VoiceRef)"

Adds `src/voice_forge/backends/kokoro.py` wrapping `hexgrad/kokoro==0.9.4` (Apache-2, PyTorch). Validates the `preset_id` arm of `VoiceRef`: NeuTTS uses `(encoded_codes, ref_text)`, Kokoro uses a string voice name passed through to `KPipeline(text, voice=name)`. The dispatch refactor from PR 2 carries it — `voice-forge synth kokoro-bella "Hello."` works without any code path being aware of "kokoro" specifically.

Adds `tests/_stubs/fake_kokorolib.py` + `tests/unit/test_kokoro_backend.py` (12 tests) using sys.modules injection. Real `kokoro` lib is opt-in via `pip install voice-forge-tts[kokoro]` + `brew install espeak-ng` (the misaki[en] G2P system dep).

**Trade-off captured.** Dropped Python 3.13 from voice-forge's classifiers + CI matrix because the published `kokoro==0.9.4` wheel declares `requires-python <3.13`. Detailed in [LEARNINGS 2026-05-24 § Kokoro library pick](../engineering-journal/LEARNINGS.md).

---

## SHIPPED 2026-05-24 — v0.2: Voice-mixing syntax parser (`name(weight)+name(weight)`)

**Commit:** `679e23b`
**From QUEUED P3:** "Voice mixing syntax (`name(weight)+name(weight)`)"

Adds `src/voice_forge/backends/_mixing.py` with `parse_mix()`. Single-voice specs (`af_bella`) and weighted multi-voice mixes (`af_bella(2)+af_sky(1)`) parse to `[(name, weight), ...]`. Empty / malformed input rejected with clear error messages.

15 tests in `tests/unit/test_voice_mixing.py` cover bare names, integer/decimal weights, multi-voice mixes, whitespace tolerance, and the rejection cases (empty spec, empty tokens, unbalanced parens, non-numeric weights, negative weights, special chars in names).

**Partial ship.** Kokoro's `KokoroBackend._resolve_voice` runs the parser correctly for all specs, but multi-voice mixes currently degrade to "pick the highest-weight voice + log a warning" because the upstream API for accessing per-voice embedding tensors via `KPipeline` isn't pinned down. Tensor-blending is requeued under P3 in QUEUED.md for v0.2.x. See [LEARNINGS 2026-05-24 § Kokoro voice-mixing tensor blending](../engineering-journal/LEARNINGS.md).

---

## SHIPPED 2026-05-24 — v0.2: Backend dispatch refactor (drops the hard-coded if/else in server.py + cli.py)

**Commit:** `ed0a7ba`
**No matching QUEUED entry** — this was tail of the "Phase D shipped without exercising the registry" story, surfaced during v0.2 planning.

Adds `_BACKEND_MODULES` (name → import-path map) and `load_backend_module()` to `backends/__init__.py`. `server.py:_ensure_backend` and `cli.py:_load_backend_or_exit` route through the helper; KeyError → 503 (unknown name), ImportError → 503 with install hint (`pip install voice-forge-tts[kokoro]`). The CLI's `health` command iterates `known_backends()` and quietly skips uninstalled ones so a partial install (e.g. `[neutts]` only) still reports usable state.

15 new tests cover `known_backends()`, `load_backend_module()` raise paths, and the load-and-register happy path (using `tests/_stubs/fake_backend_for_dispatch.py` so `importlib.import_module` actually executes the registration side effect — sys.modules pre-injection would skip body execution and miss it).

`git grep "if name == \"neutts\""` returns zero hits in `src/` after this PR.

---

## SHIPPED 2026-05-24 — v0.2: NeuTTS backend body test coverage (~70% of neutts.py)

**Commit:** `ed0a7ba`
**Driven by:** PR 2 cleanup — couldn't refactor dispatch confidently with 0% coverage on the only existing backend.

Adds `tests/_stubs/fake_neuttslib.py` (Fake `neutts.NeuTTS` + `llama_cpp.Llama` injected via `sys.modules.setitem`) + `tests/unit/test_neutts_backend.py` (12 tests). Covers `load()`, `health()`, `encode_reference()`, `synthesize()`, `synthesize_stream()`, all three `_resolve_ref` branches, and the not-loaded RuntimeError paths.

**What we did NOT test (intentional).** The three monkey-patches (`n_ctx=8192`, `repeat_penalty=1.05` injection, `watermarker=None`) at the lib boundary — those need a real `llama_cpp` and `neutts` install to exercise meaningfully. Manual Mac Studio smoke covers them. The fake-class patches run during `load()` without exploding; that's what unit-level can prove.

---

## SHIPPED 2026-05-24 — v0.2: mypy strict (no continue-on-error in CI)

**Commit:** `ed0a7ba`
**Driven by:** PR 2 cleanup — the v0 CI loosened mypy with `continue-on-error: true` while implementation landed.

Removes the `continue-on-error: true` flag from the mypy step in `.github/workflows/ci.yml`. Adds a mypy override section in `pyproject.toml` for the optional-dep libraries that don't ship type stubs (`neutts`, `llama_cpp`, `faster_whisper`, `kokoro`); fixes a `tuple[list, str]` narrowing in `neutts.py:_resolve_ref` (`encode_reference()` returns `list | None` per Protocol but NeuTTS's impl always returns a list — `assert codes is not None`).

mypy now passes cleanly in CI on Python 3.11 and 3.12.

---

## SHIPPED 2026-05-24 — v0.2: cleanup tail (version harmonize, dist rename, journal hygiene)

**Commit:** `cd00cbd`
**Driven by:** v0.2 plan §7 — drift surfaced during pre-execution verification.

Single-source `__version__ = "0.2.0"` in `src/voice_forge/__init__.py`; six previously-drifting sites now read from it (FastAPI app, /health endpoint, CLI --version, CLI health subcommand, pyproject.toml, test_cli_smoke version assertion).

PyPI distribution renamed from `voice-forge` to `voice-forge-tts` because the bare name on PyPI was taken by an unrelated project (Hemanth HM's Chatterbox TTS wrapper, v1.0.0). Python import path unchanged (`import voice_forge` still works). Explicit `[tool.hatch.build.targets.wheel] packages = ["src/voice_forge"]` added so hatchling can find the package despite the name mismatch.

Drops `httpx` from base deps (verified unused — voice_lab uses urllib.request). Drops `Programming Language :: Python :: 3.13` classifier (blocked by `kokoro==0.9.4` requires-python `<3.13`).

Fixes `/tmp/voice_forge_upload_{voice_id}.wav` leak at `server.py:register_voice` via `tempfile.NamedTemporaryFile` + `finally` unlink. Wraps synchronous Whisper `transcribe()` in `fastapi.concurrency.run_in_threadpool`.

Moves `_porting/` (v6 NeuTTS daemon + client snapshot from pre-spin-out) to `docs/engineering-journal/narratives/_attachments/v6-daemon-snapshot/` with a provenance README. Adds `docs/RELEASING.md`. Bumps README/ROADMAP for v0.2.

---

## SHIPPED 2026-05-24 — v0.1.0: NeuTTS backend + FastAPI server + CLI + voice lab + tests (Phase D)

**Commit:** `1e9c583`
**From QUEUED P1:** "Phase D: implement v0.1.0 (NeuTTS backend + server + CLI + tests)"

Ports the v6 NeuTTS daemon from `infiquetra/home-lab` into `src/voice_forge/backends/neutts.py` with all three monkey-patches preserved verbatim (`n_ctx=8192`, `repeat_penalty=1.05` injection via `Llama.__call__` wrap, `watermarker=None` post-construction). Adds FastAPI server with the OpenAI-compatible `/v1/audio/speech` endpoint, Click-based CLI with `serve`/`synth`/`voices`/`voice add`/`voice from-elevenlabs`/`voice delete`/`health` commands, FS-backed Registry under `~/.voice-forge/voices/<voice_id>/`, voice lab utilities (ElevenLabs preview pull + Whisper-based sentence-boundary trim), unit + integration test scaffolding, single-stage Dockerfile, and GitHub Actions CI for lint/format/type-check/tests.

**Outcome:** The engine works on a single backend with the abstractions in place. **What's not yet proven:** that the abstractions hold — server.py:60-64 and cli.py:27-32 still hard-code `if name == "neutts"` dispatch, so the registry isn't actually exercised. v0.2 closes that gap.
