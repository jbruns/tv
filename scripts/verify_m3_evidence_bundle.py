#!/usr/bin/env python3

"""Independently verify an executed synthetic M3 pilot evidence bundle."""

import argparse
import base64
import hashlib
import json
import re
import subprocess
from collections import defaultdict
from pathlib import Path, PurePosixPath
from typing import Any

SCHEMA = "coreelec-reconciler-m3-pilot-dry-run-2"
EXPECTED_FILES = {
    "manifest.json",
    "execution.json",
    "artifacts.json",
    "digests.json",
    "bundle.sha256",
}
SCENARIO_NAMES = (
    "absent-create",
    "formatting-noop",
    "semantic-drift",
    "mode-drift",
    "malformed-xml",
    "explicit-removal",
    "recreate-and-kodi",
    "immediate-noop",
)
CONFIGURATION_PATHS = ("artifacts", "inventory", "profiles", "secret-providers")
FORBIDDEN_TEXT = (
    "BEGIN OPENSSH PRIVATE KEY",
    "BEGIN RSA PRIVATE KEY",
    "Traceback (most recent call last)",
    "raw_exception",
)
PRIVATE_PATH = re.compile(r"(?:/Users/|/home/|[A-Za-z]:\\\\Users\\\\)")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
RUN_KINDS = {
    "CoreElecReconcilerObservationRun",
    "CoreElecReconcilerRunReport",
}


class VerificationError(ValueError):
    pass


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify an M3 evidence bundle.")
    parser.add_argument("bundle", type=Path)
    return parser.parse_args()


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _git(root: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _git_bytes(root: Path, *arguments: str) -> bytes:
    return subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=True,
        capture_output=True,
    ).stdout


def _configuration_digest(root: Path, revision: str) -> str:
    paths = _git(
        root, "ls-tree", "-r", "--name-only", revision, "--", *CONFIGURATION_PATHS
    ).splitlines()
    digest = hashlib.sha256()
    for relative in sorted(filter(None, paths)):
        digest.update(relative.encode())
        digest.update(b"\0")
        digest.update(_git_bytes(root, "show", f"{revision}:{relative}"))
        digest.update(b"\0")
    return digest.hexdigest()


def _object(path: Path) -> dict[str, Any]:
    try:
        content = path.read_bytes()
        value = json.loads(content)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise VerificationError(f"{path.name} is not valid JSON") from error
    if not isinstance(value, dict) or _canonical(value) != content:
        raise VerificationError(f"{path.name} is not canonical JSON")
    return value


def _reject_contamination(bundle: Path) -> None:
    for path in bundle.iterdir():
        if not path.is_file():
            raise VerificationError("nested or non-file bundle content is forbidden")
        text = path.read_bytes().decode("utf-8", errors="replace")
        if PRIVATE_PATH.search(text) or any(value in text for value in FORBIDDEN_TEXT):
            raise VerificationError("bundle contains private or raw exception content")
        lowered = text.casefold()
        if any(
            marker in lowered
            for marker in (
                '"password":',
                '"private_key":',
                '"secret_value":',
                '"credential_value":',
            )
        ):
            raise VerificationError("bundle contains secret-bearing fields")


def _safe_artifact_id(value: object) -> str:
    if not isinstance(value, str):
        raise VerificationError("artifact identifier is invalid")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or not value.startswith("state/"):
        raise VerificationError("artifact identifier is unsafe")
    return value


def _validate_artifacts(artifacts: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if set(artifacts) != {"schema", "documents", "attachments"}:
        raise VerificationError("artifact envelope fields are invalid")
    if artifacts["schema"] != SCHEMA:
        raise VerificationError("artifact schema mismatch")
    documents = artifacts["documents"]
    attachments = artifacts["attachments"]
    if not isinstance(documents, list) or not isinstance(attachments, list):
        raise VerificationError("artifact collections are invalid")
    by_id: dict[str, dict[str, Any]] = {}
    document_digests: set[str] = set()
    attachment_digests: set[str] = set()
    for item in documents:
        if not isinstance(item, dict) or set(item) != {
            "artifact_id",
            "sha256",
            "canonical",
            "content",
        }:
            raise VerificationError("document artifact is invalid")
        artifact_id = _safe_artifact_id(item["artifact_id"])
        digest = item["sha256"]
        if (
            artifact_id in by_id
            or not isinstance(digest, str)
            or not SHA256.fullmatch(digest)
        ):
            raise VerificationError("document artifact is duplicated or invalid")
        if (
            item["canonical"] is not True
            or _sha256(_canonical(item["content"])) != digest
        ):
            raise VerificationError("document canonical bytes or digest are invalid")
        by_id[artifact_id] = item
        document_digests.add(digest)
    for item in attachments:
        if not isinstance(item, dict) or set(item) != {
            "artifact_id",
            "sha256",
            "content_base64",
        }:
            raise VerificationError("attachment artifact is invalid")
        artifact_id = _safe_artifact_id(item["artifact_id"])
        digest = item["sha256"]
        if (
            artifact_id in by_id
            or not isinstance(digest, str)
            or not SHA256.fullmatch(digest)
        ):
            raise VerificationError("attachment artifact is duplicated or invalid")
        try:
            content = base64.b64decode(item["content_base64"], validate=True)
        except (TypeError, ValueError) as error:
            raise VerificationError("attachment encoding is invalid") from error
        if _sha256(content) != digest:
            raise VerificationError("attachment digest is invalid")
        if "/attachments/" in artifact_id and Path(artifact_id).name != digest:
            raise VerificationError("attachment path and digest do not bind")
        by_id[artifact_id] = item
        attachment_digests.add(digest)
    if not document_digests or not attachment_digests:
        raise VerificationError("canonical documents or attachments are missing")
    _validate_revision_chains(documents)
    _validate_document_bindings(documents, document_digests, attachment_digests)
    return by_id


def _validate_revision_chains(documents: list[dict[str, Any]]) -> None:
    chains: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in documents:
        artifact_id = str(item["artifact_id"])
        content = item["content"]
        if "/revisions/" in artifact_id and isinstance(content, dict):
            chains[artifact_id.rsplit("/revisions/", 1)[0]].append(item)
    if not chains:
        raise VerificationError("Run revision chains are missing")
    for revisions in chains.values():
        revisions.sort(key=lambda item: str(item["artifact_id"]))
        previous_digest: str | None = None
        run_id: str | None = None
        for expected_revision, item in enumerate(revisions, start=1):
            content = item["content"]
            if not isinstance(content, dict):
                raise VerificationError("Run revision is not an object")
            if content.get("revision") != expected_revision:
                raise VerificationError("Run revisions are missing or duplicated")
            if content.get("previous_revision_digest") != previous_digest:
                raise VerificationError("Run revision link is invalid")
            current_run_id = content.get("run_id")
            if not isinstance(current_run_id, str):
                raise VerificationError("Run revision identity is missing")
            if run_id is None:
                run_id = current_run_id
            elif current_run_id != run_id:
                raise VerificationError("stitched Run revision chain")
            current_digest = content.get("current_digest")
            if not isinstance(current_digest, str) or not current_digest.startswith(
                "sha256:"
            ):
                raise VerificationError("Run current digest is invalid")
            previous_digest = current_digest


def _walk(value: object) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(value, dict):
        found.append(value)
        for item in value.values():
            found.extend(_walk(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(_walk(item))
    return found


def _validate_document_bindings(
    documents: list[dict[str, Any]],
    document_digests: set[str],
    attachment_digests: set[str],
) -> None:
    values = [
        item["content"] for item in documents if isinstance(item["content"], dict)
    ]
    kinds = {value.get("kind") for value in values}
    if (
        not {
            "CoreElecReconcilerPlan",
            "CoreElecReconcilerRunReport",
            "CoreElecReconcilerObservationRun",
            "CoreElecReconcilerSessionClose",
        }
        <= kinds
    ):
        raise VerificationError("required canonical document families are missing")
    plan_ids = {
        str(value["plan_id"])
        for value in values
        if value.get("kind") == "CoreElecReconcilerPlan"
        and isinstance(value.get("plan_id"), str)
    }
    run_ids = {
        str(value["run_id"])
        for value in values
        if value.get("kind") in RUN_KINDS and isinstance(value.get("run_id"), str)
    }
    if not plan_ids or not run_ids:
        raise VerificationError("Plan or Run identities are missing")
    for value in values:
        device_id = value.get("device_id")
        if device_id is not None and device_id != "synthetic.device":
            raise VerificationError("canonical document Device binding is invalid")
        plan_reference = value.get("plan_reference")
        if isinstance(plan_reference, dict):
            plan_id = plan_reference.get("plan_id")
            if (
                isinstance(plan_id, str)
                and value.get("approvals")
                and plan_id not in plan_ids
            ):
                raise VerificationError("Run references an unknown Plan")
        for nested in _walk(value):
            for key, nested_value in nested.items():
                if (
                    key in {"attachment_digest", "content_attachment_digest", "digest"}
                    and isinstance(nested_value, str)
                    and nested_value.startswith("sha256:")
                    and key != "digest"
                    and nested_value.removeprefix("sha256:") not in attachment_digests
                ):
                    raise VerificationError("document attachment binding is missing")
    if not any(
        str(item["sha256"]) in document_digests
        and isinstance(item["content"], dict)
        and item["content"].get("kind") == "CoreElecReconcilerSessionClose"
        for item in documents
    ):
        raise VerificationError("session-close evidence is missing")


def _validate_execution(
    execution: dict[str, Any],
    artifacts: dict[str, Any],
) -> None:
    if set(execution) != {
        "schema",
        "mode",
        "exit_status",
        "device_contact",
        "secret_resolution",
        "scenario_inputs",
        "scenarios",
        "outcomes",
        "recovery",
        "sessions",
        "final_device_state",
    }:
        raise VerificationError("execution fields are invalid")
    if (
        execution["schema"] != SCHEMA
        or execution["mode"] != "executed-offline"
        or execution["exit_status"] != 0
        or execution["device_contact"] is not False
        or execution["secret_resolution"] is not False
    ):
        raise VerificationError("execution boundary or exit status is invalid")
    inputs = execution["scenario_inputs"]
    if not isinstance(inputs, dict) or set(inputs) != {
        "device_id",
        "resource_id",
        "logical_address",
        "scenarios",
    }:
        raise VerificationError("scenario inputs are invalid")
    if (
        inputs["device_id"] != "synthetic.device"
        or inputs["resource_id"] != "skin.playlist.new-shows"
        or inputs["logical_address"] != "special://profile/playlists/video/NewShows.xsp"
    ):
        raise VerificationError("synthetic scenario identity is invalid")
    input_scenarios = inputs["scenarios"]
    scenarios = execution["scenarios"]
    if not isinstance(input_scenarios, list) or not isinstance(scenarios, list):
        raise VerificationError("scenario collections are invalid")
    input_by_id: dict[str, dict[str, Any]] = {}
    for item in input_scenarios:
        if (
            not isinstance(item, dict)
            or set(item) != {"id", "setup", "desired"}
            or item.get("id") in input_by_id
        ):
            raise VerificationError("scenario input is invalid or duplicated")
        input_by_id[str(item["id"])] = item
    if tuple(input_by_id) != SCENARIO_NAMES:
        raise VerificationError("required scenario names or order are invalid")

    document_digests = {
        str(item["sha256"]) for item in artifacts["documents"] if isinstance(item, dict)
    }
    observed_ids: list[str] = []
    all_run_ids: set[str] = set()
    all_plan_ids: set[str] = set()
    latest_runs: dict[str, dict[str, Any]] = {}
    for item in artifacts["documents"]:
        content = item["content"]
        if not isinstance(content, dict):
            continue
        if isinstance(content.get("run_id"), str):
            all_run_ids.add(content["run_id"])
            run_id = content["run_id"]
            if content.get("kind") == "CoreElecReconcilerRunReport" and (
                run_id not in latest_runs
                or int(content.get("revision", 0))
                > int(latest_runs[run_id].get("revision", 0))
            ):
                latest_runs[run_id] = content
        if isinstance(content.get("plan_id"), str):
            all_plan_ids.add(content["plan_id"])
    for ordinal, scenario in enumerate(scenarios, start=1):
        if not isinstance(scenario, dict):
            raise VerificationError("scenario result is invalid")
        identifier = scenario.get("id")
        if not isinstance(identifier, str) or identifier not in input_by_id:
            raise VerificationError("scenario result identity is invalid")
        observed_ids.append(identifier)
        if scenario.get("ordinal") != ordinal:
            raise VerificationError("scenario ordinals are missing or duplicated")
        source = input_by_id[identifier]
        if (
            scenario.get("setup") != source["setup"]
            or scenario.get("desired") != source["desired"]
        ):
            raise VerificationError("scenario result is not bound to its input")
        operations = scenario.get("operations")
        if not isinstance(operations, list):
            raise VerificationError("scenario operation receipts are invalid")
        primitives: list[str] = []
        for operation in operations:
            if not isinstance(operation, dict) or set(operation) != {
                "primitive",
                "operation_id",
                "disposition",
            }:
                raise VerificationError("operation receipt is invalid")
            primitive = operation["primitive"]
            if primitive not in {
                "stage-write",
                "atomic-replace",
                "chmod",
                "remove",
                "restore",
                "cleanup",
            }:
                raise VerificationError("operation primitive is invalid")
            if operation["disposition"] not in {
                "applied",
                "definitely_not_applied",
                "ambiguous",
            }:
                raise VerificationError("operation disposition is invalid")
            primitives.append(str(primitive))
        disposition = scenario.get("plan_disposition")
        execution_run_id = scenario.get("execution_run_id")
        if disposition == "noop":
            if operations or execution_run_id is not None:
                raise VerificationError("no-op scenario claims execution")
        elif disposition == "actionable":
            if not operations or not isinstance(execution_run_id, str):
                raise VerificationError("actionable scenario lacks execution evidence")
        else:
            raise VerificationError("scenario Plan disposition is invalid")
        if "atomic-replace" in primitives and (
            "stage-write" not in primitives
            or primitives.index("stage-write") > primitives.index("atomic-replace")
        ):
            raise VerificationError("atomic replace lacks prior staged write")
        if "cleanup" in primitives and primitives[-1] != "cleanup":
            raise VerificationError("cleanup is not the final Resource primitive")
        desired = scenario["desired"]
        if scenario.get("final_presence") != desired:
            raise VerificationError("scenario final state contradicts Desired State")
        if scenario.get("status") != "converged":
            raise VerificationError("scenario verification did not converge")
        if scenario.get("planning_run_id") not in all_run_ids:
            raise VerificationError("scenario planning Run is missing")
        if scenario.get("plan_id") not in all_plan_ids:
            raise VerificationError("scenario Plan is missing")
        if scenario.get("verification_run_id") not in all_run_ids:
            raise VerificationError("scenario verification Run is missing")
        verification_run = latest_runs.get(str(scenario.get("verification_run_id")))
        if verification_run is None:
            raise VerificationError("scenario verification Run report is missing")
        observations = [
            evidence["payload"]
            for evidence in verification_run.get("evidence", [])
            if isinstance(evidence, dict)
            and evidence.get("payload_kind") == "ManagedFileObservation"
            and isinstance(evidence.get("payload"), dict)
        ]
        if not observations:
            raise VerificationError("scenario verification observation is missing")
        observation = observations[-1]
        if (
            observation.get("presence") != scenario.get("final_presence")
            or observation.get("managed_mode") != scenario.get("final_mode")
            or (
                str(observation.get("content_digest")).removeprefix("sha256:")
                if observation.get("content_digest") is not None
                else None
            )
            != scenario.get("final_content_sha256")
        ):
            raise VerificationError(
                "scenario final state does not match verification evidence"
            )
        if execution_run_id is not None and execution_run_id not in all_run_ids:
            raise VerificationError("scenario execution Run is missing")
        if execution_run_id is not None:
            run = latest_runs.get(execution_run_id)
            if run is None:
                raise VerificationError("scenario execution Run report is missing")
            canonical_receipts = {
                (
                    str(payload.get("operation_id")),
                    str(payload.get("disposition")),
                )
                for evidence in run.get("evidence", [])
                if isinstance(evidence, dict)
                and evidence.get("payload_kind")
                in {"ResourcePrimitiveOutcome", "ResourceCleanupReceipt"}
                and isinstance((payload := evidence.get("payload")), dict)
            }
            claimed_receipts = {
                (
                    str(operation["operation_id"]),
                    str(operation["disposition"]),
                )
                for operation in operations
            }
            if claimed_receipts != canonical_receipts:
                raise VerificationError(
                    "scenario operation receipts do not match canonical Run evidence"
                )
        if desired == "present":
            if scenario.get("final_mode") != 0o644 or not isinstance(
                scenario.get("final_content_sha256"), str
            ):
                raise VerificationError("present final state is incomplete")
        elif (
            scenario.get("final_mode") is not None
            or scenario.get("final_content_sha256") is not None
        ):
            raise VerificationError("absent final state claims file content")
    if tuple(observed_ids) != SCENARIO_NAMES:
        raise VerificationError("scenario results are duplicated, missing, or stitched")

    outcomes = execution["outcomes"]
    if not isinstance(outcomes, list) or not outcomes:
        raise VerificationError("workflow outcomes are missing")
    labels: set[str] = set()
    for outcome in outcomes:
        if not isinstance(outcome, dict) or set(outcome) != {
            "label",
            "command",
            "outcome",
            "exit_status",
            "status",
            "run_id",
            "plan_id",
            "document_sha256",
        }:
            raise VerificationError("workflow outcome is invalid")
        label = outcome["label"]
        if not isinstance(label, str) or label in labels:
            raise VerificationError("workflow outcome is duplicated")
        labels.add(label)
        if outcome["exit_status"] != 0 and not (
            (
                label == "recovery.interrupted-apply"
                and outcome["exit_status"] == 5
                and outcome["status"]
                in {"interrupted", "failed_rolled_back", "failed_recovery_required"}
            )
            or (
                label
                in {
                    "recovery.resume_verification.rejected",
                    "recovery.rollback.rejected",
                }
                and outcome["exit_status"] == 2
                and outcome["status"] == "rejected"
            )
        ):
            raise VerificationError("workflow command did not succeed")
        digest = outcome["document_sha256"]
        if digest is not None and digest not in document_digests:
            raise VerificationError("workflow output document is missing")
    if (
        not {
            "observe.initial",
            "reconcile.approval-required",
            "recovery.inspect",
            "recovery.resume_verification.rejected",
            "recovery.rollback.rejected",
        }
        <= labels
    ):
        raise VerificationError("required public workflow outcomes are missing")

    recovery = execution["recovery"]
    if not isinstance(recovery, dict) or set(recovery) != {
        "run_id",
        "inspection_run_id",
        "actions",
    }:
        raise VerificationError("recovery evidence is invalid")
    if (
        recovery["run_id"] not in all_run_ids
        or recovery["inspection_run_id"] != recovery["run_id"]
    ):
        raise VerificationError("recovery Run binding is invalid")
    actions = recovery["actions"]
    if not isinstance(actions, list):
        raise VerificationError("recovery actions are invalid")
    action_keys = [
        (item.get("action"), item.get("mode"))
        for item in actions
        if isinstance(item, dict)
    ]
    if action_keys != [
        ("inspect", None),
        ("resume_verification", None),
        ("rollback", None),
        ("finalize", "normal"),
        ("finalize", "abandon"),
    ]:
        raise VerificationError("recovery action order or set is invalid")
    for action in actions:
        if not isinstance(action, dict) or set(action) != {
            "action",
            "mode",
            "allowed",
            "requires_approval",
            "requires_reason",
            "reason_code",
        }:
            raise VerificationError("recovery action fields are invalid")

    sessions = execution["sessions"]
    if not isinstance(sessions, list) or not sessions:
        raise VerificationError("session receipts are missing")
    for ordinal, session in enumerate(sessions, start=1):
        if (
            not isinstance(session, dict)
            or session.get("ordinal") != ordinal
            or session.get("closed") is not True
            or not isinstance(session.get("capabilities"), list)
        ):
            raise VerificationError("session receipt is invalid")
    final_state = execution["final_device_state"]
    if not isinstance(final_state, dict) or set(final_state) != {
        "logical_address",
        "presence",
        "mode",
        "content_sha256",
        "content_base64",
    }:
        raise VerificationError("final Device state is invalid")
    if final_state["logical_address"] != inputs["logical_address"]:
        raise VerificationError("final Device state claim is inconsistent")
    if final_state["presence"] == "present":
        try:
            content = base64.b64decode(final_state["content_base64"], validate=True)
        except (TypeError, ValueError) as error:
            raise VerificationError("final Device content is invalid") from error
        if (
            final_state["mode"] != 0o644
            or _sha256(content) != final_state["content_sha256"]
        ):
            raise VerificationError("final Device state claim is inconsistent")
    elif final_state != {
        "logical_address": inputs["logical_address"],
        "presence": "absent",
        "mode": None,
        "content_sha256": None,
        "content_base64": None,
    }:
        raise VerificationError("absent final Device state claims content")


def verify_bundle(bundle: Path, root: Path) -> str:
    if not bundle.is_dir():
        raise VerificationError("bundle directory is missing")
    names = {path.name for path in bundle.iterdir()}
    if names != EXPECTED_FILES:
        raise VerificationError("bundle files are missing or unexpected")
    _reject_contamination(bundle)

    manifest = _object(bundle / "manifest.json")
    execution = _object(bundle / "execution.json")
    artifacts = _object(bundle / "artifacts.json")
    digests = _object(bundle / "digests.json")
    if set(manifest) != {
        "schema",
        "bundle_kind",
        "attempts",
        "components",
        "source",
        "bindings",
        "tools",
        "execution",
        "identity",
        "safety",
    }:
        raise VerificationError("manifest fields are invalid")
    if manifest.get("schema") != SCHEMA:
        raise VerificationError("schema mismatch")
    if manifest.get("bundle_kind") != "synthetic-core-execution-dry-run":
        raise VerificationError("bundle is not executed synthetic core evidence")
    if manifest.get("attempts") != 1 or manifest.get("components") != ["core"]:
        raise VerificationError("stitched or duplicate attempt evidence is forbidden")

    source = manifest.get("source")
    bindings = manifest.get("bindings")
    if not isinstance(source, dict) or not isinstance(bindings, dict):
        raise VerificationError("source binding is missing")
    expected_source = {
        "commit": _git(root, "rev-parse", "HEAD"),
        "tree": _git(root, "rev-parse", "HEAD^{tree}"),
    }
    if source != expected_source:
        raise VerificationError("source commit or tree mismatch")
    claimed_commit = source["commit"]
    if _git(root, "rev-parse", f"{claimed_commit}^{{tree}}") != source["tree"]:
        raise VerificationError("claimed commit and tree do not correspond")
    expected_bindings = {
        "configuration_sha256": _configuration_digest(root, claimed_commit),
        "lock_sha256": _sha256(_git_bytes(root, "show", f"{claimed_commit}:uv.lock")),
        "scenario_inputs_sha256": _sha256(_canonical(execution.get("scenario_inputs"))),
    }
    if bindings != expected_bindings:
        raise VerificationError("source, configuration, lock, or scenario mismatch")

    if manifest.get("identity") != {
        "device_id": "synthetic.device",
        "resource_id": "skin.playlist.new-shows",
        "logical_address": "special://profile/playlists/video/NewShows.xsp",
    }:
        raise VerificationError("real or invalid Device identity is forbidden")
    expected_safety = {
        "dry_run_only": True,
        "device_contact": False,
        "secret_resolution": False,
        "synthetic_values_only": True,
        "live_use_authorized": False,
        "ownership_transfer_authorized": False,
        "skin_025_owner": "shell",
        "effects_changed": False,
    }
    if manifest.get("safety") != expected_safety:
        raise VerificationError("dry-run safety boundary is invalid")
    tools = manifest.get("tools")
    if (
        not isinstance(tools, dict)
        or set(tools) != {"python", "coreelec_reconciler", "uv"}
        or not all(isinstance(value, str) and value for value in tools.values())
    ):
        raise VerificationError("tool version binding is invalid")
    if manifest.get("execution") != {
        "artifact": "execution.json",
        "artifacts": "artifacts.json",
        "exit_status": execution.get("exit_status"),
    }:
        raise VerificationError("execution artifact binding is invalid")

    _validate_artifacts(artifacts)
    _validate_execution(execution, artifacts)

    expected_digests = {
        name: _sha256((bundle / name).read_bytes())
        for name in ("manifest.json", "execution.json", "artifacts.json")
    }
    if digests != {"schema": SCHEMA, "files": expected_digests}:
        raise VerificationError("artifact digest mismatch")
    digest_bytes = (bundle / "digests.json").read_bytes()
    bundle_digest = (bundle / "bundle.sha256").read_text(encoding="ascii")
    if bundle_digest != _sha256(digest_bytes) + "\n":
        raise VerificationError("bundle digest mismatch")
    return bundle_digest.strip()


def main() -> int:
    arguments = _arguments()
    root = Path(__file__).resolve().parents[1]
    try:
        digest = verify_bundle(arguments.bundle.resolve(), root)
    except (OSError, subprocess.CalledProcessError, VerificationError) as error:
        print(f"evidence bundle rejected: {error}")
        return 2
    print(f"evidence bundle verified: {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
