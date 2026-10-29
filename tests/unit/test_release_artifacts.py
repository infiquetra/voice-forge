"""Executable admission controls; synthetic event data never establishes tag proof."""

from __future__ import annotations

import importlib.util
import io
import json
import re
import shutil
import subprocess
import sys
import tarfile
import warnings
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from packaging.version import Version

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "release_artifacts", ROOT / "scripts/release_artifacts.py"
)
assert SPEC and SPEC.loader
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)
SHA = "a" * 40
OTHER = "b" * 40


@pytest.fixture
def candidate(tmp_path, monkeypatch):
    source = {
        "repository": "infiquetra/voice-forge",
        "sha": SHA,
        "ref": "refs/tags/v0.3.0",
        "event": "push",
        "run_id": "123",
        "run_attempt": "1",
    }
    for key, value in source.items():
        monkeypatch.setenv(f"GITHUB_{'EVENT_NAME' if key == 'event' else key.upper()}", value)
    event = {"repository": {"full_name": source["repository"]}, "ref": source["ref"], "after": SHA}
    path = tmp_path / "event.json"
    path.write_text(json.dumps(event))
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(path))
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "output"))
    revisions = {"HEAD": SHA, source["ref"]: SHA, source["ref"] + "^{commit}": SHA}
    monkeypatch.setattr(release, "git_revision", revisions.__getitem__)
    return source, event, path, revisions


def metadata(project):
    return (
        f"Metadata-Version: 2.4\nName: {project['name']}\nVersion: {project['version']}\n"
        f"Requires-Python: {project['requires-python']}\n\n"
    ).encode()


def make_distributions(bundle, wheel_metadata=None, duplicate=False, sdist_metadata=None):
    project = release.project_metadata()
    stem = f"voice_forge_tts-{project['version']}"
    dist = bundle / "dist"
    dist.mkdir(parents=True, exist_ok=True)
    wheel = dist / f"{stem}-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(
            "voice_forge/__init__.py", (release.ROOT / "src/voice_forge/__init__.py").read_bytes()
        )
        archive.writestr(f"{stem}.dist-info/METADATA", wheel_metadata or metadata(project))
        if duplicate:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                archive.writestr("voice_forge/__init__.py", b"duplicate")
    with tarfile.open(dist / f"{stem}.tar.gz", "w:gz") as archive:
        for name, body in {
            "PKG-INFO": sdist_metadata or metadata(project),
            "pyproject.toml": (release.ROOT / "pyproject.toml").read_bytes(),
            "src/voice_forge/__init__.py": (
                release.ROOT / "src/voice_forge/__init__.py"
            ).read_bytes(),
        }.items():
            member = tarfile.TarInfo(f"{stem}/{name}")
            member.size = len(body)
            archive.addfile(member, io.BytesIO(body))
    return wheel


@pytest.fixture
def bundle(tmp_path, candidate):
    path = tmp_path / "bundle"
    wheel = make_distributions(path)
    digest = release.create_manifest(path)
    return path, wheel, digest


def rewrite_manifest(bundle, change):
    path = bundle / release.MANIFEST
    manifest = json.loads(path.read_text())
    change(manifest)
    path.write_text(json.dumps(manifest))
    return release.sha256(path)


def test_accepts_exact_source_bundle_and_destination(bundle):
    path, wheel, digest = bundle
    assert release.verify_bundle(path, digest, "42") == wheel
    release.publish_check(path, digest, "42", "success", "pypi")


@pytest.mark.parametrize("revision", ["HEAD", "refs/tags/v0.3.0^{commit}"])
def test_different_checkout_ref_or_push_object_rejected(candidate, revision):
    candidate[3][revision] = OTHER
    with pytest.raises(ValueError, match="SHA|object"):
        release.verify_source()


def test_annotated_tag_object_and_exact_commit_are_distinct(candidate):
    _, event, path, revisions = candidate
    revisions["refs/tags/v0.3.0"] = OTHER
    event["after"] = OTHER
    path.write_text(json.dumps(event))
    assert release.verify_source()["sha"] == SHA


def test_unrelated_push_object_rejected(candidate):
    _, event, path, _ = candidate
    event["after"] = OTHER
    path.write_text(json.dumps(event))
    with pytest.raises(ValueError, match="object"):
        release.verify_source()


def test_different_main_pass_cannot_qualify_tag(candidate):
    candidate[3]["refs/remotes/origin/main"] = SHA
    candidate[3]["refs/tags/v0.3.0^{commit}"] = OTHER
    with pytest.raises(ValueError, match="different SHA"):
        release.verify_source()


@pytest.mark.parametrize("change", ["ref", "repository", "deleted"])
def test_wrong_push_payload_rejected(candidate, change):
    _, event, path, _ = candidate
    event[change] = {"full_name": "other/repo"} if change == "repository" else True
    path.write_text(json.dumps(event))
    with pytest.raises(ValueError):
        release.verify_source()


@pytest.mark.parametrize(
    "event,ref", [("pull_request", "refs/pull/7/merge"), ("push", "refs/heads/main")]
)
def test_safe_ci_sources_are_accepted_without_publication(candidate, monkeypatch, event, ref):
    source, payload, path, revisions = candidate
    monkeypatch.setenv("GITHUB_EVENT_NAME", event)
    monkeypatch.setenv("GITHUB_REF", ref)
    source.update(event=event, ref=ref)
    payload.update(ref=ref, number=7, pull_request={"base": {"ref": "main"}})
    path.write_text(json.dumps(payload))
    revisions.update({"refs/remotes/origin/main": SHA, "refs/remotes/origin/main^{commit}": SHA})
    assert release.verify_source() == source
    with pytest.raises(ValueError):
        release.release_destination(source)


@pytest.mark.parametrize(
    "key,value",
    [("event", "workflow_run"), ("event", "pull_request_target"), ("ref", "refs/heads/other")],
)
def test_unsupported_sources_rejected(candidate, monkeypatch, key, value):
    monkeypatch.setenv(f"GITHUB_{'EVENT_NAME' if key == 'event' else key.upper()}", value)
    with pytest.raises(ValueError):
        release.verify_source()


@pytest.mark.parametrize(
    "field,value",
    [
        ("sha", OTHER),
        ("ref", "refs/heads/main"),
        ("repository", "other/repo"),
        ("event", "pull_request"),
        ("run_id", "122"),
        ("run_attempt", "2"),
    ],
)
def test_stale_or_different_source_manifest_rejected_even_if_digest_matches(bundle, field, value):
    path, _, _ = bundle
    digest = rewrite_manifest(path, lambda m: m["source"].update({field: value}))
    with pytest.raises(ValueError, match="source/ref/event/run/attempt"):
        release.verify_bundle(path, digest, "42")


def test_wrong_artifact_origin_rejected(bundle):
    path, _, _ = bundle
    digest = rewrite_manifest(path, lambda m: m.update(artifact_name="other-artifact"))
    with pytest.raises(ValueError, match="origin"):
        release.verify_bundle(path, digest, "42")


@pytest.mark.parametrize("artifact", ["", "0", "41,42", "42garbage"])
def test_no_ambiguous_or_missing_producer_id(bundle, artifact):
    path, _, digest = bundle
    with pytest.raises(ValueError, match="artifact ID"):
        release.verify_bundle(path, digest, artifact)


@pytest.mark.parametrize(
    "kind",
    ["missing", "extra", "duplicate", "directory", "symlink", "extra-bundle", "missing-manifest"],
)
def test_bad_distribution_inventory_rejected(bundle, kind):
    path, wheel, digest = bundle
    if kind == "missing":
        wheel.unlink()
    elif kind == "extra":
        (path / "dist" / "unexpected.txt").write_text("extra")
    elif kind == "duplicate":
        shutil.copyfile(wheel, wheel.with_name("extra-py3-none-any.whl"))
    elif kind == "directory":
        wheel.unlink()
        wheel.mkdir()
    elif kind == "symlink":
        original = wheel.read_bytes()
        wheel.unlink()
        target = path.parent / "original.whl"
        target.write_bytes(original)
        wheel.symlink_to(target)
    elif kind == "extra-bundle":
        (path / "extra").write_text("extra")
    else:
        (path / release.MANIFEST).unlink()
    with pytest.raises(ValueError):
        release.verify_bundle(path, digest, "42")


def test_replaced_wheel_and_companion_manifest_rejected(bundle):
    path, wheel, producer_digest = bundle
    with wheel.open("ab") as stream:
        stream.write(b"tampered")
    rewrite_manifest(
        path,
        lambda m: m["files"][0].update(sha256=release.sha256(wheel), size=wheel.stat().st_size),
    )
    with pytest.raises(ValueError, match="independent producer"):
        release.verify_bundle(path, producer_digest, "42")


def test_replaced_wheel_without_manifest_rejected(bundle):
    path, wheel, digest = bundle
    with wheel.open("ab") as stream:
        stream.write(b"tampered")
    with pytest.raises(ValueError, match="digest/size/inventory"):
        release.verify_bundle(path, digest, "42")


@pytest.mark.parametrize(
    "field,bad", [("Name", "wrong"), ("Version", "9.9.9"), ("Requires-Python", ">=3.13")]
)
def test_bad_wheel_metadata_rejected(candidate, tmp_path, field, bad):
    body = metadata(release.project_metadata()).decode()
    body = re.sub(rf"^{field}: .*", f"{field}: {bad}", body, flags=re.MULTILINE)
    path = tmp_path / "bad"
    make_distributions(path, body.encode())
    with pytest.raises(ValueError, match=field):
        release.create_manifest(path)


def test_duplicate_archive_members_rejected(candidate, tmp_path):
    path = tmp_path / "bad"
    make_distributions(path, duplicate=True)
    with pytest.raises(ValueError, match="Duplicate wheel"):
        release.create_manifest(path)


def test_duplicate_manifest_keys_rejected(bundle):
    path, _, _ = bundle
    manifest = path / release.MANIFEST
    manifest.write_text(manifest.read_text().replace('"schema": 1', '"schema": 1, "schema": 1'))
    with pytest.raises(ValueError, match="Duplicate JSON"):
        release.verify_bundle(path, release.sha256(manifest), "42")


@pytest.mark.parametrize("result", ["failure", "cancelled", "skipped", "", "neutral"])
def test_unsuccessful_qualification_cannot_reach_publication(bundle, result):
    path, _, digest = bundle
    reached = []
    with pytest.raises(ValueError, match="qualification"):
        release.publish_check(path, digest, "42", result, "pypi")
        reached.append("publisher")
    assert reached == []


@pytest.mark.parametrize(
    "suffix,destination",
    [
        ("", "pypi"),
        ("-rc.1", "testpypi"),
        ("-alpha.1", "testpypi"),
        ("-beta.1", "testpypi"),
        ("-RC.1", "testpypi"),
        ("rc1", "pypi"),
    ],
)
def test_existing_destination_routing(candidate, suffix, destination):
    source = dict(candidate[0], ref=f"refs/tags/v0.3.0{suffix}")
    assert release.release_destination(source) == destination


def test_wrong_destination_rejected_before_publisher(bundle):
    path, _, digest = bundle
    with pytest.raises(ValueError, match="destination"):
        release.publish_check(path, digest, "42", "success", "testpypi")


@pytest.mark.parametrize("origin", ["checkout", "external", "symlink"])
def test_import_and_metadata_origins_fail_closed(tmp_path, origin):
    prefix, checkout = tmp_path / "venv", tmp_path / "checkout"
    prefix.mkdir()
    checkout.mkdir()
    path = checkout / "voice_forge.py" if origin == "checkout" else tmp_path / "elsewhere.py"
    path.touch()
    if origin == "symlink":
        link = prefix / "voice_forge.py"
        link.symlink_to(path)
        path = link
    with pytest.raises(ValueError, match="origin"):
        release.check_origin(path, prefix, checkout)


@pytest.fixture
def installed(tmp_path, monkeypatch):
    prefix = tmp_path / "venv"
    site = prefix / "lib/site-packages"
    site.mkdir(parents=True)
    wheel = tmp_path / "wheel.whl"
    wheel.write_bytes(b"original wheel")
    direct = {"url": wheel.as_uri(), "archive_info": {"hashes": {"sha256": release.sha256(wheel)}}}
    distribution = SimpleNamespace(
        metadata={"Name": release.PROJECT},
        version="0.3.0",
        locate_file=lambda _: site,
        read_text=lambda _: json.dumps(direct),
        entry_points=[
            SimpleNamespace(name=n, value=v, group="console_scripts")
            for n, v in {
                "voice-forge": "voice_forge.cli:main",
                "voice-forge-backend-shim": "voice_forge.subprocess_shim:main",
                "voice-forge-secrets": "voice_forge.secrets.cli:main",
            }.items()
        ],
    )
    module = SimpleNamespace(__file__=str(site / "voice_forge/__init__.py"), __version__="0.3.0")
    monkeypatch.setattr(sys, "prefix", str(prefix))
    monkeypatch.setattr(sys, "path", [str(site)])
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(release.importlib.metadata, "distribution", lambda _: distribution)
    monkeypatch.setattr(release.importlib, "import_module", lambda _: module)
    return wheel, direct, distribution, module


def test_installed_wheel_origin_metadata_and_runtime_pass(installed):
    release.check_installed(installed[0], "0.3.0", ROOT)


@pytest.mark.parametrize(
    "corruption", ["url", "hash", "metadata", "runtime", "origin", "entrypoints"]
)
def test_bad_installed_wheel_rejected(installed, corruption):
    wheel, direct, distribution, module = installed
    if corruption == "url":
        direct["url"] = "file:///other.whl"
    elif corruption == "hash":
        direct["archive_info"]["hashes"]["sha256"] = "0" * 64
    elif corruption == "metadata":
        distribution.version = "9.9.9"
    elif corruption == "runtime":
        module.__version__ = "9.9.9"
    elif corruption == "entrypoints":
        distribution.entry_points = []
    else:
        module.__file__ = str(ROOT / "src/voice_forge/__init__.py")
    with pytest.raises(ValueError):
        release.check_installed(wheel, "0.3.0", ROOT)


def workflow(name):
    # BaseLoader preserves Actions' `on` key (YAML 1.1 bool resolution does not).
    return yaml.load((ROOT / ".github/workflows" / name).read_text(), Loader=yaml.BaseLoader)


def expression(value, source):
    """Evaluate the small expression subset actually used by publisher job guards."""
    value = value.removeprefix("${{").removesuffix("}}").strip()
    for name, resolved in {
        "event_name": source["event"],
        "ref_name": source["ref"].removeprefix("refs/tags/"),
        "ref": source["ref"],
    }.items():
        value = value.replace(f"github.{name}", repr(resolved))
    value = value.replace("&&", " and ").replace("||", " or ")
    value = re.sub(r"!(?!=)", "not ", value)
    return eval(
        value,
        {"__builtins__": {}},
        {
            "contains": lambda text, part: part.lower() in text.lower(),
            "startsWith": lambda text, part: text.lower().startswith(part.lower()),
        },
    )


def outcomes(name, source, failures=(), prefix=""):
    """Expand the real reusable DAG and apply implicit success() dependency gates."""
    results = {}
    jobs = workflow(name)["jobs"]
    while len(results) < len(jobs):
        for key, job in jobs.items():
            if key in results:
                continue
            needs = job.get("needs", [])
            needs = [needs] if isinstance(needs, str) else needs
            if not all(n in results for n in needs):
                continue
            if any(results[n] != "success" for n in needs) or not expression(
                job.get("if", "True"), source
            ):
                results[key] = "skipped"
            elif prefix + key in failures:
                results[key] = failures[prefix + key]
            elif "uses" in job:
                called = job["uses"].split("/")[-1]
                children = outcomes(called, source, failures, prefix + key + "/")
                results[key] = (
                    "success" if all(v == "success" for v in children.values()) else "failure"
                )
            else:
                results[key] = "success"
    return results


@pytest.mark.parametrize(
    "stage", ["ci/lint-and-test", "ci/qualify/build", "ci/qualify/smoke", "ci/qualify", "ci"]
)
@pytest.mark.parametrize("status", ["failure", "cancelled", "skipped"])
def test_actual_reusable_graph_blocks_publish_for_every_unsuccessful_gate(candidate, stage, status):
    result = outcomes("publish.yml", candidate[0], {stage: status})
    assert result["publish-pypi"] == result["publish-testpypi"] == "skipped"


@pytest.mark.parametrize(
    "ref,event,expected",
    [
        ("refs/tags/v0.3.0", "push", "pypi"),
        ("refs/tags/v0.3.0-rc.1", "push", "testpypi"),
        ("refs/tags/v0.3.0-alpha.1", "push", "testpypi"),
        ("refs/tags/v0.3.0-beta.1", "push", "testpypi"),
        ("refs/heads/main", "push", None),
        ("refs/pull/1/merge", "pull_request", None),
        ("refs/tags/v0.3.0", "workflow_run", None),
    ],
)
def test_actual_publisher_conditions_and_reusable_graph(candidate, ref, event, expected):
    source = dict(candidate[0], ref=ref, event=event)
    result = outcomes("publish.yml", source)
    reached = [
        k for k, status in result.items() if k.startswith("publish-") and status == "success"
    ]
    assert reached == ([f"publish-{expected}"] if expected else [])


def test_safe_pr_path_has_no_publish_or_oidc_and_build_is_after_full_matrix():
    ci, qualifier, publisher = (
        workflow(n) for n in ("ci.yml", "release-qualification.yml", "publish.yml")
    )
    assert set(ci["on"]) == {"push", "pull_request", "workflow_call"}
    assert ci["jobs"]["qualify"]["needs"] == "lint-and-test"
    assert ci["jobs"]["lint-and-test"]["strategy"]["matrix"]["python-version"] == ["3.11", "3.12"]
    assert qualifier["jobs"]["smoke"]["needs"] == "build"
    for document in (ci, qualifier):
        assert document["permissions"] == {"contents": "read"}
        for job in document["jobs"].values():
            assert "id-token" not in job.get("permissions", {})
            assert not any("pypi-publish@" in step.get("uses", "") for step in job.get("steps", []))
    for destination in ("pypi", "testpypi"):
        job = publisher["jobs"][f"publish-{destination}"]
        assert job["needs"] == "ci"
        assert job["environment"]["name"] == destination
        assert job["permissions"] == {"contents": "read", "id-token": "write"}
        assert "publish-check" in job["steps"][-2]["run"]
        assert "pypi-publish@" in job["steps"][-1]["uses"]
    assert publisher["concurrency"]["cancel-in-progress"] == "false"


def test_download_selection_is_only_the_same_run_producer_id_and_no_cached_release_environments():
    for name in ("release-qualification.yml", "publish.yml"):
        document = workflow(name)
        assert (
            not document["on"]["workflow_call"].get("inputs")
            if "workflow_call" in document["on"]
            else True
        )
        for job in document["jobs"].values():
            for step in job.get("steps", []):
                action = step.get("uses", "")
                assert "cache" not in action
                if "download-artifact@" in action:
                    inputs = step["with"]
                    assert set(inputs) == {"artifact-ids", "merge-multiple", "path"}
                    assert inputs["artifact-ids"].startswith("${{ needs.")
                    assert inputs["artifact-ids"].endswith(".outputs.artifact-id }}")
                if action and not action.startswith("./"):
                    assert re.fullmatch(r"[0-9a-f]{40}", action.split("@")[1])


def test_cli_rejects_unsuccessful_qualification_without_publisher(bundle):
    path, _, digest = bundle
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/release_artifacts.py"),
            "publish-check",
            "--bundle",
            str(path),
            "--expected-manifest",
            digest,
            "--artifact-id",
            "42",
            "--qualification",
            "failure",
            "--destination",
            "pypi",
        ],
        text=True,
        capture_output=True,
    )
    assert result.returncode != 0
    assert "qualification did not succeed" in result.stderr


@pytest.mark.parametrize("change", ["pr-ref", "pr-base", "pr-sha"])
def test_pr_source_mismatch_rejected(candidate, monkeypatch, change):
    _, event, path, revisions = candidate
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    monkeypatch.setenv("GITHUB_REF", "refs/pull/7/merge")
    event.update(
        number=8 if change == "pr-ref" else 7,
        pull_request={"base": {"ref": "other" if change == "pr-base" else "main"}},
    )
    if change == "pr-sha":
        revisions["HEAD"] = OTHER
    path.write_text(json.dumps(event))
    with pytest.raises(ValueError):
        release.verify_source()


@pytest.mark.parametrize("digest", ["", "0" * 63, "$(touch SHOULD_NOT_EXIST)", "a" * 64])
def test_untrusted_expected_digest_is_data_and_fails_closed(bundle, digest):
    path, _, _ = bundle
    with pytest.raises(ValueError):
        release.verify_bundle(path, digest, "42")
    assert not (ROOT / "SHOULD_NOT_EXIST").exists()


def test_duplicate_metadata_fields_rejected(candidate, tmp_path):
    path = tmp_path / "bad"
    body = metadata(release.project_metadata()).replace(b"\n\n", b"\nName: voice-forge-tts\n\n")
    make_distributions(path, body)
    with pytest.raises(ValueError, match="Name"):
        release.create_manifest(path)


def test_missing_import_package_rejected(candidate, tmp_path):
    path = tmp_path / "bad"
    wheel = make_distributions(path)
    project = release.project_metadata()
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(
            f"voice_forge_tts-{project['version']}.dist-info/METADATA", metadata(project)
        )
    with pytest.raises(ValueError, match="Missing import"):
        release.create_manifest(path)


def test_tag_ci_cannot_restore_or_save_caches(candidate):
    ci = workflow("ci.yml")
    tag = candidate[0]
    pr = dict(tag, event="pull_request", ref="refs/pull/7/merge")
    main = dict(tag, ref="refs/heads/main")
    steps = ci["jobs"]["lint-and-test"]["steps"]
    for step in steps:
        if "actions/cache/restore@" in step.get("uses", ""):
            # The matrix clause is fixed to the supported 3.12 hook owner.
            condition = step["if"].replace("matrix.python-version", "'3.12'")
            assert not expression(condition, tag)
            assert expression(condition, pr)
            assert expression(condition, main)
        if "actions/cache/save@" in step.get("uses", ""):
            condition = step["if"].replace("success()", "True")
            condition = condition.replace("matrix.python-version", "'3.12'")
            condition = re.sub(
                r"steps\.(?:downloads|hooks)\.outputs\.cache-hit", "'false'", condition
            )
            assert not expression(condition, tag)
            assert not expression(condition, pr)
            assert expression(condition, main)


def set_fixture_tag(candidate, monkeypatch, tag):
    """Set synthetic event/ref lookups; never creates a Git tag."""
    source, event, path, revisions = candidate
    source["ref"] = f"refs/tags/{tag}"
    event["ref"] = source["ref"]
    path.write_text(json.dumps(event))
    monkeypatch.setenv("GITHUB_REF", source["ref"])
    revisions.update({source["ref"]: SHA, source["ref"] + "^{commit}": SHA})


def test_wrong_tag_version_cannot_create_manifest(candidate, monkeypatch, tmp_path):
    path = tmp_path / "wrong-version"
    make_distributions(path)
    set_fixture_tag(candidate, monkeypatch, "v9.9.9")
    with pytest.raises(ValueError, match="tag version differs from project version"):
        release.create_manifest(path)
    assert not (path / release.MANIFEST).exists()


def test_wrong_tag_version_cannot_publish_matching_project_distributions(
    bundle, candidate, monkeypatch
):
    path, _, _ = bundle
    set_fixture_tag(candidate, monkeypatch, "v9.9.9")
    # Model the parent defect's producer binding an otherwise valid 0.3.0 bundle
    # to this mismatched tag, including an independent matching manifest digest.
    digest = rewrite_manifest(path, lambda m: m.update(source=candidate[0]))
    with pytest.raises(ValueError, match="tag version differs from project version"):
        release.publish_check(path, digest, "42", "success", "pypi")


def fixture_project(tmp_path, monkeypatch, version):
    """Disposable source/metadata fixtures, not built release or hosted evidence."""
    root = tmp_path / "source-fixture"
    (root / "src/voice_forge").mkdir(parents=True)
    project = (
        (ROOT / "pyproject.toml")
        .read_text()
        .replace('version = "0.3.0"', f'version = "{version}"', 1)
    )
    (root / "pyproject.toml").write_text(project)
    (root / "src/voice_forge/__init__.py").write_text(f'__version__ = "{version}"\n')
    monkeypatch.setattr(release, "ROOT", root)
    return root


@pytest.mark.parametrize(
    "project_version,tag,canonical,destination",
    [
        ("0.3.0", "v0.3.0", "0.3.0", "pypi"),
        ("00.03.00", "v0.3.0", "0.3.0", "pypi"),
        ("0.3.0", "v00.03.00", "0.3.0", "pypi"),
        ("0.3.0-rc.01", "v0.3.0-RC.1", "0.3.0rc1", "testpypi"),
        ("0.3.0RC1", "v0.3.0-rc.01", "0.3.0rc1", "testpypi"),
        ("0.3.0rc1", "v0.3.0-rc.1", "0.3.0rc1", "testpypi"),
        ("0.3.0-alpha.01", "v0.3.0-AlPhA.1", "0.3.0a1", "testpypi"),
        ("0.3.0a1", "v0.3.0-alpha.01", "0.3.0a1", "testpypi"),
        ("0.3.0Beta01", "v0.3.0-BETA.1", "0.3.0b1", "testpypi"),
        ("0.3.0b1", "v0.3.0-beta.01", "0.3.0b1", "testpypi"),
        ("0.3.0rc1", "v0.3.0rc1", "0.3.0rc1", "pypi"),
        ("0.3.0a1", "v0.3.0A1", "0.3.0a1", "pypi"),
        ("0.3.0b1", "v0.3.0b1", "0.3.0b1", "pypi"),
    ],
)
def test_normalized_tag_project_and_canonical_distributions_pass_real_admission(
    candidate, monkeypatch, tmp_path, project_version, tag, canonical, destination
):
    fixture_project(tmp_path, monkeypatch, project_version)
    set_fixture_tag(candidate, monkeypatch, tag)
    assert release.project_metadata()["version"] == canonical
    path = tmp_path / "normalized-bundle"
    wheel = make_distributions(path)
    assert canonical in wheel.name
    digest = release.create_manifest(path)
    assert release.verify_bundle(path, digest, "42") == wheel
    release.publish_check(path, digest, "42", "success", destination)
    graph = outcomes("publish.yml", candidate[0])
    assert graph[f"publish-{destination}"] == "success"
    assert graph[f"publish-{'pypi' if destination == 'testpypi' else 'testpypi'}"] == "skipped"


@pytest.mark.parametrize(
    "project_version,tag",
    [
        ("0.3.0rc1", "v0.3.0-rc.2"),
        ("0.3.0rc1", "v0.3.0-beta.1"),
        ("0.3.0a1", "v0.3.0-beta.1"),
        ("0.3.0b1", "v0.3.0-alpha.1"),
        ("0.3.0b1", "v0.3.0-beta.2"),
        ("0.3.0rc1", "v0.3.0"),
        ("0.3.0", "v0.3.0-rc.1"),
    ],
)
def test_prerelease_flavor_number_or_final_mismatch_blocks_create_and_publish(
    candidate, monkeypatch, tmp_path, project_version, tag
):
    fixture_project(tmp_path, monkeypatch, project_version)
    set_fixture_tag(candidate, monkeypatch, f"v{project_version}")
    path = tmp_path / "prerelease-bundle"
    make_distributions(path)
    release.create_manifest(path)
    set_fixture_tag(candidate, monkeypatch, tag)
    digest = rewrite_manifest(path, lambda m: m.update(source=candidate[0]))
    for admit in (
        lambda: release.create_manifest(path),
        lambda: release.publish_check(
            path, digest, "42", "success", release.release_destination(candidate[0])
        ),
    ):
        with pytest.raises(ValueError, match="tag version differs from project version"):
            admit()


@pytest.mark.parametrize(
    "version",
    [
        "",
        "0.3",
        "0.3.0.0",
        "0!0.3.0",
        "1!0.3.0",
        "0.3.0+local",
        "0.3.0.post1",
        "0.3.0.dev1",
        "0.3.0rc1.post1",
        "0.3.0rc",
        "0.3.0-preview1",
        "0.3.0c1",
        "0.3.0-r1",
        "0.3.0-rc..1",
        "0.3.0-rc.-1",
        "0.3.0--rc.1",
        "0.3.0rc1junk",
        "0.3.0-rc.١",
        "０.3.0",
        " 0.3.0",
        "0.3.0\n",
        "v0.3.0",
    ],
)
def test_malformed_or_unsupported_versions_rejected_by_source_gate(candidate, monkeypatch, version):
    set_fixture_tag(candidate, monkeypatch, f"v{version}")
    with pytest.raises(ValueError, match="Unsupported release version|Not a release tag"):
        release.verify_source()


@pytest.mark.parametrize("version", ["0.3.0.post1", "0.3.0rc", "0.3.0+local", "0.3"])
def test_unsupported_project_version_fails_closed(tmp_path, monkeypatch, version):
    fixture_project(tmp_path, monkeypatch, version)
    with pytest.raises(ValueError, match="Unsupported release version"):
        release.project_metadata()


def test_supported_normalizations_agree_with_declared_packaging_tool():
    # Packaging is already in the CI dev/build lock; production uses stdlib only.
    for core in ("0.3.0", "00.03.00", "1.20.300"):
        assert release.normalized_version(core) == str(Version(core))
        for phase in ("a", "alpha", "b", "beta", "rc"):
            for spelling in (phase, phase.upper(), phase.title()):
                for before in ("", "-", "_", "."):
                    for after in ("", "-", "_", "."):
                        for number in ("0", "1", "001"):
                            value = f"{core}{before}{spelling}{after}{number}"
                            assert release.normalized_version(value) == str(Version(value))


@pytest.mark.parametrize("target", ["wheel", "sdist"])
def test_noncanonical_equivalent_distribution_metadata_is_compared_consistently(
    candidate, monkeypatch, tmp_path, target
):
    fixture_project(tmp_path, monkeypatch, "0.3.0rc1")
    set_fixture_tag(candidate, monkeypatch, "v0.3.0-RC.01")
    project = dict(release.project_metadata(), version="00.03.00-RC.001")
    path = tmp_path / "equivalent-metadata"
    make_distributions(path, **{f"{target}_metadata": metadata(project)})
    digest = release.create_manifest(path)
    release.publish_check(path, digest, "42", "success", "testpypi")


@pytest.mark.parametrize("target", ["wheel", "sdist"])
@pytest.mark.parametrize("wrong", ["9.9.9", "0.3.0rc1", "0.3.0+local"])
def test_source_and_distribution_version_disagreement_rejected(candidate, tmp_path, target, wrong):
    project = dict(release.project_metadata(), version=wrong)
    path = tmp_path / "wrong-metadata"
    make_distributions(path, **{f"{target}_metadata": metadata(project)})
    with pytest.raises(ValueError, match="Version|Unsupported release version"):
        release.create_manifest(path)


def test_changed_source_version_cannot_reuse_an_admitted_bundle(
    bundle, candidate, tmp_path, monkeypatch
):
    path, _, digest = bundle
    fixture_project(tmp_path, monkeypatch, "0.3.1")
    with pytest.raises(ValueError, match="tag version differs from project version"):
        release.publish_check(path, digest, "42", "success", "pypi")


def test_installed_runtime_and_metadata_versions_normalize_consistently(installed):
    wheel, _, distribution, module = installed
    distribution.version = "0.3.0rc1"
    module.__version__ = "00.03.00-RC.001"
    release.check_installed(wheel, "0.3.0-rc.01", ROOT)
    module.__version__ = "0.3.0rc2"
    with pytest.raises(ValueError, match="Runtime version"):
        release.check_installed(wheel, "0.3.0-rc.01", ROOT)
