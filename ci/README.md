# CI dependency lock

`requirements.in` contains the unchanged base + dev requirements and the build
backend requirements from `pyproject.toml`. `requirements.txt` pins their
transitive closure with PyPI distribution SHA-256 hashes for the Linux CPython
3.11/3.12 CI matrix. Optional model/VCS/backend extras are deliberately outside
this CI lock; runtime dependency constraints remain in `pyproject.toml`.

Regenerate on Linux with uv 0.13.4, then review the version/hash changes:

```sh
python3.11 scripts/ci_dependencies.py --write-input
uv pip compile ci/requirements.in --python-version 3.11 --generate-hashes \
  --only-binary :all: --no-header --no-annotate -o ci/requirements.txt
python3.11 scripts/ci_dependencies.py --stamp-lock
python3.11 scripts/ci_dependencies.py
```

Validate installation and the complete existing tests on **both** interpreters
before accepting a refresh. CI checks input drift before installation, requires
hashes, installs only wheels from the lock, then builds/installs the project
without dependency resolution or build isolation. The project install is a
regular wheel install; the locked build tools are sufficient without Hatchling's
additional editable-install dependencies. `uv pip check` verifies the resulting
environment. This lock is not a release qualification or publishing environment.

All ten static/hygiene hooks run once on Python 3.12. The Ruff/Black source scopes,
Mypy stubs, Bandit severity/config and hygiene thresholds are preserved. The
strict `mypy src` check also runs once on 3.12: it checks against the installed
application dependencies, whereas the isolated hook uses only its declared
stubs and adds blanket missing-import suppression. These are distinct checks;
collapsing them would lose coverage or change the hook dependency contract.
Bandit explicitly requests Python 3.12, as its upstream hook otherwise overrides
the default with `python3`.

Download and hook caches use platform, full interpreter version, uv version and
lock/config/script hashes. Restore failures and misses still execute the entire
installation and checks. Pull requests restore only; only successful `main`
push jobs may save. There are no virtualenv caches or release cache consumers.
