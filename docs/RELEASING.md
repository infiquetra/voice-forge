# Releasing voice-forge-tts

> One-stop guide for cutting a release. Read this end-to-end the first time; subsequent releases follow the same sequence.

## Distribution name

Voice-forge publishes to PyPI under **`voice-forge-tts`**. The Python import name stays `voice_forge`. The bare `voice-forge` name on PyPI was already taken by an unrelated project before v0.1.0 went out the door.

## One-time setup (first release only)

### 1. Configure a Pending Publisher on PyPI

`voice-forge-tts` uses OIDC trusted publishing — no PyPI token is stored anywhere. You need to register the GitHub workflow as a trusted publisher BEFORE the first tag push, otherwise the publish step will fail.

1. Sign in at https://pypi.org with an account that will own the project.
2. Go to **Account Settings → Publishing → Add a new pending publisher**.
3. Fill in:
   - **PyPI Project Name:** `voice-forge-tts`
   - **Owner:** `infiquetra`
   - **Repository name:** `voice-forge`
   - **Workflow filename:** `publish.yml`
   - **Environment name:** `pypi` (must match the `environment:` key in `publish.yml`)
4. Save. The pending publisher persists until the first successful publish, then converts to a regular trusted publisher tied to the now-existing project.

### 2. (Optional) Configure TestPyPI as well

Repeat step 1 against https://test.pypi.org for `voice-forge-tts` with the same repo/workflow but environment name `testpypi`. Useful for dry-runs.

### 3. GitHub repo environments

In the repo settings → Environments, add two environments matching the trusted publishers:

- `pypi` (production)
- `testpypi` (optional, for dry-runs)

Add no secrets — OIDC handles auth.

## Per-release procedure

1. **Verify on Mac Studio** (manual smoke; no Apple Silicon runner in CI):
   ```bash
   brew install espeak-ng    # needed for Kokoro
   python -m build
   uv pip install --force-reinstall "dist/voice_forge_tts-${VERSION}-*.whl[neutts,kokoro,voice-lab]"
   voice-forge --version
   voice-forge health
   voice-forge synth saga-comms "Smoke test." /tmp/smoke.wav && afplay /tmp/smoke.wav
   voice-forge voice add kokoro-bella --backend kokoro --preset af_bella
   voice-forge synth kokoro-bella "Kokoro smoke." /tmp/smoke_k.wav && afplay /tmp/smoke_k.wav
   ```

2. **Run the audition harness** (catches timbre regressions by ear):
   ```bash
   python scripts/sync_fleet_from_home_lab.py --home-lab-path ~/workspace/infiquetra/home-lab
   python scripts/asgard_audition.py --output tests/functional/output/${VERSION}-smoke
   open tests/functional/output/${VERSION}-smoke/index.html
   ```
   Click through all 27 rows. Confirm p1 ("can you hear me?") is clean on every sister. Note p2 30-second-cliff degradation on NeuTTS sisters — that's expected.

3. **Update the journal**:
   - Move shipped QUEUED items to `docs/engineering-journal/ARCHIVE.md` with `## SHIPPED YYYY-MM-DD — title` + commit hash.
   - Tick ROADMAP boxes that landed.
   - Add LEARNINGS entries for anything surprising the release surfaced.

4. **Bump version** in one place: `src/voice_forge/__init__.py:__version__`. Everything else reads from there. Confirm `pyproject.toml:version` matches.

5. **Tag and push**:
   ```bash
   git tag v${VERSION}
   git push origin v${VERSION}
   ```

6. **Watch the publish workflow** at `https://github.com/infiquetra/voice-forge/actions`. On success, the new wheel + sdist appear at https://pypi.org/project/voice-forge-tts/.

7. **Verify install** from a clean Python env:
   ```bash
   uv pip install voice-forge-tts==${VERSION}
   voice-forge --version
   ```

8. **Update consumers**:
   - `infiquetra/home-lab/ansible/roles/hermes_neutts_daemon/defaults/main.yml`: bump `voice_forge_version` to `v${VERSION}` and switch `voice_forge_repo` from git URL to `voice-forge-tts` once you've confirmed the PyPI install works on the Mac mini.

## TestPyPI dry-run

If you want to rehearse a release without committing:

1. Tag an RC: `git tag v0.2.0-rc.1 && git push origin v0.2.0-rc.1`.
2. The workflow detects the rc and routes to TestPyPI (see `publish.yml`).
3. Verify:
   ```bash
   uv pip install --index-url https://test.pypi.org/simple/ voice-forge-tts==0.2.0rc1
   ```
4. Delete the rc tag locally + remote after verification.

## Rollback

PyPI doesn't allow re-uploading the same version. If a release is broken, **yank it** (don't delete) and ship a patch version with the fix.

```bash
# Yank a release via PyPI web UI: project page → Manage → Releases → Yank
# Then ship v${OLD}.${NEXT}+1:
git tag v0.2.1
git push origin v0.2.1
```

## License of release artifacts

voice-forge is Apache 2.0. The bundled `LICENSE` file is included in every wheel. No additional license disclosures needed unless transitive dependencies require them (none currently do).
