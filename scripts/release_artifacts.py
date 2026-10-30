"""Fail-closed source, distribution and installed-wheel admission for release CI.

Expected manifest digests and artifact IDs come from producer job outputs, never
from downloaded files or caller inputs. This module has only stdlib dependencies.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.metadata
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import venv
import zipfile
from email.parser import BytesParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECT = "voice-forge-tts"
MANIFEST = "manifest.json"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def normalized_version(value: str) -> str:
    """Normalize the documented three-component final/a/b/rc release subset.

    PEP 440 permits case folding, integer normalization, alpha/beta aliases and
    optional single separators. Other forms need an explicit release-contract
    change. Keep source admission usable with system Python's stdlib alone.
    """
    match = (
        re.fullmatch(
            r"(?P<release>[0-9]+\.[0-9]+\.[0-9]+)"
            r"(?:[-_.]?(?P<phase>alpha|beta|rc|a|b)[-_.]?(?P<number>[0-9]+))?",
            value,
            flags=re.IGNORECASE,
        )
        if isinstance(value, str)
        else None
    )
    if match is None:
        raise ValueError("Unsupported release version; see docs/RELEASING.md")
    version = ".".join(str(int(part)) for part in match["release"].split("."))
    if match["phase"] is not None:
        phase = match["phase"].lower()
        phase = {"alpha": "a", "beta": "b"}.get(phase, phase)
        version += phase + str(int(match["number"]))
    return version


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def unique_object(pairs: list[tuple[str, object]]) -> dict:
    result: dict = {}
    for key, value in pairs:
        require(key not in result, f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def read_json(path: Path) -> dict:
    value = json.loads(path.read_bytes(), object_pairs_hook=unique_object)
    require(isinstance(value, dict), "Expected a JSON object")
    return value


def git_revision(ref: str) -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "--verify", ref], cwd=ROOT, text=True
    ).strip()


def identity() -> dict[str, str]:
    source = {
        key: os.environ[env]
        for key, env in {
            "repository": "GITHUB_REPOSITORY",
            "sha": "GITHUB_SHA",
            "ref": "GITHUB_REF",
            "event": "GITHUB_EVENT_NAME",
            "run_id": "GITHUB_RUN_ID",
            "run_attempt": "GITHUB_RUN_ATTEMPT",
        }.items()
    }
    require(bool(re.fullmatch(r"[0-9a-f]{40}", source["sha"])), "Invalid caller SHA")
    for key in ("run_id", "run_attempt"):
        require(bool(re.fullmatch(r"[1-9][0-9]*", source[key])), f"Invalid {key}")
    require(source["repository"] == "infiquetra/voice-forge", "Unexpected repository")
    return source


def release_destination(source: dict[str, str]) -> str:
    require(source["event"] == "push", "Publication requires a tag push")
    require(
        bool(re.fullmatch(r"refs/tags/v[^/]*\.[^/]*\.[^/]*", source["ref"])), "Not a release tag"
    )
    # GitHub expression contains() is case-insensitive; preserve existing routing.
    tag = source["ref"].lower()
    return "testpypi" if any(marker in tag for marker in ("-rc.", "-alpha.", "-beta.")) else "pypi"


def verify_source() -> dict[str, str]:
    source = identity()
    event = read_json(Path(os.environ["GITHUB_EVENT_PATH"]))
    require(event["repository"]["full_name"] == source["repository"], "Event repository mismatch")
    require(git_revision("HEAD") == source["sha"], "Checkout does not match the caller SHA")
    if source["event"] == "push":
        require(
            event["ref"] == source["ref"] and not event.get("deleted", False), "Push ref mismatch"
        )
        if source["ref"] == "refs/heads/main":
            ref = "refs/remotes/origin/main"
        else:
            release_destination(source)
            require(
                normalized_version(source["ref"].removeprefix("refs/tags/v"))
                == project_metadata()["version"],
                "Release tag version differs from project version",
            )
            ref = source["ref"]
        require(
            git_revision(f"{ref}^{{commit}}") == source["sha"], "Ref resolves to a different SHA"
        )
        # Annotated tag push payloads can identify the tag object, not its commit.
        require(event["after"] in {git_revision(ref), source["sha"]}, "Push object mismatch")
    elif source["event"] == "pull_request":
        require(source["ref"] == f"refs/pull/{event['number']}/merge", "PR ref mismatch")
        require(event["pull_request"]["base"]["ref"] == "main", "Unexpected PR base")
    else:
        raise ValueError("Unsupported caller event")
    print("Verified caller source: " + json.dumps(source, sort_keys=True))
    return source


def project_metadata() -> dict[str, str]:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    require(project["name"] == PROJECT, "Unexpected project name")
    return {
        "name": project["name"],
        "version": normalized_version(project["version"]),
        "requires-python": project["requires-python"],
    }


def check_metadata(data: bytes, project: dict[str, str]) -> None:
    metadata = BytesParser().parsebytes(data)
    for field, key in (
        ("Name", "name"),
        ("Requires-Python", "requires-python"),
    ):
        require(metadata.get_all(field) == [project[key]], f"Bad distribution metadata: {field}")
    versions = metadata.get_all("Version", [])
    require(len(versions) == 1, "Bad distribution metadata: Version")
    require(
        normalized_version(versions[0]) == normalized_version(project["version"]),
        "Bad distribution metadata: Version",
    )


def distribution_files(bundle: Path, project: dict[str, str]) -> list[Path]:
    dist = bundle / "dist"
    require(dist.is_dir() and not dist.is_symlink(), "Missing regular dist directory")
    stem = f"voice_forge_tts-{project['version']}"
    expected_names = {f"{stem}-py3-none-any.whl", f"{stem}.tar.gz"}
    files = sorted(dist.iterdir())
    require(
        {p.name for p in files} == expected_names,
        "Expected exactly one project wheel and one sdist",
    )
    require(all(p.is_file() and not p.is_symlink() for p in files), "Non-regular distribution")
    wheel = next(p for p in files if p.suffix == ".whl")
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        require(len(names) == len(set(names)), "Duplicate wheel members")
        metadata_name = f"{stem}.dist-info/METADATA"
        require(
            [n for n in names if n.endswith(".dist-info/METADATA")] == [metadata_name],
            "Bad wheel metadata path",
        )
        require("voice_forge/__init__.py" in names, "Missing import package")
        check_metadata(archive.read(metadata_name), project)
    sdist = next(p for p in files if p.name.endswith(".tar.gz"))
    with tarfile.open(sdist, "r:gz") as archive:
        names = archive.getnames()
        require(len(names) == len(set(names)), "Duplicate sdist members")
        metadata_name = f"{stem}/PKG-INFO"
        require(
            [n for n in names if n.endswith("/PKG-INFO")] == [metadata_name],
            "Bad sdist metadata path",
        )
        for name, expected in (
            (metadata_name, None),
            (f"{stem}/pyproject.toml", (ROOT / "pyproject.toml").read_bytes()),
            (
                f"{stem}/src/voice_forge/__init__.py",
                (ROOT / "src/voice_forge/__init__.py").read_bytes(),
            ),
        ):
            member = archive.getmember(name)
            require(member.isfile(), "Non-regular sdist metadata/source")
            stream = archive.extractfile(member)
            if stream is None:
                raise ValueError("Missing sdist source")
            data = stream.read()
            if expected is None:
                check_metadata(data, project)
            else:
                require(data == expected, "Sdist source mismatch")
    return files


def artifact_name(source: dict[str, str]) -> str:
    return f"release-dist-{source['run_id']}-{source['run_attempt']}"


def create_manifest(bundle: Path) -> str:
    source = verify_source()
    project = project_metadata()
    files = distribution_files(bundle, project)
    require({p.name for p in bundle.iterdir()} == {"dist"}, "Unexpected producer bundle contents")
    manifest = {
        "schema": 1,
        "source": source,
        "artifact_name": artifact_name(source),
        "project": project,
        "files": [{"name": p.name, "sha256": sha256(p), "size": p.stat().st_size} for p in files],
    }
    path = bundle / MANIFEST
    path.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n")
    digest = sha256(path)
    with Path(os.environ["GITHUB_OUTPUT"]).open("a") as output:
        output.write(f"manifest-sha256={digest}\n")
    print(f"Producer manifest SHA-256: {digest}\n" + path.read_text())
    return digest


def verify_bundle(bundle: Path, expected_manifest: str, artifact_id: str) -> Path:
    source = verify_source()
    require(
        bool(re.fullmatch(r"[1-9][0-9]*", artifact_id)), "Missing or ambiguous producer artifact ID"
    )
    require(
        bool(re.fullmatch(r"[0-9a-f]{64}", expected_manifest)), "Missing producer manifest digest"
    )
    require(not bundle.is_symlink(), "Symlink bundle")
    require({p.name for p in bundle.iterdir()} == {"dist", MANIFEST}, "Unexpected bundle contents")
    path = bundle / MANIFEST
    require(path.is_file() and not path.is_symlink(), "Missing regular manifest")
    require(sha256(path) == expected_manifest, "Manifest differs from independent producer output")
    manifest = read_json(path)
    project = project_metadata()
    require(manifest.get("schema") == 1, "Unsupported manifest schema")
    require(manifest.get("source") == source, "Artifact source/ref/event/run/attempt mismatch")
    require(manifest.get("artifact_name") == artifact_name(source), "Artifact origin mismatch")
    require(manifest.get("project") == project, "Project metadata differs from source")
    files = distribution_files(bundle, project)
    actual = [{"name": p.name, "sha256": sha256(p), "size": p.stat().st_size} for p in files]
    require(manifest.get("files") == actual, "Distribution digest/size/inventory mismatch")
    print(f"Verified artifact ID {artifact_id}; manifest SHA-256 {expected_manifest}")
    print(json.dumps(actual, sort_keys=True))
    return next(p for p in files if p.suffix == ".whl")


def publish_check(
    bundle: Path, expected_manifest: str, artifact_id: str, qualification: str, destination: str
) -> None:
    require(qualification == "success", "Full CI/build/smoke qualification did not succeed")
    require(release_destination(identity()) == destination, "Wrong publication destination")
    verify_bundle(bundle, expected_manifest, artifact_id)


def check_origin(origin: Path, prefix: Path, checkout: Path) -> None:
    origin, prefix, checkout = origin.resolve(), prefix.resolve(), checkout.resolve()
    require(
        origin.is_relative_to(prefix) and not origin.is_relative_to(checkout),
        "Import/metadata origin outside fresh environment or inside checkout",
    )


def check_installed(wheel: Path, version: str, checkout: Path) -> None:
    prefix = Path(sys.prefix).resolve()
    require(sys.prefix != sys.base_prefix, "Smoke requires a fresh virtual environment")
    require(not prefix.is_relative_to(checkout.resolve()), "Smoke environment is inside checkout")
    require(
        not Path.cwd().resolve().is_relative_to(checkout.resolve()),
        "Smoke working directory is inside checkout",
    )
    require(
        not any(Path(p).resolve().is_relative_to(checkout.resolve()) for p in sys.path),
        "Checkout is on import path",
    )
    distribution = importlib.metadata.distribution(PROJECT)
    require(
        distribution.metadata["Name"] == PROJECT
        and normalized_version(distribution.version) == normalized_version(version),
        "Installed metadata mismatch",
    )
    check_origin(Path(str(distribution.locate_file(""))), prefix, checkout)
    direct = json.loads(distribution.read_text("direct_url.json") or "{}")
    require(direct.get("url") == wheel.resolve().as_uri(), "Installed wheel URL mismatch")
    require(
        direct.get("archive_info", {}).get("hashes", {}).get("sha256") == sha256(wheel),
        "Installed wheel digest mismatch",
    )
    entrypoints = {
        e.name: e.value for e in distribution.entry_points if e.group == "console_scripts"
    }
    require(
        entrypoints
        == {
            "voice-forge": "voice_forge.cli:main",
            "voice-forge-backend-shim": "voice_forge.subprocess_shim:main",
            "voice-forge-secrets": "voice_forge.secrets.cli:main",
        },
        "Installed entry points mismatch",
    )
    origins = {}
    for name in ("voice_forge", "voice_forge.config", "voice_forge.registry", "voice_forge.cli"):
        module = importlib.import_module(name)
        origin = Path(module.__file__ or "").resolve()
        check_origin(origin, prefix, checkout)
        origins[name] = str(origin)
        if name == "voice_forge":
            require(
                normalized_version(module.__version__) == normalized_version(version),
                "Runtime version differs from wheel metadata",
            )
    print(
        json.dumps(
            {"version": version, "wheel_sha256": sha256(wheel), "origins": origins}, sort_keys=True
        )
    )


def smoke(
    bundle: Path, expected_manifest: str, artifact_id: str, wheelhouse: Path | None = None
) -> None:
    wheel = verify_bundle(bundle, expected_manifest, artifact_id).resolve()
    version = project_metadata()["version"]
    with tempfile.TemporaryDirectory(prefix="voice-forge-smoke-") as temporary:
        work = Path(temporary).resolve()
        require(not work.is_relative_to(ROOT), "Smoke temporary directory is inside checkout")
        environment = work / "venv"
        venv.EnvBuilder(with_pip=True).create(environment)
        python = str(environment / "bin/python")
        command = [
            python,
            "-I",
            "-m",
            "pip",
            "--isolated",
            "install",
            "--no-cache-dir",
            "--only-binary=:all:",
        ]
        if wheelhouse is not None:
            command.extend(["--no-index", "--find-links", str(wheelhouse.resolve())])
        subprocess.run([*command, str(wheel)], cwd=work, check=True)
        subprocess.run([python, "-I", "-m", "pip", "--isolated", "check"], cwd=work, check=True)
        subprocess.run(
            [
                python,
                "-I",
                str(Path(__file__).resolve()),
                "installed",
                "--wheel",
                str(wheel),
                "--version",
                version,
                "--checkout",
                str(ROOT),
            ],
            cwd=work,
            check=True,
        )
    # The installer/import probe must leave the producer bytes unchanged.
    verify_bundle(bundle, expected_manifest, artifact_id)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("source")
    for command in ("create", "verify", "smoke", "publish-check"):
        sub = commands.add_parser(command)
        sub.add_argument("--bundle", type=Path, required=True)
        if command != "create":
            sub.add_argument("--expected-manifest", required=True)
            sub.add_argument("--artifact-id", required=True)
        if command == "smoke":
            sub.add_argument("--wheelhouse", type=Path)
        if command == "publish-check":
            sub.add_argument("--qualification", required=True)
            sub.add_argument("--destination", choices=("pypi", "testpypi"), required=True)
    installed = commands.add_parser("installed")
    installed.add_argument("--wheel", type=Path, required=True)
    installed.add_argument("--version", required=True)
    installed.add_argument("--checkout", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "source":
        verify_source()
    elif args.command == "create":
        create_manifest(args.bundle)
    elif args.command == "installed":
        check_installed(args.wheel, args.version, args.checkout)
    elif args.command == "verify":
        verify_bundle(args.bundle, args.expected_manifest, args.artifact_id)
    elif args.command == "smoke":
        smoke(args.bundle, args.expected_manifest, args.artifact_id, args.wheelhouse)
    else:
        publish_check(
            args.bundle,
            args.expected_manifest,
            args.artifact_id,
            args.qualification,
            args.destination,
        )


if __name__ == "__main__":
    main()
