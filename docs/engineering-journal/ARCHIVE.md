# Archive — Shipped + Rejected + Superseded Items

> Where QUEUED items go to die. **Never silently delete from QUEUED.md** — always move here so the trail stays intact.
>
> Conventions:
> - `## SHIPPED YYYY-MM-DD — Title` for completed work (include commit hash, PR link, brief recap)
> - `## REJECTED YYYY-MM-DD — Title` for items we decided against (include reason + revisit conditions)
> - `## SUPERSEDED YYYY-MM-DD — Title` for items replaced by a different approach (link to the replacement)

---

## SHIPPED 2026-05-24 — v0.1.0: NeuTTS backend + FastAPI server + CLI + voice lab + tests (Phase D)

**Commit:** `1e9c583`
**From QUEUED P1:** "Phase D: implement v0.1.0 (NeuTTS backend + server + CLI + tests)"

Ports the v6 NeuTTS daemon from `infiquetra/home-lab` into `src/voice_forge/backends/neutts.py` with all three monkey-patches preserved verbatim (`n_ctx=8192`, `repeat_penalty=1.05` injection via `Llama.__call__` wrap, `watermarker=None` post-construction). Adds FastAPI server with the OpenAI-compatible `/v1/audio/speech` endpoint, Click-based CLI with `serve`/`synth`/`voices`/`voice add`/`voice from-elevenlabs`/`voice delete`/`health` commands, FS-backed Registry under `~/.voice-forge/voices/<voice_id>/`, voice lab utilities (ElevenLabs preview pull + Whisper-based sentence-boundary trim), unit + integration test scaffolding, single-stage Dockerfile, and GitHub Actions CI for lint/format/type-check/tests.

**Outcome:** The engine works on a single backend with the abstractions in place. **What's not yet proven:** that the abstractions hold — server.py:60-64 and cli.py:27-32 still hard-code `if name == "neutts"` dispatch, so the registry isn't actually exercised. v0.2 closes that gap.
