# Releasing voice-forge-tts

> One-stop guide for cutting a release. Read this end-to-end the first time; subsequent releases follow the same sequence.

## Qualification before publication

`publish.yml` calls the complete `ci.yml` through `workflow_call` at the caller's
commit. Both Python 3.11/3.12 test jobs must succeed, including all ten hooks and
both distinct Mypy gates on 3.12. The original CI hash-lock verifier and normal
wheel installation remain. Checkout uses the caller SHA with full history;
`scripts/release_artifacts.py source` checks HEAD, repository, event payload and
ref identity. A tag must resolve to that same commit. Annotated tag objects are
checked separately from the commit they identify. An unrelated successful main
run cannot authorize a release. Tag qualification restores and saves no CI
caches; PRs retain restore access and successful main pushes remain the writers.

Release source admission also requires the tag's version to equal the project
version. Wheel/sdist metadata and the installed runtime version must agree after
the same normalization. This check runs before a tag can pass source admission,
before manifest creation and again before a publisher can consume the bundle.

The verifier deliberately supports a bounded PEP 440 release grammar with three
ASCII integer components, optionally followed by an explicit numbered prerelease:

```text
X.Y.Z[SEP PHASE SEP N]
SEP   = absent, "-", "_", or "." (independently at each position)
PHASE = a, alpha, b, beta, or rc (case-insensitive)
X, Y, Z, N = one or more ASCII digits
```

The tag has a literal lowercase `v` prefix. Numeric leading zeros are removed;
`alpha` becomes `a`, `beta` becomes `b`, and prerelease letters become lowercase.
For example, project `0.3.0-RC.01`, tag `v0.3.0-rc.1` and distribution metadata
`0.3.0rc1` identify the same version. Distribution filenames and archive roots
must use the normalized version. Equivalent metadata spellings compare by this
normalization; duplicate Version fields still fail. Epochs, local/post/dev
versions, extra/missing release components, implicit prerelease numbers,
`c`/`pre`/`preview` aliases, whitespace and other forms fail closed. Supporting
any of those requires a reviewed release-contract change. This bounded grammar
implements the applicable [PEP 440 normalizations](https://packaging.python.org/en/latest/specifications/version-specifiers/#normalization)
using the standard library, including before the build environment exists; it
requires no runtime dependency or verifier tool bootstrap.

Destination selection continues to use the original tag spelling: case-insensitive
`-rc.`, `-alpha.` and `-beta.` markers select TestPyPI; other accepted spellings
select PyPI. Thus `v0.3.0rc1` retains its existing PyPI route. Version normalization
does not change this routing. PR/main qualification has no release tag to compare
and still validates the project/distribution version contract.

After the matrix succeeds, `release-qualification.yml` builds one wheel and one
sdist using Hatchling 1.33.0 in a separate fresh build environment. It does not
use the CI-only dependency lock or restore release artifacts/environments. The
manifest binds repository, event, ref, SHA, run ID/attempt, artifact name, project
metadata and each distribution's filename, size and SHA-256. Its digest travels
through producer job/workflow outputs, independently of the downloaded files.
The immutable upload's artifact ID also travels through these outputs. Consumers
select that exact ID in the current run, without cross-run tokens or selection
inputs, and reject unexpected files, duplicate archive members, stale identities,
metadata mismatches and changed bytes. The download action's digest warning is
not the admission gate. See the pinned
[download implementation](https://github.com/actions/download-artifact/blob/d3f86a106a0bac45b974a628896c90dbdf5c8093/src/download-artifact.ts).

Both supported interpreters smoke-install the exact wheel, with base dependencies
only, in newly created environments outside the checkout. Isolated Python checks
installed metadata, entry points, runtime version, the wheel URL/digest recorded
by pip, and representative package imports whose resolved origins must be inside
the fresh environment. No optional model/GPU extras are requested. Both publish
jobs recheck source identity and distribution hashes immediately before the
existing PyPA action consumes these original files. Nothing rebuilds or repacks
them after smoke testing.

Ordinary PR/main CI exercises this same build/download/verification/smoke path
with `contents: read` and no publishing job or OIDC grant. A successful PR proves
its merge SHA and artifact only; it is not tag or publication evidence. The tag
workflow retains the `testpypi` and `pypi` environments and job-only
`id-token: write`. Each publisher additionally needs `contents: read` to check out
the exact candidate's verifier, with persisted checkout credentials disabled.
Environment approvals and trusted-publisher registrations are unchanged.

CI cancels obsolete PR validation only. Publication has a tag-specific concurrency
group with cancellation disabled; reusable CI uses a separate group prefix.
The 10-minute matrix deadline is conservative relative to observed successful
3.11/3.12 jobs of about 20/73 seconds in
[run 40970794543](https://github.com/infiquetra/voice-forge/actions/runs/40970794543).
Build, smoke and publish each start with a 10-minute bound; these initial bounds
are not measured release durations and should be revisited using hosted evidence.
Direct actions are pinned to reviewed official commits on their existing major
lines. GitHub documents same-commit local reusable workflow selection and caller
context in [workflow reuse](https://docs.github.com/en/actions/how-tos/reuse-automations/reuse-workflows).

Before first release use, require a successful hosted PR matrix/build/smoke run
for the reviewed source and independent review of the tag gate and OIDC boundary.
Record the candidate SHA/ref, run/attempt, artifact ID, producer manifest digest,
distribution digests and installed origins. Local synthetic negative controls
exercise verifier failures and dependency reachability; they cannot prove hosted
tag execution. A real tag push separately requires the full cold qualification.

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

4. **Bump both authoritative version surfaces**:
   `src/voice_forge/__init__.py:__version__` for runtime reporting and
   `pyproject.toml:project.version` for wheel metadata. The unit suite enforces
   their equality.

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

## TestPyPI publication

PR CI provides a rehearsal without package-index writes. TestPyPI rehearsal is
an actual publication, selected by the existing `-rc.`, `-alpha.` or `-beta.` tag
markers. When an operator chooses to publish a release candidate:

1. Tag an RC: `git tag v0.2.0-rc.1 && git push origin v0.2.0-rc.1`.
2. The workflow detects the rc and routes to TestPyPI (see `publish.yml`).
3. Verify:
   ```bash
   uv pip install --index-url https://test.pypi.org/simple/ voice-forge-tts==0.2.0rc1
   ```
4. Delete the rc tag locally + remote after verification.

## Rollback

For a workflow defect, revert the workflow/helper change; an operator can disable
the affected workflow while preparing a fix. Reverting source or deleting a tag
does not undo a package-index publication.

PyPI doesn't allow re-uploading the same version. If a release is broken, **yank it** (don't delete) and ship a patch version with the fix.

```bash
# Yank a release via PyPI web UI: project page → Manage → Releases → Yank
# Then ship v${OLD}.${NEXT}+1:
git tag v0.2.1
git push origin v0.2.1
```

## License of release artifacts

voice-forge is Apache 2.0. The bundled `LICENSE` file is included in every wheel. No additional license disclosures needed unless transitive dependencies require them (none currently do).
