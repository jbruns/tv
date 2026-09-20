#!/usr/bin/env python3

"""Independently verify an executed synthetic M3 pilot evidence bundle."""

import argparse
import base64
import hashlib
import json
import re
import subprocess
from collections import defaultdict
from datetime import datetime
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
EXECUTION_TERMINAL_STATUSES = {
    "blocked",
    "noop",
    "converged",
    "failed_rolled_back",
    "failed_partial",
    "failed_recovery_required",
}
OBSERVATION_TERMINAL_STATUSES = {"observed", "observed_partial"}
SESSION_CLOSE_FIELDS = {
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
}
SAFE_CODE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
UUID7 = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
WORKSPACE = re.compile(r"^workspace:[a-zA-Z0-9_-]{8,128}$")


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


def _canonical_current_digest(value: dict[str, Any]) -> str:
    return "sha256:" + _sha256(
        _canonical(
            {key: item for key, item in value.items() if key != "current_digest"}
        )
    )


def _revision_chains(
    documents: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    chains: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in documents:
        artifact_id = str(item["artifact_id"])
        content = item["content"]
        if "/revisions/" in artifact_id and isinstance(content, dict):
            chains[artifact_id.rsplit("/revisions/", 1)[0]].append(item)
    for revisions in chains.values():
        revisions.sort(key=lambda item: str(item["artifact_id"]))
    return chains


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
        content = item["content"]
        if (
            isinstance(content, dict)
            and content.get("kind") in RUN_KINDS
            and "current_digest" in content
            and content["current_digest"] != _canonical_current_digest(content)
        ):
            raise VerificationError("Run current digest is invalid")
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
    chains = _validate_revision_chains(documents)
    _validate_document_bindings(documents, document_digests, attachment_digests, chains)
    return by_id


def _validate_revision_chains(
    documents: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    chains = _revision_chains(documents)
    if not chains:
        raise VerificationError("Run revision chains are missing")
    for revisions in chains.values():
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
            recomputed_digest = _canonical_current_digest(content)
            if current_digest != recomputed_digest:
                raise VerificationError("Run current digest is invalid")
            previous_digest = recomputed_digest
    return chains


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


def _require_sha256(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value.startswith("sha256:")
        or not SHA256.fullmatch(value.removeprefix("sha256:"))
    ):
        raise VerificationError(f"{label} is not a SHA-256 digest")
    return value


def _is_terminal_run(value: dict[str, Any]) -> bool:
    status = value.get("status")
    if value.get("kind") == "CoreElecReconcilerObservationRun":
        return status in OBSERVATION_TERMINAL_STATUSES
    return status in EXECUTION_TERMINAL_STATUSES


def _validate_session_closes(
    documents: list[dict[str, Any]],
    chains: dict[str, list[dict[str, Any]]],
) -> None:
    by_id = {str(item["artifact_id"]): item for item in documents}
    record_ids: set[str] = set()
    sessions_by_run: set[tuple[str, str]] = set()
    found = False
    for item in documents:
        value = item["content"]
        if not isinstance(value, dict) or value.get("kind") != (
            "CoreElecReconcilerSessionClose"
        ):
            continue
        found = True
        schema_version = value.get("schema_version")
        expected_fields = (
            SESSION_CLOSE_FIELDS | {"run_kind"}
            if schema_version == 2
            else SESSION_CLOSE_FIELDS
        )
        if set(value) != expected_fields or schema_version not in {1, 2}:
            raise VerificationError("session-close schema is invalid")
        if value.get("producer") != {
            "name": "coreelec-reconciler",
            "version": "0.1.0",
        }:
            raise VerificationError("session-close producer is invalid")
        run_kind = (
            value.get("run_kind")
            if schema_version == 2
            else "CoreElecReconcilerRunReport"
        )
        if run_kind not in RUN_KINDS or (
            schema_version == 2 and run_kind != "CoreElecReconcilerObservationRun"
        ):
            raise VerificationError("session-close Run kind is invalid")
        for field in ("record_id", "run_id"):
            if not isinstance(value.get(field), str) or not UUID7.fullmatch(
                value[field]
            ):
                raise VerificationError(f"session-close {field} is invalid")
        if (
            not isinstance(value.get("session_id"), str)
            or not SAFE_CODE.fullmatch(value["session_id"])
            or not isinstance(value.get("workspace_id"), str)
            or not WORKSPACE.fullmatch(value["workspace_id"])
            or value.get("device_id") != "synthetic.device"
        ):
            raise VerificationError("session-close identity is invalid")
        try:
            observed_at = datetime.fromisoformat(
                str(value["observed_at"]).replace("Z", "+00:00")
            )
        except ValueError as error:
            raise VerificationError("session-close timestamp is invalid") from error
        if observed_at.utcoffset() is None or not str(value["observed_at"]).endswith(
            "Z"
        ):
            raise VerificationError("session-close timestamp is not UTC")
        for field in ("terminal_revision", "observed_head_revision"):
            if type(value.get(field)) is not int or value[field] < 1:
                raise VerificationError(f"session-close {field} is invalid")
        for field in (
            "terminal_digest",
            "observed_head_digest",
            "current_digest",
        ):
            _require_sha256(value.get(field), f"session-close {field}")
        seal_digest = value.get("seal_digest")
        if seal_digest is not None:
            _require_sha256(seal_digest, "session-close seal digest")
        if value["current_digest"] != _canonical_current_digest(value):
            raise VerificationError("session-close current digest is invalid")
        disposition = value.get("disposition")
        failure = value.get("failure")
        if disposition == "complete":
            if failure is not None:
                raise VerificationError("complete session close contains failure")
        elif disposition in {"failed", "unknown"}:
            if (
                not isinstance(failure, dict)
                or set(failure) != {"category", "code"}
                or failure.get("category")
                not in {"local_runtime", "protocol", "timeout", "transport", "unknown"}
                or not isinstance(failure.get("code"), str)
                or not SAFE_CODE.fullmatch(failure["code"])
            ):
                raise VerificationError("session-close failure is invalid")
        else:
            raise VerificationError("session-close disposition is invalid")

        record_id = value["record_id"]
        session_key = (value["run_id"], value["session_id"])
        if record_id in record_ids or session_key in sessions_by_run:
            raise VerificationError("session-close idempotency identity is duplicated")
        record_ids.add(record_id)
        sessions_by_run.add(session_key)
        artifact_id = str(item["artifact_id"])
        if (
            "/session-closes/" not in artifact_id
            or Path(artifact_id).name != _sha256(record_id.encode()) + ".json"
        ):
            raise VerificationError("session-close artifact path is invalid")
        prefix = artifact_id.rsplit("/session-closes/", 1)[0]
        revisions = chains.get(prefix)
        identity_item = by_id.get(prefix + "/identity.json")
        head_item = by_id.get(prefix + "/head.json")
        if (
            not revisions
            or identity_item is None
            or head_item is None
            or not isinstance(identity_item["content"], dict)
            or not isinstance(head_item["content"], dict)
        ):
            raise VerificationError("session-close workspace artifacts are missing")
        identity = identity_item["content"]
        if (
            identity.get("kind") != run_kind
            or identity.get("run_id") != value["run_id"]
            or identity.get("workspace_id") != value["workspace_id"]
            or identity.get("device_id") != value["device_id"]
        ):
            raise VerificationError("session-close workspace identity mismatch")
        revision_values = [revision["content"] for revision in revisions]
        terminal = next(
            (
                revision
                for revision in revision_values
                if isinstance(revision, dict) and _is_terminal_run(revision)
            ),
            None,
        )
        if terminal is None:
            raise VerificationError("session-close terminal Run is missing")
        terminal_revision = value["terminal_revision"]
        observed_revision = value["observed_head_revision"]
        if (
            terminal.get("revision") != terminal_revision
            or terminal.get("current_digest") != value["terminal_digest"]
            or observed_revision < terminal_revision
            or observed_revision > len(revision_values)
        ):
            raise VerificationError("session-close terminal binding is invalid")
        observed = revision_values[observed_revision - 1]
        if (
            not isinstance(observed, dict)
            or not _is_terminal_run(observed)
            or observed.get("current_digest") != value["observed_head_digest"]
            or head_item["content"]
            != {
                "digest": revision_values[-1]["current_digest"],
                "revision": revision_values[-1]["revision"],
            }
            or observed_revision != revision_values[-1]["revision"]
        ):
            raise VerificationError("session-close observed-head binding is invalid")
        authority = observed.get("authority")
        cleanup = observed.get("cleanup")
        if run_kind == "CoreElecReconcilerObservationRun":
            if (
                value["authority_state"] != "not_applicable"
                or seal_digest is not None
                or authority is not None
                or cleanup is not None
            ):
                raise VerificationError("observation session-close binding is invalid")
        elif (
            not isinstance(authority, dict)
            or not isinstance(cleanup, dict)
            or value["authority_state"] != authority.get("ownership_state")
            or authority.get("cleanup_state") != cleanup.get("state")
            or value["authority_state"] == "not_applicable"
        ):
            raise VerificationError("execution session-close binding is invalid")
        seal_item = by_id.get(prefix + "/seal.json")
        if seal_digest is None:
            if seal_item is not None:
                raise VerificationError("session-close omits existing seal")
        elif (
            seal_item is None
            or seal_digest != "sha256:" + str(seal_item["sha256"])
            or not isinstance(seal_item["content"], dict)
            or seal_item["content"]
            != {
                "ownership_released_or_quarantined": True,
                "terminal_digest": observed["current_digest"],
                "terminal_revision": observed["revision"],
            }
            or value["authority_state"] not in {"released", "quarantined"}
        ):
            raise VerificationError("session-close authority seal binding is invalid")
    if not found:
        raise VerificationError("session-close evidence is missing")


def _validate_document_bindings(
    documents: list[dict[str, Any]],
    document_digests: set[str],
    attachment_digests: set[str],
    chains: dict[str, list[dict[str, Any]]],
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
    _validate_session_closes(documents, chains)


def _canonical_operation_receipts(run: dict[str, Any]) -> list[dict[str, Any]]:
    evidence = run.get("evidence")
    if not isinstance(evidence, list):
        raise VerificationError("execution Run evidence is invalid")
    intents: dict[str, tuple[int, dict[str, Any], dict[str, Any]]] = {}
    checkpoints: dict[str, tuple[int, dict[str, Any]]] = {}
    receipts: list[tuple[int, dict[str, Any]]] = []
    for index, item in enumerate(evidence):
        if not isinstance(item, dict) or not isinstance(item.get("payload"), dict):
            continue
        payload = item["payload"]
        operation_id = payload.get("operation_id")
        if not isinstance(operation_id, str):
            continue
        kind = item.get("payload_kind")
        if kind == "ResourcePrimitiveIntent":
            if operation_id in intents or not isinstance(item.get("bindings"), dict):
                raise VerificationError("duplicate or unbound primitive intent")
            intents[operation_id] = (index, item["bindings"], payload)
        elif kind == "RemoteMarkerCheckpoint":
            if operation_id in checkpoints:
                raise VerificationError("duplicate primitive checkpoint")
            checkpoints[operation_id] = (index, payload)
        elif kind in {"ResourcePrimitiveOutcome", "ResourceCleanupReceipt"}:
            receipts.append((index, item))
    result: list[dict[str, Any]] = []
    receipt_sequence = 0
    for ordinal, (outcome_index, outcome) in enumerate(receipts, start=1):
        payload = outcome["payload"]
        operation_id = payload["operation_id"]
        intent_record = intents.get(operation_id)
        checkpoint_record = checkpoints.get(operation_id)
        if intent_record is None or checkpoint_record is None:
            raise VerificationError("primitive receipt lacks intent or checkpoint")
        intent_index, bindings, intent = intent_record
        checkpoint_index, checkpoint = checkpoint_record
        if not intent_index < checkpoint_index < outcome_index:
            raise VerificationError(
                "primitive intent/checkpoint/outcome order is invalid"
            )
        if (
            checkpoint.get("operation_id") != intent.get("operation_id")
            or checkpoint.get("marker_digest") != intent.get("marker_digest")
            or checkpoint.get("generation") != intent.get("marker_generation")
            or checkpoint.get("phase") != intent.get("marker_phase")
            or checkpoint.get("token_digest") != intent.get("token_digest")
        ):
            raise VerificationError("primitive checkpoint does not bind its intent")
        primitive = intent.get("primitive")
        outcome_kind = outcome.get("payload_kind")
        if (primitive == "cleanup") != (outcome_kind == "ResourceCleanupReceipt"):
            raise VerificationError("cleanup receipt kind is inconsistent")
        if outcome_kind == "ResourcePrimitiveOutcome":
            receipt_sequence += 1
            if payload.get("receipt_sequence") != receipt_sequence:
                raise VerificationError("primitive receipt sequence is invalid")
        result.append(
            {
                "ordinal": ordinal,
                "resource_id": bindings.get("resource_id"),
                "change_id": bindings.get("change_id"),
                "operation_id": operation_id,
                "primitive": str(primitive).replace("_", "-"),
                "disposition": payload.get("disposition"),
            }
        )
    if len(result) != len(intents):
        raise VerificationError("primitive intent or receipt is missing")
    return result


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
        "session_closes",
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
                "ordinal",
                "resource_id",
                "change_id",
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
            if (
                operation["ordinal"] != len(primitives) + 1
                or operation["resource_id"] != inputs["resource_id"]
                or not isinstance(operation["change_id"], str)
                or not operation["operation_id"].startswith(
                    operation["change_id"] + "."
                )
            ):
                raise VerificationError("operation identity or order is invalid")
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
            if operations != _canonical_operation_receipts(run):
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
    recovery_run = latest_runs.get(str(recovery["run_id"]))
    if recovery_run is None:
        raise VerificationError("recovery Run report is missing")
    recovery_close = next(
        (
            item["content"]
            for item in artifacts["documents"]
            if isinstance(item["content"], dict)
            and item["content"].get("kind") == "CoreElecReconcilerSessionClose"
            and item["content"].get("run_id") == recovery["run_id"]
        ),
        None,
    )
    if not isinstance(recovery_close, dict):
        raise VerificationError("recovery session-close record is missing")
    evidence = recovery_run.get("evidence")
    results = recovery_run.get("resource_results")
    if not isinstance(evidence, list) or not isinstance(results, list):
        raise VerificationError("recovery Run evidence is invalid")
    ambiguous = any(
        isinstance(item, dict)
        and item.get("payload_kind") == "ResourcePrimitiveOutcome"
        and isinstance(item.get("payload"), dict)
        and item["payload"].get("disposition") == "ambiguous"
        for item in evidence
    )
    forward_work_unperformed = any(
        isinstance(item, dict) and item.get("mutation_outcome") == "pending"
        for item in results
    )
    preparation_complete = any(
        isinstance(item, dict)
        and item.get("payload_kind") == "ResourcePreparationCompleted"
        for item in evidence
    )
    rollback_declared = any(
        isinstance(item, dict)
        and item.get("payload_kind") == "ResourcePreparationCompleted"
        and isinstance(item.get("payload"), dict)
        and item["payload"].get("rollback_capable") is True
        for item in evidence
    )
    rollback_approved = any(
        isinstance(item, dict) and item.get("scope") == "apply"
        for item in recovery_run.get("approvals", [])
    )
    relations = {
        item.get("latest_observed_relation")
        for item in results
        if isinstance(item, dict)
    }
    stable_and_bound = recovery_close["authority_state"] not in {
        "unknown",
        "not_applicable",
    }
    resume_allowed = (
        stable_and_bound
        and not forward_work_unperformed
        and recovery_run.get("status") in {"executing", "interrupted"}
        and not ambiguous
    )
    rollback_allowed = (
        stable_and_bound
        and preparation_complete
        and rollback_declared
        and rollback_approved
        and bool(relations & {"before", "post", "allowed_intermediate"})
        and not ambiguous
    )
    normal_finalize = recovery_run.get("status") in EXECUTION_TERMINAL_STATUSES
    abandon = recovery_close["authority_state"] not in {
        "released",
        "not_applicable",
    }
    expected_actions = [
        {
            "action": "inspect",
            "mode": None,
            "allowed": True,
            "requires_approval": False,
            "requires_reason": False,
            "reason_code": "recovery.workspace-present",
        },
        {
            "action": "resume_verification",
            "mode": None,
            "allowed": resume_allowed,
            "requires_approval": False,
            "requires_reason": False,
            "reason_code": (
                "recovery.verification-only-work-available"
                if resume_allowed
                else "recovery.resume-not-safe"
            ),
        },
        {
            "action": "rollback",
            "mode": None,
            "allowed": rollback_allowed,
            "requires_approval": False,
            "requires_reason": False,
            "reason_code": (
                "recovery.rollback-capable-before-evidence-present"
                if rollback_allowed
                else "recovery.rollback-not-authorized"
            ),
        },
        {
            "action": "finalize",
            "mode": "normal",
            "allowed": normal_finalize,
            "requires_approval": False,
            "requires_reason": False,
            "reason_code": (
                "recovery.normal-finalization-available"
                if normal_finalize
                else "recovery.final-state-not-known"
            ),
        },
        {
            "action": "finalize",
            "mode": "abandon",
            "allowed": abandon,
            "requires_approval": True,
            "requires_reason": True,
            "reason_code": (
                "recovery.abandonment-available"
                if abandon
                else "recovery.ownership-not-identifiable"
            ),
        },
    ]
    if actions != expected_actions:
        raise VerificationError("recovery action policy is inconsistent")

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
    session_closes = execution["session_closes"]
    if not isinstance(session_closes, list):
        raise VerificationError("session-close receipts are invalid")
    expected_session_closes = [
        {
            "artifact_id": item["artifact_id"],
            "sha256": item["sha256"],
            "record_id": item["content"]["record_id"],
            "session_id": item["content"]["session_id"],
        }
        for item in artifacts["documents"]
        if isinstance(item, dict)
        and isinstance(item.get("content"), dict)
        and item["content"].get("kind") == "CoreElecReconcilerSessionClose"
    ]
    if session_closes != expected_session_closes:
        raise VerificationError("session-close receipt binding is invalid")
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
