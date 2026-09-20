import importlib.util
import json
import shutil
import subprocess
from pathlib import Path
from types import ModuleType

import pytest

REPOSITORY_ROOT = Path(__file__).parents[2]


def _module(name: str, path: Path) -> ModuleType:
    specification = importlib.util.spec_from_file_location(name, path)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


HARNESS = _module("m3_harness", REPOSITORY_ROOT / "scripts" / "run_m3_pilot_harness.py")
VERIFIER = _module(
    "m3_verifier", REPOSITORY_ROOT / "scripts" / "verify_m3_evidence_bundle.py"
)


@pytest.fixture
def source_checkout(tmp_path: Path) -> Path:
    root = tmp_path / "source"
    root.mkdir()
    (root / "inventory").mkdir()
    (root / "profiles").mkdir()
    (root / "inventory" / "device.yaml").write_text("synthetic: true\n")
    (root / "profiles" / "profile.yaml").write_text("synthetic: true\n")
    (root / "uv.lock").write_text("version = 1\n")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.invalid"],
        cwd=root,
        check=True,
    )
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "fixture"], cwd=root, check=True)
    return root


def _write_canonical(path: Path, value: object) -> None:
    path.write_bytes(VERIFIER._canonical(value))


def _reseal(bundle: Path) -> None:
    digests = {
        "schema": VERIFIER.SCHEMA,
        "files": {
            name: VERIFIER._sha256((bundle / name).read_bytes())
            for name in ("manifest.json", "sequence.json")
        },
    }
    digest_bytes = VERIFIER._canonical(digests)
    (bundle / "digests.json").write_bytes(digest_bytes)
    (bundle / "bundle.sha256").write_text(
        VERIFIER._sha256(digest_bytes) + "\n", encoding="ascii"
    )


def test_dry_run_is_byte_deterministic_and_independently_valid(
    source_checkout: Path,
) -> None:
    first = source_checkout / "first"
    second = source_checkout / "second"

    first_digest = HARNESS.generate_bundle(source_checkout, first)
    second_digest = HARNESS.generate_bundle(source_checkout, second)

    assert first_digest == second_digest
    assert {path.name: path.read_bytes() for path in first.iterdir()} == {
        path.name: path.read_bytes() for path in second.iterdir()
    }
    assert VERIFIER.verify_bundle(first, source_checkout) == first_digest
    expected = json.loads(
        (
            REPOSITORY_ROOT / "tests/fixtures/pilot-harness/core-sequence.json"
        ).read_bytes()
    )
    assert (
        json.loads((first / "sequence.json").read_bytes())["scenarios"]
        == (expected["scenarios"])
    )
    manifest = json.loads((first / "manifest.json").read_bytes())
    assert manifest["safety"]["device_contact"] is False
    assert manifest["safety"]["secret_resolution"] is False
    assert manifest["safety"]["skin_025_owner"] == "shell"


@pytest.mark.parametrize(
    "case",
    [
        "missing",
        "duplicate",
        "stitched",
        "source",
        "tree",
        "configuration",
        "lock",
        "artifact-digest",
        "bundle-digest",
        "secret",
        "private-path",
        "real-identity",
        "raw-exception",
        "semantic",
    ],
)
def test_independent_verifier_rejects_invalid_bundles(
    source_checkout: Path, case: str
) -> None:
    original = source_checkout / "original"
    HARNESS.generate_bundle(source_checkout, original)
    bundle = source_checkout / case
    shutil.copytree(original, bundle)

    manifest_path = bundle / "manifest.json"
    sequence_path = bundle / "sequence.json"
    manifest = json.loads(manifest_path.read_bytes())
    sequence = json.loads(sequence_path.read_bytes())
    if case == "missing":
        sequence_path.unlink()
    elif case == "duplicate":
        sequence["scenarios"][-1] = dict(sequence["scenarios"][0])
        _write_canonical(sequence_path, sequence)
        _reseal(bundle)
    elif case == "stitched":
        manifest["components"].append("supplemental-recovery")
        _write_canonical(manifest_path, manifest)
        _reseal(bundle)
    elif case in {"source", "tree"}:
        manifest["source"]["commit" if case == "source" else "tree"] = "0" * 40
        _write_canonical(manifest_path, manifest)
        _reseal(bundle)
    elif case in {"configuration", "lock"}:
        manifest["bindings"][f"{case}_sha256"] = "0" * 64
        _write_canonical(manifest_path, manifest)
        _reseal(bundle)
    elif case == "artifact-digest":
        digests_path = bundle / "digests.json"
        digests = json.loads(digests_path.read_bytes())
        digests["files"]["sequence.json"] = "0" * 64
        _write_canonical(digests_path, digests)
        (bundle / "bundle.sha256").write_text(
            VERIFIER._sha256(digests_path.read_bytes()) + "\n",
            encoding="ascii",
        )
    elif case == "bundle-digest":
        (bundle / "bundle.sha256").write_text("0" * 64 + "\n")
    elif case == "secret":
        manifest["secret_value"] = "synthetic-but-forbidden"
        _write_canonical(manifest_path, manifest)
        _reseal(bundle)
    elif case == "private-path":
        manifest["controller_path"] = "/Users/private/workspace"
        _write_canonical(manifest_path, manifest)
        _reseal(bundle)
    elif case == "real-identity":
        manifest["identity"]["device_id"] = "ugoos-theater"
        _write_canonical(manifest_path, manifest)
        _reseal(bundle)
    elif case == "raw-exception":
        manifest["diagnostic"] = "Traceback (most recent call last)"
        _write_canonical(manifest_path, manifest)
        _reseal(bundle)
    else:
        sequence["scenarios"][0]["expected_status"] = "noop"
        _write_canonical(sequence_path, sequence)
        _reseal(bundle)

    with pytest.raises(VERIFIER.VerificationError):
        VERIFIER.verify_bundle(bundle, source_checkout)
