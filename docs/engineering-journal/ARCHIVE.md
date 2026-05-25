# Archive — Shipped + Rejected + Superseded Items

> Where QUEUED items go to die. **Never silently delete from QUEUED.md** — always move here so the trail stays intact.
>
> Conventions:
> - `## SHIPPED YYYY-MM-DD — Title` for completed work (include commit hash, PR link, brief recap)
> - `## REJECTED YYYY-MM-DD — Title` for items we decided against (include reason + revisit conditions)
> - `## SUPERSEDED YYYY-MM-DD — Title` for items replaced by a different approach (link to the replacement)

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
