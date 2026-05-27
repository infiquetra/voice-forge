"""Post-install patcher for the Higgs Audio backend.

Why this exists
===============

The upstream ``boson_multimodal`` package (built from
``git+https://github.com/boson-ai/higgs-audio.git`` via setuptools' default
``find_packages``) silently drops two subdirectories that lack ``__init__.py``
markers at the source level: ``serve/`` and ``audio_processing/``. The audio
tokenizer required for voice cloning lives at
``boson_multimodal.audio_processing.higgs_audio_tokenizer`` — missing.

The reference inference script (``examples/generation.py``) in the same repo
DOES expect this module to be importable. Without it, no voice cloning.

This patcher is invoked by ``voice-forge backend install higgs`` AFTER the
main pip install completes. It clones the upstream repo to a cache dir and
copies the missing source trees into the venv's ``site-packages``,
synthesising the ``__init__.py`` files that should have been there to begin
with. Idempotent — re-running is a no-op if the modules are already
importable.

Upstream packaging defect is not yet filed as an issue (2026-05-26). When
they ship a fix, the simplest signal is that
``boson_multimodal.audio_processing.higgs_audio_tokenizer`` becomes
importable directly from pip — and this patcher's ``_needs_patch`` check
will return False, skipping the work.
"""

from __future__ import annotations

import logging
import shutil
import subprocess  # nosec B404 — git clone is the entire point
import sys
import tempfile
from pathlib import Path

logger = logging.getLogger("voice_forge.backends._higgs_post_install")

UPSTREAM_REPO = "https://github.com/boson-ai/higgs-audio.git"
# Pin a commit if we ever need reproducibility; for now follow main since
# the package itself is pinned through pip's git+https resolution.
UPSTREAM_REF = "main"

# Subtrees that need to be copied into site-packages because the wheel
# install dropped them. Path is relative to the upstream repo root; the
# destination mirrors that path under <site-packages>/boson_multimodal/.
MISSING_SUBTREES = (
    "audio_processing",
    # serve/ is intentionally omitted — voice-forge's _HiggsInProcess uses
    # the HiggsAudioModelClient direct-model pattern from upstream's
    # examples/generation.py, NOT the buggier ServeEngine wrapper.
)


def _venv_site_packages(venv_path: Path) -> Path:
    """Locate the venv's site-packages directory.

    Uses ``sysconfig`` under the venv's interpreter to avoid hardcoding the
    Python version into the path.
    """
    py = venv_path / "bin" / "python"
    if not py.is_file():
        raise FileNotFoundError(f"no python at {py} — venv not provisioned?")
    out = subprocess.check_output(  # nosec B603 — py path resolved above
        [
            str(py),
            "-c",
            "import sysconfig, sys; sys.stdout.write(sysconfig.get_paths()['purelib'])",
        ],
        timeout=10,
    )
    return Path(out.decode().strip())


def _needs_patch(site_packages: Path) -> bool:
    """True iff at least one required subtree is missing from the venv."""
    boson_root = site_packages / "boson_multimodal"
    if not boson_root.is_dir():
        # boson_multimodal itself isn't installed — pip install ran but
        # something's wrong. Bail rather than try to fix it; the caller
        # should re-run `backend install`.
        raise RuntimeError(
            f"boson_multimodal not installed in {site_packages}; "
            f"re-run `voice-forge backend install higgs` first"
        )
    for subtree in MISSING_SUBTREES:
        tokenizer_check = boson_root / subtree / "higgs_audio_tokenizer.py"
        # audio_processing's smoking-gun file is higgs_audio_tokenizer.py.
        # If that's present we assume the whole tree was installed properly
        # (upstream may have shipped a fix between releases).
        if subtree == "audio_processing" and not tokenizer_check.is_file():
            return True
        # For any other subtree, just check the directory exists.
        if subtree != "audio_processing" and not (boson_root / subtree).is_dir():
            return True
    return False


def _clone_upstream(dest: Path) -> None:
    """Clone the boson-ai/higgs-audio repo to ``dest`` at UPSTREAM_REF."""
    logger.info("cloning %s @ %s -> %s", UPSTREAM_REPO, UPSTREAM_REF, dest)
    subprocess.run(  # nosec B603 B607 — upstream URL pinned
        ["git", "clone", "--depth", "1", "--branch", UPSTREAM_REF, UPSTREAM_REPO, str(dest)],
        check=True,
        timeout=120,
    )


def _copy_subtree(src_repo_root: Path, subtree: str, site_packages: Path) -> None:
    """Copy ``src_repo_root/boson_multimodal/<subtree>/`` into the venv.

    Synthesises an ``__init__.py`` in the destination if upstream didn't
    ship one — that's the root cause of the wheel-exclusion bug so we
    have to materialise it explicitly. Also adds ``__init__.py`` files
    in any sub-subdirectories that lack one and contain Python source.
    """
    src = src_repo_root / "boson_multimodal" / subtree
    dst = site_packages / "boson_multimodal" / subtree
    if not src.is_dir():
        raise FileNotFoundError(f"upstream clone missing {src}")
    if dst.is_dir():
        # Stale partial copy — wipe + rewrite to keep the patcher idempotent.
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    # Materialise the missing __init__.py at the top of the copied tree.
    init_file = dst / "__init__.py"
    if not init_file.is_file():
        init_file.write_text(
            '"""Synthesised by voice_forge._higgs_post_install.\n\n'
            "Upstream boson_multimodal packaging drops this directory's\n"
            "__init__.py marker, breaking pip's package discovery. This\n"
            "file is materialised at backend install time so the modules\n"
            'inside become importable.\n"""\n'
        )
    # And in any subdirectories that contain .py files but no __init__.py.
    for sub in dst.rglob("*"):
        if sub.is_dir() and any(p.suffix == ".py" for p in sub.iterdir() if p.is_file()):
            sub_init = sub / "__init__.py"
            if not sub_init.is_file():
                sub_init.write_text('"""Synthesised by voice_forge._higgs_post_install."""\n')
    logger.info("patched %s (%d files)", dst, sum(1 for _ in dst.rglob("*.py")))


def run(venv_path: Path) -> None:
    """Entry point — invoked from cli.py:backend_install for the higgs backend.

    Args:
        venv_path: Per-backend venv root, e.g.
            ``~/.voice-forge/backends/higgs/.venv/``.
    """
    site_packages = _venv_site_packages(venv_path)
    if not _needs_patch(site_packages):
        logger.info("higgs venv already has audio_processing — skipping patch")
        return
    logger.info("higgs venv missing audio_processing tree — patching from upstream")
    with tempfile.TemporaryDirectory(prefix="higgs-upstream-") as tmp:
        clone_dir = Path(tmp) / "higgs-audio"
        _clone_upstream(clone_dir)
        for subtree in MISSING_SUBTREES:
            _copy_subtree(clone_dir, subtree, site_packages)
    logger.info("higgs post-install patch complete")


def main() -> None:
    """CLI entry point for standalone invocation (debugging / re-running)."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if len(sys.argv) != 2:
        sys.stderr.write("usage: python -m voice_forge.backends._higgs_post_install <venv_path>\n")
        sys.exit(2)
    run(Path(sys.argv[1]).expanduser())


if __name__ == "__main__":
    main()
