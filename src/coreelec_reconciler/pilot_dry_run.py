"""Deterministic offline execution used by the M3 pilot evidence harness."""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

from coreelec_reconciler.application.commands import (
    ApplyCommand,
    Command,
    ObserveCommand,
    PlanCommand,
    ReconcileCommand,
    RecoverCommand,
    ReportCommand,
    VerifyCommand,
)
from coreelec_reconciler.application.outcomes import (
    ApplyOutcome,
    CanonicalPlanOutcome,
    ObservationOutcome,
    RecoveryInspectionOutcome,
    UnsupportedOutcome,
    VerifyOutcome,
)
from coreelec_reconciler.bootstrap import BootstrapSettings, bootstrap
from coreelec_reconciler.cli.presentation import presentation_for
from coreelec_reconciler.domain.execution import (
    MutationDisposition,
    MutationReceipt,
    NormalizedResourceState,
    Presence,
)
from coreelec_reconciler.domain.identifiers import DeviceId
from coreelec_reconciler.transports.interfaces import (
    DeviceCapabilitySnapshot,
    DeviceIdentity,
    EntryKind,
    FileMetadata,
    ReadFailure,
    ReadFailureCode,
    ReadResult,
)
from coreelec_reconciler.transports.remote_ownership import (
    AuthorityConflict,
    RemoteAuthorityBackend,
    RemoteObject,
    RemoteObjectKind,
)

SCHEMA = "coreelec-reconciler-m3-pilot-dry-run-2"
DEVICE_ID = DeviceId("synthetic.device")
RESOURCE_ID = "skin.playlist.new-shows"
LOGICAL_ADDRESS = "special://profile/playlists/video/NewShows.xsp"
MANAGED_PATH = "/storage/.kodi/userdata/playlists/video/NewShows.xsp"
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
SCENARIO_INPUTS = (
    {"id": "absent-create", "setup": "absent", "desired": "present"},
    {"id": "formatting-noop", "setup": "formatting-only", "desired": "present"},
    {"id": "semantic-drift", "setup": "semantic-drift", "desired": "present"},
    {"id": "mode-drift", "setup": "mode-drift", "desired": "present"},
    {"id": "malformed-xml", "setup": "malformed", "desired": "present"},
    {"id": "explicit-removal", "setup": "converged", "desired": "absent"},
    {"id": "recreate-and-kodi", "setup": "absent", "desired": "present"},
    {"id": "immediate-noop", "setup": "converged", "desired": "present"},
)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode()


@dataclass(frozen=True, slots=True)
class _Entry:
    mode: int
    content: bytes
    kind: EntryKind = EntryKind.REGULAR
    readable: bool = True


class _ManagedFiles:
    def __init__(self) -> None:
        self.entries: dict[str, _Entry] = {}
        self.operations: list[dict[str, str]] = []
        self._faults: dict[str, list[tuple[MutationDisposition, bool]]] = {}

    def put(self, path: str, entry: _Entry) -> None:
        self.entries[path] = entry

    def discard(self, path: str) -> None:
        self.entries.pop(path, None)

    def lstat(self, path: str) -> ReadResult:
        entry = self.entries.get(path)
        if entry is None:
            return ReadResult(
                None, ReadFailure(ReadFailureCode.NOT_FOUND, "entry is absent")
            )
        return ReadResult(FileMetadata(entry.kind, entry.mode, len(entry.content)))

    def read(self, path: str, limit: int) -> ReadResult:
        entry = self.entries.get(path)
        if entry is None:
            return ReadResult(
                None, ReadFailure(ReadFailureCode.NOT_FOUND, "entry is absent")
            )
        if not entry.readable:
            return ReadResult(
                None, ReadFailure(ReadFailureCode.UNREADABLE, "entry is unreadable")
            )
        if len(entry.content) > limit:
            return ReadResult(
                None, ReadFailure(ReadFailureCode.TOO_LARGE, "entry exceeds limit")
            )
        return ReadResult(entry.content)

    def lost_ack(self, primitive: str, *, applied: bool) -> None:
        self._faults.setdefault(primitive, []).append(
            (MutationDisposition.AMBIGUOUS, applied)
        )

    def fault(self, primitive: str, disposition: MutationDisposition) -> None:
        self._faults.setdefault(primitive, []).append(
            (
                disposition,
                disposition is not MutationDisposition.DEFINITELY_NOT_APPLIED,
            )
        )

    def stage_write(
        self,
        path: str,
        content: bytes,
        mode: int,
        operation_id: str,
        *,
        expected: NormalizedResourceState,
        binding_digest: str,
    ) -> MutationReceipt:
        if not _bound_stage(path, binding_digest):
            return self._receipt(
                "stage-write",
                operation_id,
                MutationDisposition.DEFINITELY_NOT_APPLIED,
            )
        existing = self.entries.get(path)
        if expected.presence is Presence.ABSENT and existing is not None:
            disposition = (
                MutationDisposition.APPLIED
                if existing.kind is EntryKind.REGULAR
                and existing.mode == mode
                and existing.content == content
                else MutationDisposition.DEFINITELY_NOT_APPLIED
            )
            return self._receipt("stage-write", operation_id, disposition)
        if not self._matches(path, expected):
            return self._receipt(
                "stage-write",
                operation_id,
                MutationDisposition.DEFINITELY_NOT_APPLIED,
            )
        disposition, applied = self._outcome("stage_write")
        if applied:
            self.entries[path] = _Entry(mode, content)
        return self._receipt("stage-write", operation_id, disposition)

    def chmod(
        self,
        path: str,
        mode: int,
        operation_id: str,
        *,
        expected: NormalizedResourceState,
        binding_digest: str,
    ) -> MutationReceipt:
        del binding_digest
        if not self._matches(path, expected):
            return self._receipt(
                "chmod", operation_id, MutationDisposition.DEFINITELY_NOT_APPLIED
            )
        disposition, applied = self._outcome("chmod")
        entry = self.entries.get(path)
        if applied and entry is not None:
            self.entries[path] = _Entry(mode, entry.content, entry.kind, entry.readable)
        return self._receipt("chmod", operation_id, disposition)

    def atomic_replace(
        self,
        staged_path: str,
        destination: str,
        operation_id: str,
        *,
        expected_staged: NormalizedResourceState,
        expected_destination: NormalizedResourceState,
        binding_digest: str,
    ) -> MutationReceipt:
        if (
            not _bound_stage(staged_path, binding_digest)
            or not self._matches(staged_path, expected_staged)
            or not self._matches(destination, expected_destination)
        ):
            return self._receipt(
                "atomic-replace",
                operation_id,
                MutationDisposition.DEFINITELY_NOT_APPLIED,
            )
        disposition, applied = self._outcome("atomic_replace")
        staged = self.entries.get(staged_path)
        if applied and staged is not None:
            self.entries[destination] = staged
            del self.entries[staged_path]
        return self._receipt("atomic-replace", operation_id, disposition)

    def remove(
        self,
        path: str,
        operation_id: str,
        *,
        expected: NormalizedResourceState,
        binding_digest: str,
    ) -> MutationReceipt:
        del binding_digest
        if not self._matches(path, expected):
            return self._receipt(
                "remove", operation_id, MutationDisposition.DEFINITELY_NOT_APPLIED
            )
        disposition, applied = self._outcome("remove")
        if applied:
            self.entries.pop(path, None)
        return self._receipt("remove", operation_id, disposition)

    def restore(
        self,
        path: str,
        content: bytes | None,
        mode: int | None,
        operation_id: str,
        *,
        expected: NormalizedResourceState,
        binding_digest: str,
    ) -> MutationReceipt:
        del binding_digest
        if not self._matches(path, expected):
            return self._receipt(
                "restore", operation_id, MutationDisposition.DEFINITELY_NOT_APPLIED
            )
        disposition, applied = self._outcome("restore")
        if applied:
            if content is None:
                self.entries.pop(path, None)
            else:
                self.entries[path] = _Entry(mode or 0, content)
        return self._receipt("restore", operation_id, disposition)

    def cleanup(
        self,
        path: str,
        operation_id: str,
        *,
        expected: NormalizedResourceState,
        binding_digest: str,
    ) -> MutationReceipt:
        del binding_digest
        if not self._matches(path, expected):
            return self._receipt(
                "cleanup", operation_id, MutationDisposition.DEFINITELY_NOT_APPLIED
            )
        disposition, applied = self._outcome("cleanup")
        if applied:
            self.entries.pop(path, None)
        return self._receipt("cleanup", operation_id, disposition)

    def _matches(self, path: str, expected: NormalizedResourceState) -> bool:
        entry = self.entries.get(path)
        if expected.presence is Presence.ABSENT:
            return entry is None
        if expected.presence is not Presence.PRESENT or entry is None:
            return False
        return (
            expected.entry_kind == entry.kind.value
            and expected.content_digest == "sha256:" + _sha256(entry.content)
            and expected.managed_mode == entry.mode
        )

    def _outcome(self, primitive: str) -> tuple[MutationDisposition, bool]:
        queue = self._faults.get(primitive)
        return queue.pop(0) if queue else (MutationDisposition.APPLIED, True)

    def _receipt(
        self,
        primitive: str,
        operation_id: str,
        disposition: MutationDisposition,
    ) -> MutationReceipt:
        self.operations.append(
            {
                "primitive": primitive,
                "operation_id": operation_id,
                "disposition": disposition.value,
            }
        )
        return MutationReceipt(operation_id, disposition)


class _RemoteDevice(RemoteAuthorityBackend):
    def __init__(self) -> None:
        self.ownership = RemoteObject(RemoteObjectKind.ABSENT)
        self.quarantine = RemoteObject(RemoteObjectKind.ABSENT)

    def inspect_ownership(self, device_key: str) -> RemoteObject:
        del device_key
        return self.ownership

    def inspect_quarantine(self, device_key: str) -> RemoteObject:
        del device_key
        return self.quarantine

    def create_ownership_if_unowned_and_not_quarantined(
        self, device_key: str, payload: bytes, expected_digest: str
    ) -> None:
        del device_key
        if (
            self.ownership.kind is not RemoteObjectKind.ABSENT
            or self.quarantine.kind is not RemoteObjectKind.ABSENT
            or _prefixed_digest(payload) != expected_digest
        ):
            raise AuthorityConflict("synthetic ownership acquisition rejected")
        self.ownership = RemoteObject(RemoteObjectKind.REGULAR, payload)

    def replace_ownership(
        self,
        device_key: str,
        expected_digest: str,
        payload: bytes,
        next_digest: str,
    ) -> None:
        del device_key
        if (
            self.ownership.payload is None
            or _prefixed_digest(self.ownership.payload) != expected_digest
            or _prefixed_digest(payload) != next_digest
        ):
            raise AuthorityConflict("synthetic ownership compare rejected")
        self.ownership = RemoteObject(RemoteObjectKind.REGULAR, payload)

    def remove_ownership(
        self,
        device_key: str,
        expected_digest: str,
        terminal_receipt_digest: str,
    ) -> MutationReceipt:
        del device_key
        if (
            self.ownership.payload is None
            or _prefixed_digest(self.ownership.payload) != expected_digest
            or json.loads(self.ownership.payload).get("manifest_digest")
            != terminal_receipt_digest
        ):
            raise AuthorityConflict("synthetic terminal evidence rejected")
        self.ownership = RemoteObject(RemoteObjectKind.ABSENT)
        return MutationReceipt("remote-ownership-release", MutationDisposition.APPLIED)

    def convert_to_quarantine(
        self,
        device_key: str,
        expected_digest: str,
        payload: bytes,
        next_digest: str,
    ) -> None:
        del device_key
        if (
            self.ownership.payload is None
            or _prefixed_digest(self.ownership.payload) != expected_digest
            or _prefixed_digest(payload) != next_digest
        ):
            raise AuthorityConflict("synthetic quarantine compare rejected")
        self.quarantine = RemoteObject(RemoteObjectKind.REGULAR, payload)
        self.ownership = RemoteObject(RemoteObjectKind.ABSENT)


class _Runtime:
    def __init__(self) -> None:
        self._uuid = 0
        self._instant = datetime(2026, 9, 20, 6, 0, tzinfo=UTC)

    def utc_now(self) -> str:
        value = self._instant.isoformat().replace("+00:00", "Z")
        self._instant += timedelta(seconds=1)
        return value

    def new_uuid7(self) -> str:
        self._uuid += 1
        return f"019950f8-4c00-7000-8001-{self._uuid:012d}"

    def new_ownership_token(self) -> bytes:
        return bytes([self._uuid % 251 + 1]) * 32


@dataclass(slots=True)
class _Session:
    files: _ManagedFiles
    remote: _RemoteDevice
    required: frozenset[str]
    closed: bool = False

    @property
    def identity(self) -> DeviceIdentity:
        return DeviceIdentity(DEVICE_ID, "sha256:" + "a" * 64, "boot.synthetic")

    @property
    def capabilities(self) -> DeviceCapabilitySnapshot:
        from coreelec_reconciler.domain.configuration import ProfileRootCapability

        return DeviceCapabilitySnapshot(
            ProfileRootCapability("/storage/.kodi/userdata"), True
        )

    @property
    def managed_files(self) -> _ManagedFiles:
        if "managed_file.read" not in self.required:
            raise RuntimeError("synthetic session lacks managed_file.read")
        return self.files

    @property
    def managed_file_mutations(self) -> _ManagedFiles:
        if (
            not {
                "managed_file.write",
                "atomic_replace_over_existing",
            }
            <= self.required
        ):
            raise RuntimeError("synthetic session lacks mutation capabilities")
        return self.files

    def remote_ownership(self, workspace_key: str) -> _RemoteDevice:
        if "remote_run_ownership" not in self.required or len(workspace_key) != 64:
            raise RuntimeError("synthetic session lacks remote ownership capability")
        return self.remote

    def close(self) -> None:
        self.closed = True


def _bound_stage(path: str, binding_digest: str) -> bool:
    token = binding_digest.removeprefix("sha256:")
    return path.endswith(f".{token}.stage") or f"/runs/{token}/stage/" in path


def _prefixed_digest(payload: bytes) -> str:
    return "sha256:" + _sha256(payload)


def _write_repository(root: Path, desired: str = "present") -> None:
    for relative in (
        "artifacts",
        "inventory",
        "profiles/platform",
        "profiles/room",
        "profiles/device",
        "secret-providers",
    ):
        (root / relative).mkdir(parents=True, exist_ok=True)
    (root / "artifacts/catalog.yaml").write_text(
        "kind: ArtifactCatalog\nschema_version: 1\nartifacts: []\n"
    )
    (root / "secret-providers/controller-environment.yaml").write_text(
        """kind: SecretProviderCatalog
schema_version: 1
providers:
  - id: controller.environment
    type: environment
    keys:
      synthetic-key:
        variable: SYNTHETIC_PRIVATE_KEY_FILE
"""
    )
    (root / "inventory/synthetic.yaml").write_text(
        """kind: DeviceInventory
schema_version: 1
devices:
  - id: synthetic.device
    endpoint:
      host: synthetic.invalid
      port: 22
    ssh:
      username: synthetic
      host_key:
        policy: pinned
        reference: ssh-host-key.synthetic
      credential:
        type: secret
        provider: controller.environment
        key: synthetic-key
    profiles:
      platform: platform.synthetic
      room: room.synthetic
      device: device.synthetic
"""
    )
    (root / "profiles/room/synthetic.yaml").write_text(
        """kind: Profile
schema_version: 1
id: room.synthetic
layer: room
resources:
  - id: skin.playlist.new-shows
    type: KodiSmartPlaylist
    management: enforce
    desired: present
    selectors: [selector.baseline, selector.skin, selector.room]
    requires: []
    intent:
      playlist:
        limit: 40
"""
    )
    (root / "profiles/device/synthetic.yaml").write_text(
        """kind: Profile
schema_version: 1
id: device.synthetic
layer: device
resources:
  - id: skin.playlist.new-shows
    type: KodiSmartPlaylist
    management: enforce
    desired: present
    selectors: [selector.baseline, selector.skin, selector.room]
    requires: []
    intent:
      playlist:
        limit: 50
"""
    )
    _write_desired(root, desired)


def _write_desired(root: Path, desired: str) -> None:
    present_intent = """intent:
      playlist:
        id: playlist.video.new-shows
        media_type: tvshows
        display_name: New Shows
        match: all
        limit: 50
        rules:
          - field: playcount
            operator: is
            value: 0
        order:
          by: dateadded
          direction: descending
      file:
        mode: "0644\""""
    absent_intent = """intent:
      playlist:
        id: playlist.video.new-shows
        media_type: tvshows"""
    intent = present_intent if desired == "present" else absent_intent
    (root / "profiles/platform/synthetic.yaml").write_text(
        f"""kind: Profile
schema_version: 1
id: platform.synthetic
layer: platform
resources:
  - id: skin.playlist.new-shows
    type: KodiSmartPlaylist
    management: enforce
    desired: {desired}
    selectors: [selector.baseline, selector.skin]
    requires: []
    {intent}
"""
    )
    overlay_intent = (
        """intent:
      playlist:
        limit: 40"""
        if desired == "present"
        else absent_intent
    )
    (root / "profiles/room/synthetic.yaml").write_text(
        f"""kind: Profile
schema_version: 1
id: room.synthetic
layer: room
resources:
  - id: skin.playlist.new-shows
    type: KodiSmartPlaylist
    management: enforce
    desired: {desired}
    selectors: [selector.baseline, selector.skin, selector.room]
    requires: []
    {overlay_intent}
"""
    )
    device_intent = (
        """intent:
      playlist:
        limit: 50"""
        if desired == "present"
        else absent_intent
    )
    (root / "profiles/device/synthetic.yaml").write_text(
        f"""kind: Profile
schema_version: 1
id: device.synthetic
layer: device
resources:
  - id: skin.playlist.new-shows
    type: KodiSmartPlaylist
    management: enforce
    desired: {desired}
    selectors: [selector.baseline, selector.skin, selector.room]
    requires: []
    {device_intent}
"""
    )


def _outcome_record(label: str, command: Command, outcome: object) -> dict[str, object]:
    if isinstance(outcome, UnsupportedOutcome):
        raise RuntimeError(
            f"synthetic workflow unavailable: {label}: "
            f"{outcome.reason.value} ({outcome.diagnostic_code})"
        )
    presentation = presentation_for(outcome, command)  # type: ignore[arg-type]
    status = getattr(outcome, "status", None)
    run_id = getattr(outcome, "run_id", None)
    plan_id = getattr(outcome, "plan_id", None)
    return {
        "label": label,
        "command": type(command).__name__,
        "outcome": type(outcome).__name__,
        "exit_status": presentation.exit_code,
        "status": getattr(status, "value", None),
        "run_id": getattr(run_id, "value", None),
        "plan_id": getattr(plan_id, "value", None),
        "document_sha256": (
            _sha256(presentation.document)
            if presentation.document is not None
            else None
        ),
    }


def _state_artifacts(roots: tuple[tuple[str, Path], ...]) -> dict[str, object]:
    documents: list[dict[str, object]] = []
    attachments: list[dict[str, object]] = []
    for prefix, root in roots:
        if not root.exists():
            continue
        for path in sorted(item for item in root.rglob("*") if item.is_file()):
            if path.name == "lease" or path.suffix == ".lease":
                continue
            relative = f"{prefix}/{path.relative_to(root).as_posix()}"
            content = path.read_bytes()
            try:
                value = json.loads(content)
            except UnicodeDecodeError, json.JSONDecodeError:
                attachments.append(
                    {
                        "artifact_id": relative,
                        "sha256": _sha256(content),
                        "content_base64": base64.b64encode(content).decode("ascii"),
                    }
                )
                continue
            documents.append(
                {
                    "artifact_id": relative,
                    "sha256": _sha256(content),
                    "canonical": _canonical(value) == content,
                    "content": value,
                }
            )
    return {
        "schema": SCHEMA,
        "documents": documents,
        "attachments": attachments,
    }


def execute_dry_run(workspace: Path) -> tuple[dict[str, object], dict[str, object]]:
    repository = workspace / "repository"
    state = workspace / "state"
    repository.mkdir(parents=True)
    _write_repository(repository)
    files = _ManagedFiles()
    remote = _RemoteDevice()
    runtime = _Runtime()
    sessions: list[_Session] = []

    def open_session(device: object, required: frozenset[str]) -> _Session:
        del device
        session = _Session(files, remote, required)
        sessions.append(session)
        return session

    settings = BootstrapSettings(
        str(repository),
        state_root=str(state),
        session_opener=open_session,
        runtime_values=runtime,
        host_key_fingerprint=lambda device: "SHA256:synthetic-host-key",
    )
    outcomes: list[dict[str, object]] = []

    def execute(label: str, command: Command) -> object:
        application = bootstrap(settings)
        try:
            outcome = application.execute(command)
        except Exception as error:
            raise RuntimeError(f"synthetic command failed: {label}") from error
        outcomes.append(_outcome_record(label, command, outcome))
        return outcome

    observed = execute("observe.initial", ObserveCommand(str(repository), DEVICE_ID))
    if not isinstance(observed, ObservationOutcome):
        raise RuntimeError("synthetic observation did not produce a canonical Run")
    awaiting = execute(
        "reconcile.approval-required",
        ReconcileCommand(str(repository), DEVICE_ID, ()),
    )
    if getattr(awaiting, "execution_run_report", None) is not None:
        raise RuntimeError("approval-required reconcile unexpectedly executed")

    scenarios: list[dict[str, object]] = []
    desired_content: bytes | None = None
    for ordinal, scenario_input in enumerate(SCENARIO_INPUTS, start=1):
        name = scenario_input["id"]
        if name == "absent-create":
            files.discard(MANAGED_PATH)
            _write_desired(repository, "present")
        elif name == "formatting-noop":
            if desired_content is None:
                raise RuntimeError("desired content was not captured")
            files.put(
                MANAGED_PATH,
                _Entry(0o644, desired_content.replace(b"><", b">\n<")),
            )
        elif name == "semantic-drift":
            if desired_content is None:
                raise RuntimeError("desired content was not captured")
            files.put(
                MANAGED_PATH,
                _Entry(0o644, desired_content.replace(b"New Shows", b"Other Shows")),
            )
        elif name == "mode-drift":
            if desired_content is None:
                raise RuntimeError("desired content was not captured")
            files.put(MANAGED_PATH, _Entry(0o600, desired_content))
        elif name == "malformed-xml":
            files.put(MANAGED_PATH, _Entry(0o644, b"<smartplaylist>"))
        elif name == "explicit-removal":
            _write_desired(repository, "absent")
        elif name == "recreate-and-kodi":
            _write_desired(repository, "present")

        operation_start = len(files.operations)
        planned = execute(f"{name}.plan", PlanCommand(str(repository), DEVICE_ID))
        if not isinstance(planned, CanonicalPlanOutcome):
            raise RuntimeError(f"{name} did not produce a canonical Plan")
        plan_value = json.loads(planned.plan.canonical_bytes)
        changes = [
            change
            for resource in plan_value["resources"]
            for change in resource["changes"]
        ]
        change_id = (
            str(changes[0]["change_id"])
            if isinstance(changes, list) and changes
            else None
        )
        applied = None
        approval_scopes: tuple[str, ...] = ()
        if planned.disposition == "actionable":
            approval_scopes = tuple(
                str(item["scope"]) for item in plan_value["approval_requirements"]
            )
            applied = execute(
                f"{name}.apply",
                ApplyCommand(str(repository), planned.plan_id, approval_scopes),
            )
            run_id = getattr(applied, "run_id", None)
            if run_id is not None:
                execute(
                    f"{name}.report",
                    ReportCommand(str(repository), run_id),
                )
        verified = execute(f"{name}.verify", VerifyCommand(str(repository), DEVICE_ID))
        if not isinstance(verified, VerifyOutcome):
            raise RuntimeError(f"{name} did not produce a verification Run")
        entry = files.entries.get(MANAGED_PATH)
        if name == "absent-create" and entry is not None:
            desired_content = entry.content
        scenario_operations = files.operations[operation_start:]
        scenarios.append(
            {
                "ordinal": ordinal,
                "id": name,
                "desired": scenario_input["desired"],
                "setup": scenario_input["setup"],
                "plan_disposition": planned.disposition,
                "planning_run_id": planned.run_id.value,
                "plan_id": planned.plan_id.value,
                "execution_run_id": (
                    getattr(getattr(applied, "run_id", None), "value", None)
                ),
                "verification_run_id": getattr(verified.run_id, "value", None),
                "status": getattr(verified.status, "value", None),
                "operations": [
                    {
                        **dict(item),
                        "ordinal": operation_ordinal,
                        "resource_id": RESOURCE_ID,
                        "change_id": change_id,
                    }
                    for operation_ordinal, item in enumerate(
                        scenario_operations, start=1
                    )
                ],
                "final_presence": "present" if entry is not None else "absent",
                "final_mode": entry.mode if entry is not None else None,
                "final_content_sha256": (
                    _sha256(entry.content) if entry is not None else None
                ),
                "approval": (
                    list(approval_scopes) if name == "explicit-removal" else None
                ),
                "kodi_usability": (
                    "synthetic-operator-attestation-required"
                    if name == "recreate-and-kodi"
                    else None
                ),
            }
        )

    recovery_plan = execute("recovery.plan", PlanCommand(str(repository), DEVICE_ID))
    if not isinstance(recovery_plan, CanonicalPlanOutcome):
        raise RuntimeError("recovery setup did not produce a Plan")
    files.discard(MANAGED_PATH)
    recovery_plan = execute(
        "recovery.actionable-plan", PlanCommand(str(repository), DEVICE_ID)
    )
    if not isinstance(recovery_plan, CanonicalPlanOutcome):
        raise RuntimeError("recovery setup Plan is unavailable")
    files.lost_ack("atomic_replace", applied=False)
    files.fault("cleanup", MutationDisposition.AMBIGUOUS)
    interrupted = execute(
        "recovery.interrupted-apply",
        ApplyCommand(
            str(repository),
            recovery_plan.plan_id,
            tuple(
                str(item["scope"])
                for item in json.loads(recovery_plan.plan.canonical_bytes)[
                    "approval_requirements"
                ]
            ),
        ),
    )
    if not isinstance(interrupted, ApplyOutcome):
        raise RuntimeError("recovery setup did not produce an execution Run")
    inspection = execute(
        "recovery.inspect",
        RecoverCommand(str(repository), interrupted.run_id, "inspect"),
    )
    if not isinstance(inspection, RecoveryInspectionOutcome):
        raise RuntimeError("recovery inspection is unavailable")
    recovery_actions: list[dict[str, object]] = []
    for action in inspection.actions:
        recovery_actions.append(
            {
                "action": action.code.value,
                "mode": (
                    action.finalize_mode.value
                    if action.finalize_mode is not None
                    else None
                ),
                "allowed": action.allowed,
                "requires_approval": action.requires_approval,
                "requires_reason": action.requires_reason,
                "reason_code": action.reason_code,
            }
        )
    for rejected_action in ("resume_verification", "rollback"):
        try:
            bootstrap(settings).execute(
                RecoverCommand(
                    str(repository),
                    interrupted.run_id,
                    rejected_action,
                )
            )
        except ValueError:
            outcomes.append(
                {
                    "label": f"recovery.{rejected_action}.rejected",
                    "command": "RecoverCommand",
                    "outcome": "RecoveryActionRejected",
                    "exit_status": 2,
                    "status": "rejected",
                    "run_id": interrupted.run_id.value,
                    "plan_id": recovery_plan.plan_id.value,
                    "document_sha256": None,
                }
            )
        else:
            raise RuntimeError(
                f"unsafe recovery action was accepted: {rejected_action}"
            )
    final_entry = files.entries.get(MANAGED_PATH)
    execution = {
        "schema": SCHEMA,
        "mode": "executed-offline",
        "exit_status": 0,
        "device_contact": False,
        "secret_resolution": False,
        "scenario_inputs": {
            "device_id": DEVICE_ID.value,
            "resource_id": RESOURCE_ID,
            "logical_address": LOGICAL_ADDRESS,
            "scenarios": [dict(item) for item in SCENARIO_INPUTS],
        },
        "scenarios": scenarios,
        "outcomes": outcomes,
        "recovery": {
            "run_id": interrupted.run_id.value,
            "inspection_run_id": inspection.run_id.value,
            "actions": recovery_actions,
        },
        "sessions": [
            {
                "ordinal": index,
                "capabilities": sorted(session.required),
                "closed": session.closed,
            }
            for index, session in enumerate(sessions, start=1)
        ],
        "final_device_state": {
            "logical_address": LOGICAL_ADDRESS,
            "presence": "present" if final_entry is not None else "absent",
            "mode": final_entry.mode if final_entry is not None else None,
            "content_sha256": (
                _sha256(final_entry.content) if final_entry is not None else None
            ),
            "content_base64": (
                base64.b64encode(final_entry.content).decode("ascii")
                if final_entry is not None
                else None
            ),
        },
    }
    artifacts = _state_artifacts((("state", state),))
    artifact_documents = cast(list[dict[str, object]], artifacts["documents"])
    session_closes: list[dict[str, object]] = []
    for item in artifact_documents:
        content = item.get("content")
        if (
            isinstance(content, dict)
            and content.get("kind") == "CoreElecReconcilerSessionClose"
        ):
            session_closes.append(
                {
                    "artifact_id": item["artifact_id"],
                    "sha256": item["sha256"],
                    "record_id": content["record_id"],
                    "session_id": content["session_id"],
                }
            )
    execution["session_closes"] = session_closes
    return execution, artifacts


__all__ = ["SCENARIO_NAMES", "SCHEMA", "execute_dry_run"]
