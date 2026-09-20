import fcntl
import hashlib
import importlib.util
import json
import os
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


def _create_source(root: Path) -> Path:
    root.mkdir(exist_ok=True)
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


@pytest.fixture
def source_checkout(tmp_path: Path) -> Path:
    return _create_source(tmp_path / "source")


@pytest.fixture(scope="module")
def valid_bundle(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[Path, Path, str]:
    if os.environ.get("M3_RUN_EXPENSIVE_PILOT_TESTS") != "1":
        pytest.skip("executable pilot tests run outside the 60-second selector")
    root = _create_source(tmp_path_factory.mktemp("valid-bundle-source"))
    bundle = root.parent / "valid-bundle"
    digest = HARNESS.generate_bundle(root, bundle)
    return root, bundle, digest


def _write_canonical(path: Path, value: object) -> None:
    path.write_bytes(VERIFIER._canonical(value))


def _reseal(bundle: Path) -> None:
    digests = {
        "schema": VERIFIER.SCHEMA,
        "files": {
            name: VERIFIER._sha256((bundle / name).read_bytes())
            for name in ("manifest.json", "execution.json", "artifacts.json")
        },
    }
    digest_bytes = VERIFIER._canonical(digests)
    (bundle / "digests.json").write_bytes(digest_bytes)
    (bundle / "bundle.sha256").write_text(
        VERIFIER._sha256(digest_bytes) + "\n", encoding="ascii"
    )


def _reseal_artifacts(bundle: Path, artifacts: dict[str, object]) -> None:
    _write_canonical(bundle / "artifacts.json", artifacts)
    _reseal(bundle)


def _recompute_artifact(item: dict[str, object]) -> None:
    content = item["content"]
    assert isinstance(content, dict)
    content["current_digest"] = VERIFIER._canonical_current_digest(content)
    item["sha256"] = VERIFIER._sha256(VERIFIER._canonical(content))


def _working_configuration_digest(root: Path) -> str:
    paths = subprocess.run(
        [
            "git",
            "ls-files",
            "--",
            "artifacts",
            "inventory",
            "profiles",
            "secret-providers",
        ],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    digest = hashlib.sha256()
    for relative in sorted(paths):
        digest.update(relative.encode())
        digest.update(b"\0")
        digest.update((root / relative).read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def test_dry_run_executes_and_is_independently_valid(
    valid_bundle: tuple[Path, Path, str],
) -> None:
    source_checkout, first, first_digest = valid_bundle
    assert VERIFIER.verify_bundle(first, source_checkout) == first_digest
    execution = json.loads((first / "execution.json").read_bytes())
    artifacts = json.loads((first / "artifacts.json").read_bytes())
    assert execution["mode"] == "executed-offline"
    assert execution["exit_status"] == 0
    assert artifacts["documents"]
    assert any(
        isinstance(item["content"], dict)
        and item["content"].get("kind") == "CoreElecReconcilerObservationRun"
        for item in artifacts["documents"]
    )
    manifest = json.loads((first / "manifest.json").read_bytes())
    assert manifest["safety"]["device_contact"] is False
    assert manifest["safety"]["secret_resolution"] is False
    assert manifest["safety"]["skin_025_owner"] == "shell"


@pytest.mark.parametrize("ignored", [False, True])
def test_dry_run_rejects_untracked_effective_configuration(
    source_checkout: Path, ignored: bool
) -> None:
    if ignored:
        exclude = source_checkout / ".git" / "info" / "exclude"
        exclude.write_text("profiles/untracked.yaml\n")
    (source_checkout / "profiles" / "untracked.yaml").write_text("effective: true\n")

    with pytest.raises(ValueError, match="untracked"):
        HARNESS.generate_bundle(source_checkout, source_checkout / "bundle")


def test_dry_run_allows_irrelevant_untracked_files(
    valid_bundle: tuple[Path, Path, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    valid_source, valid, _ = valid_bundle
    source_checkout = tmp_path / "source"
    shutil.copytree(valid_source, source_checkout)
    (source_checkout / "notes.txt").write_text("not effective configuration\n")
    execution = json.loads((valid / "execution.json").read_bytes())
    artifacts = json.loads((valid / "artifacts.json").read_bytes())
    monkeypatch.setattr(
        HARNESS, "execute_dry_run", lambda runtime: (execution, artifacts)
    )

    digest = HARNESS.generate_bundle(source_checkout, source_checkout / "bundle")

    assert VERIFIER.verify_bundle(source_checkout / "bundle", source_checkout) == digest


@pytest.mark.parametrize("target", ("dot", "root", "parent", "home"))
def test_dry_run_rejects_destructive_output_paths(
    source_checkout: Path,
    monkeypatch: pytest.MonkeyPatch,
    target: str,
) -> None:
    monkeypatch.setenv("HOME", str(source_checkout.parent / "home"))
    home = Path.home()
    home.mkdir()
    output = {
        "dot": source_checkout,
        "root": Path("/"),
        "parent": source_checkout.parent,
        "home": home,
    }[target]

    with pytest.raises(ValueError, match="safe dedicated output"):
        HARNESS.generate_bundle(source_checkout, output)


def test_dry_run_rejects_symlink_and_arbitrary_existing_directory(
    source_checkout: Path,
) -> None:
    existing = source_checkout / "existing"
    existing.mkdir()
    symlink = source_checkout / "symlink"
    symlink.symlink_to(existing, target_is_directory=True)

    with pytest.raises(ValueError, match="harness-owned"):
        HARNESS.generate_bundle(source_checkout, existing)
    with pytest.raises(ValueError, match="symlink"):
        HARNESS.generate_bundle(source_checkout, symlink)


def test_dry_run_rejects_repository_and_session_internal_roots(
    source_checkout: Path,
) -> None:
    session_root = Path.home() / ".copilot" / "session-state"

    with pytest.raises(ValueError, match="repository or session root"):
        HARNESS.generate_bundle(source_checkout, source_checkout / ".git" / "bundle")
    with pytest.raises(ValueError, match="repository or session root"):
        HARNESS.generate_bundle(source_checkout, session_root / "bundle")


def test_dry_run_regenerates_only_owned_bundle(
    valid_bundle: tuple[Path, Path, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_checkout, valid, first = valid_bundle
    bundle = source_checkout / "regenerated"
    shutil.copytree(valid, bundle)
    marker, marker_content = HARNESS._ownership_marker(source_checkout, bundle)
    marker.write_bytes(marker_content)
    (bundle / "manifest.json").write_text("stale")
    execution = json.loads((valid / "execution.json").read_bytes())
    artifacts = json.loads((valid / "artifacts.json").read_bytes())
    monkeypatch.setattr(
        HARNESS, "execute_dry_run", lambda runtime: (execution, artifacts)
    )

    second = HARNESS.generate_bundle(source_checkout, bundle)

    assert second == first
    assert VERIFIER.verify_bundle(bundle, source_checkout) == first


def test_dry_run_rejects_unknown_content_in_owned_bundle(
    valid_bundle: tuple[Path, Path, str],
) -> None:
    source_checkout, valid, _ = valid_bundle
    bundle = source_checkout / "unknown-content"
    shutil.copytree(valid, bundle)
    marker, marker_content = HARNESS._ownership_marker(source_checkout, bundle)
    marker.write_bytes(marker_content)
    (bundle / "user-file.txt").write_text("preserve me")

    with pytest.raises(ValueError, match="unknown content"):
        HARNESS.generate_bundle(source_checkout, bundle)
    assert (bundle / "user-file.txt").read_text() == "preserve me"


@pytest.mark.parametrize("dangling", [False, True])
def test_dry_run_rejects_ownership_marker_symlink(
    valid_bundle: tuple[Path, Path, str],
    tmp_path: Path,
    dangling: bool,
) -> None:
    source_checkout, valid, _ = valid_bundle
    bundle = tmp_path / f"marker-symlink-{dangling}"
    shutil.copytree(valid, bundle)
    marker, _ = HARNESS._ownership_marker(source_checkout, bundle)
    target = tmp_path / "missing" if dangling else tmp_path / "marker-target"
    if not dangling:
        target.write_text("not an ownership marker")
    marker.symlink_to(target)

    with pytest.raises(ValueError, match="marker"):
        HARNESS.generate_bundle(source_checkout, bundle)


def test_dry_run_rejects_hardlinked_ownership_marker(
    valid_bundle: tuple[Path, Path, str],
    tmp_path: Path,
) -> None:
    source_checkout, valid, _ = valid_bundle
    bundle = tmp_path / "marker-hardlink"
    shutil.copytree(valid, bundle)
    marker, marker_content = HARNESS._ownership_marker(source_checkout, bundle)
    target = tmp_path / "marker-target"
    target.write_bytes(marker_content)
    marker.hardlink_to(target)

    with pytest.raises(ValueError, match="private regular file"):
        HARNESS.generate_bundle(source_checkout, bundle)


def test_dry_run_rejects_concurrent_marker_owner(
    valid_bundle: tuple[Path, Path, str],
    tmp_path: Path,
) -> None:
    source_checkout, valid, _ = valid_bundle
    bundle = tmp_path / "marker-locked"
    shutil.copytree(valid, bundle)
    marker, marker_content = HARNESS._ownership_marker(source_checkout, bundle)
    marker.write_bytes(marker_content)
    with marker.open("rb") as marker_stream:
        fcntl.flock(marker_stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ValueError, match="already locked"):
            HARNESS.generate_bundle(source_checkout, bundle)


def test_dry_run_rejects_orphaned_marker_creation_conflict(
    source_checkout: Path,
) -> None:
    bundle = source_checkout / "marker-conflict"
    marker, marker_content = HARNESS._ownership_marker(source_checkout, bundle)
    marker.write_bytes(marker_content)

    with pytest.raises(ValueError, match="conflicts"):
        HARNESS.generate_bundle(source_checkout, bundle)
    assert not bundle.exists()


@pytest.mark.parametrize(
    "field",
    [
        "authority_state",
        "current_digest",
        "device_id",
        "disposition",
        "failure",
        "kind",
        "observed_at",
        "observed_head_digest",
        "observed_head_revision",
        "producer",
        "record_id",
        "run_id",
        "schema_version",
        "seal_digest",
        "session_id",
        "terminal_digest",
        "terminal_revision",
        "workspace_id",
    ],
)
def test_verifier_rejects_resealed_session_close_field_changes(
    valid_bundle: tuple[Path, Path, str],
    tmp_path: Path,
    field: str,
) -> None:
    source, original, _ = valid_bundle
    bundle = tmp_path / field
    shutil.copytree(original, bundle)
    artifacts = json.loads((bundle / "artifacts.json").read_bytes())
    close = next(
        item
        for item in artifacts["documents"]
        if isinstance(item["content"], dict)
        and item["content"].get("kind") == "CoreElecReconcilerSessionClose"
        and item["content"].get("authority_state") == "released"
    )
    value = close["content"]
    replacements: dict[str, object] = {
        "authority_state": "owned",
        "current_digest": "sha256:" + "0" * 64,
        "device_id": "synthetic.other",
        "disposition": "failed",
        "failure": {"category": "transport", "code": "session_close.transport"},
        "kind": "OtherSessionClose",
        "observed_at": "2026-09-20T07:00:00Z",
        "observed_head_digest": "sha256:" + "0" * 64,
        "observed_head_revision": value["observed_head_revision"] - 1,
        "producer": {"name": "other", "version": "0.1.0"},
        "record_id": "019950f8-4c00-7000-8001-999999999999",
        "run_id": "019950f8-4c00-7000-8001-999999999999",
        "schema_version": 2,
        "seal_digest": "sha256:" + "0" * 64,
        "session_id": "session.other",
        "terminal_digest": "sha256:" + "0" * 64,
        "terminal_revision": value["terminal_revision"] - 1,
        "workspace_id": "workspace:other-session",
    }
    if field == "failure":
        value["disposition"] = "failed"
    value[field] = replacements[field]
    if field != "current_digest":
        _recompute_artifact(close)
    else:
        close["sha256"] = VERIFIER._sha256(VERIFIER._canonical(value))
    _reseal_artifacts(bundle, artifacts)

    with pytest.raises(VERIFIER.VerificationError):
        VERIFIER.verify_bundle(bundle, source)


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("action", "rollback"),
        ("mode", "abandon"),
        ("allowed", False),
        ("requires_approval", True),
        ("requires_reason", True),
        ("reason_code", "recovery.changed"),
    ],
)
def test_verifier_rejects_every_resealed_recovery_policy_field(
    valid_bundle: tuple[Path, Path, str],
    tmp_path: Path,
    field: str,
    replacement: object,
) -> None:
    source, original, _ = valid_bundle
    bundle = tmp_path / f"recovery-{field}"
    shutil.copytree(original, bundle)
    execution = json.loads((bundle / "execution.json").read_bytes())
    execution["recovery"]["actions"][0][field] = replacement
    _write_canonical(bundle / "execution.json", execution)
    _reseal(bundle)

    with pytest.raises(VERIFIER.VerificationError):
        VERIFIER.verify_bundle(bundle, source)


def test_verifier_rejects_resealed_recovery_policy_reordering(
    valid_bundle: tuple[Path, Path, str],
    tmp_path: Path,
) -> None:
    source, original, _ = valid_bundle
    bundle = tmp_path / "recovery-order"
    shutil.copytree(original, bundle)
    execution = json.loads((bundle / "execution.json").read_bytes())
    execution["recovery"]["actions"][0:2] = reversed(
        execution["recovery"]["actions"][0:2]
    )
    _write_canonical(bundle / "execution.json", execution)
    _reseal(bundle)

    with pytest.raises(VERIFIER.VerificationError):
        VERIFIER.verify_bundle(bundle, source)


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
        "working-config-binding",
        "working-lock-binding",
        "artifact-digest",
        "bundle-digest",
        "secret",
        "private-path",
        "real-identity",
        "raw-exception",
        "semantic",
        "plan-binding",
        "final-state",
        "revision-link",
        "run-current-digest",
        "observation-current-digest",
        "session-close-current-digest",
        "primitive-recomputed-digest",
    ],
)
def test_independent_verifier_rejects_invalid_bundles(
    valid_bundle: tuple[Path, Path, str],
    tmp_path: Path,
    case: str,
) -> None:
    valid_source, original, _ = valid_bundle
    source_checkout = tmp_path / "source"
    shutil.copytree(valid_source, source_checkout)
    bundle = tmp_path / f"bundle-{case}"
    shutil.copytree(original, bundle)

    manifest_path = bundle / "manifest.json"
    execution_path = bundle / "execution.json"
    manifest = json.loads(manifest_path.read_bytes())
    execution = json.loads(execution_path.read_bytes())
    artifacts = json.loads((bundle / "artifacts.json").read_bytes())
    if case == "missing":
        execution_path.unlink()
    elif case == "duplicate":
        execution["scenarios"][-1] = dict(execution["scenarios"][0])
        _write_canonical(execution_path, execution)
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
    elif case == "working-config-binding":
        (source_checkout / "profiles" / "profile.yaml").write_text(
            "synthetic: modified\n"
        )
        manifest["bindings"]["configuration_sha256"] = _working_configuration_digest(
            source_checkout
        )
        _write_canonical(manifest_path, manifest)
        _reseal(bundle)
    elif case == "working-lock-binding":
        lock = source_checkout / "uv.lock"
        lock.write_text("version = 2\n")
        manifest["bindings"]["lock_sha256"] = hashlib.sha256(
            lock.read_bytes()
        ).hexdigest()
        _write_canonical(manifest_path, manifest)
        _reseal(bundle)
    elif case == "artifact-digest":
        digests_path = bundle / "digests.json"
        digests = json.loads(digests_path.read_bytes())
        digests["files"]["execution.json"] = "0" * 64
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
    elif case == "semantic":
        execution["scenarios"][0]["operations"] = [
            {
                "primitive": "atomic-replace",
                "operation_id": "resealed.semantic.mutation",
                "disposition": "applied",
            }
        ]
        _write_canonical(execution_path, execution)
        _reseal(bundle)
    elif case == "plan-binding":
        execution["scenarios"][0]["plan_id"] = "019950f8-4c00-7000-8000-999999999999"
        _write_canonical(execution_path, execution)
        _reseal(bundle)
    elif case == "final-state":
        execution["scenarios"][0]["final_content_sha256"] = "0" * 64
        _write_canonical(execution_path, execution)
        _reseal(bundle)
    elif case == "revision-link":
        revision = next(
            item
            for item in artifacts["documents"]
            if "/revisions/00000002.json" in item["artifact_id"]
            and isinstance(item["content"], dict)
        )
        revision["content"]["previous_revision_digest"] = "sha256:" + "0" * 64
        revision["sha256"] = VERIFIER._sha256(VERIFIER._canonical(revision["content"]))
        _write_canonical(bundle / "artifacts.json", artifacts)
        _reseal(bundle)
    elif case in {"run-current-digest", "observation-current-digest"}:
        kind = (
            "CoreElecReconcilerRunReport"
            if case == "run-current-digest"
            else "CoreElecReconcilerObservationRun"
        )
        revision = next(
            item
            for item in artifacts["documents"]
            if "/revisions/" in item["artifact_id"]
            and isinstance(item["content"], dict)
            and item["content"].get("kind") == kind
        )
        revision["content"]["status"] = "tampered"
        revision["sha256"] = VERIFIER._sha256(VERIFIER._canonical(revision["content"]))
        _reseal_artifacts(bundle, artifacts)
    elif case == "session-close-current-digest":
        close = next(
            item
            for item in artifacts["documents"]
            if isinstance(item["content"], dict)
            and item["content"].get("kind") == "CoreElecReconcilerSessionClose"
        )
        close["content"]["current_digest"] = "sha256:" + "0" * 64
        close["sha256"] = VERIFIER._sha256(VERIFIER._canonical(close["content"]))
        _reseal_artifacts(bundle, artifacts)
    else:
        run_id = execution["scenarios"][0]["execution_run_id"]
        revisions = [
            item
            for item in artifacts["documents"]
            if "/revisions/" in item["artifact_id"]
            and isinstance(item["content"], dict)
            and item["content"].get("run_id") == run_id
        ]
        revisions.sort(key=lambda item: item["content"]["revision"])
        target_operation = execution["scenarios"][0]["operations"][0]["operation_id"]
        previous = None
        for revision in revisions:
            revision["content"]["previous_revision_digest"] = previous
            for evidence in revision["content"]["evidence"]:
                if (
                    evidence.get("payload_kind") == "ResourcePrimitiveIntent"
                    and evidence.get("payload", {}).get("operation_id")
                    == target_operation
                ):
                    evidence["payload"]["primitive"] = "chmod"
            _recompute_artifact(revision)
            previous = revision["content"]["current_digest"]
        prefix = revisions[0]["artifact_id"].rsplit("/revisions/", 1)[0]
        head = next(
            item
            for item in artifacts["documents"]
            if item["artifact_id"] == prefix + "/head.json"
        )
        head["content"] = {
            "digest": revisions[-1]["content"]["current_digest"],
            "revision": revisions[-1]["content"]["revision"],
        }
        head["sha256"] = VERIFIER._sha256(VERIFIER._canonical(head["content"]))
        seal = next(
            item
            for item in artifacts["documents"]
            if item["artifact_id"] == prefix + "/seal.json"
        )
        seal["content"]["terminal_digest"] = revisions[-1]["content"]["current_digest"]
        seal["sha256"] = VERIFIER._sha256(VERIFIER._canonical(seal["content"]))
        close = next(
            item
            for item in artifacts["documents"]
            if item["artifact_id"].startswith(prefix + "/session-closes/")
        )
        terminal = next(
            revision
            for revision in revisions
            if revision["content"]["status"] in VERIFIER.EXECUTION_TERMINAL_STATUSES
        )
        close["content"]["terminal_digest"] = terminal["content"]["current_digest"]
        close["content"]["observed_head_digest"] = revisions[-1]["content"][
            "current_digest"
        ]
        close["content"]["seal_digest"] = "sha256:" + seal["sha256"]
        _recompute_artifact(close)
        execution["session_closes"] = [
            {
                "artifact_id": item["artifact_id"],
                "sha256": item["sha256"],
                "record_id": item["content"]["record_id"],
                "session_id": item["content"]["session_id"],
            }
            for item in artifacts["documents"]
            if isinstance(item["content"], dict)
            and item["content"].get("kind") == "CoreElecReconcilerSessionClose"
        ]
        _write_canonical(execution_path, execution)
        _reseal_artifacts(bundle, artifacts)

    expected_error = (
        "operation receipts" if case == "primitive-recomputed-digest" else None
    )
    with pytest.raises(VERIFIER.VerificationError, match=expected_error):
        VERIFIER.verify_bundle(bundle, source_checkout)
