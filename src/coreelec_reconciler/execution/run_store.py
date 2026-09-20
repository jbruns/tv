"""Fail-closed filesystem persistence for canonical Run revisions."""

import fcntl
import hashlib
import os
import secrets
import stat
from dataclasses import dataclass
from pathlib import Path

from coreelec_reconciler.domain.canonical_json import (
    canonical_document_bytes,
    decode_json_object,
)
from coreelec_reconciler.domain.execution import (
    TERMINAL_RUN_STATUSES,
    ActiveDeviceRun,
    AppendIntent,
    AttachmentRef,
    AuthorityPhase,
    DeviceIndexIntent,
    DeviceLease,
    ExecutionEvidenceKind,
    LoadedAttachment,
    RevisionLease,
    RunStatus,
    SealIntent,
    StoredRevision,
    VerifiedRunChain,
    WorkspaceId,
    decode_execution_evidence,
    evidence_proves_terminal_cleanup,
    execution_run_identity,
    is_post_terminal_cleanup_successor,
    validate_execution_evidence_sequence,
)
from coreelec_reconciler.domain.identifiers import DeviceId, RunId
from coreelec_reconciler.resource_types.builtins import built_in_resource_registry
from coreelec_reconciler.resource_types.registry import ResourceRegistry

from .local_durability import (
    AcknowledgementLost,
    DurabilityError,
    LocalDurability,
    PosixLocalDurability,
    read_regular_file,
)


class RunStoreError(RuntimeError):
    pass


class LeaseUnavailable(RunStoreError):
    pass


class CompareConflict(RunStoreError):
    pass


class CorruptRunStore(RunStoreError):
    pass


@dataclass(frozen=True, slots=True)
class OperationalReceipt:
    digest: str
    kind: str
    resource_id: str
    attachment: AttachmentRef
    payload: bytes


_IDENTITY_FIELDS = {
    "binding_digest",
    "boot_id",
    "created_at",
    "device_id",
    "kind",
    "originating_planning_run_id",
    "ownership_token_digest",
    "plan_full_digest",
    "plan_id",
    "producer",
    "run_id",
    "schema_version",
    "workspace_id",
}


class RunStore:
    """Filesystem RunStore whose public identities never expose local paths."""

    def __init__(
        self,
        root: Path,
        durability: LocalDurability | None = None,
        resource_registry: ResourceRegistry | None = None,
    ) -> None:
        self._root = root
        self._durability = durability or PosixLocalDurability()
        self._resource_registry = resource_registry or built_in_resource_registry()
        self._device_descriptors: dict[str, int] = {}
        self._run_descriptors: dict[str, int] = {}
        self._initialize()

    def _initialize(self) -> None:
        if self._root.exists() and (self._root.is_symlink() or not self._root.is_dir()):
            raise CorruptRunStore("RunStore root is unsafe")
        self._root.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self._root, 0o700)
        for name in ("device-leases", "device-index", "runs"):
            path = self._root / name
            if path.exists() and (path.is_symlink() or not path.is_dir()):
                raise CorruptRunStore("RunStore directory is unsafe")
            path.mkdir(mode=0o700, exist_ok=True)
            os.chmod(path, 0o700)

    def acquire_device(self, device_id: DeviceId) -> DeviceLease:
        key = _opaque_key(device_id.value)
        path = self._root / "device-leases" / f"{key}.lease"
        token, descriptor = self._acquire_lock(path)
        self._device_descriptors[token] = descriptor
        return DeviceLease(device_id, token)

    def release_device(self, lease: DeviceLease) -> None:
        self._release_lock(lease.token, self._device_descriptors)

    def acquire_run(self, run_id: RunId) -> RevisionLease:
        workspace = self._workspace_for_run(run_id)
        path = workspace / "lease"
        token, descriptor = self._acquire_lock(path)
        self._run_descriptors[token] = descriptor
        identity = self._read_object(workspace / "identity.json")
        return RevisionLease(
            run_id,
            WorkspaceId(_required_string(identity, "workspace_id")),
            token,
        )

    def release_run(self, lease: RevisionLease) -> None:
        self._release_lock(lease.token, self._run_descriptors)

    def create_run(
        self,
        device_lease: DeviceLease,
        run_id: RunId,
        device_id: DeviceId,
        ownership_token: bytes,
        ownership_token_digest: str,
        initial_payload: bytes,
    ) -> tuple[RevisionLease, WorkspaceId]:
        self._require_device_lease(device_lease, device_id)
        if _sha256(ownership_token) != ownership_token_digest:
            raise RunStoreError("ownership token digest mismatch")
        initial = self._validate_revision(initial_payload)
        initial_value = decode_json_object(initial_payload)
        try:
            initial_status = RunStatus(_required_string(initial_value, "status"))
        except ValueError as error:
            raise RunStoreError("initial Run status is unknown") from error
        authority = initial_value.get("authority")
        recovery = initial_value.get("recovery")
        if (
            not isinstance(authority, dict)
            or authority.get("ownership_token_digest") != ownership_token_digest
        ):
            raise RunStoreError("initial Run does not bind the ownership token")
        if (
            initial.revision != 1
            or _required_string(initial_value, "run_id") != run_id.value
        ):
            raise RunStoreError("initial Run revision must be revision 1")
        try:
            self._workspace_for_run(run_id)
        except FileNotFoundError:
            pass
        else:
            raise RunStoreError("Run already exists")

        workspace_id = WorkspaceId(f"workspace:{run_id.value}")
        if (
            not isinstance(recovery, dict)
            or recovery.get("workspace_id") != workspace_id.value
        ):
            raise RunStoreError("initial Run does not bind the workspace ID")
        directory = self._root / "runs" / _opaque_key(workspace_id.value)
        directory.mkdir(mode=0o700)
        os.chmod(directory, 0o700)
        for name in ("revisions", "attachments", "receipts"):
            child = directory / name
            child.mkdir(mode=0o700)
            os.chmod(child, 0o700)
        identity = execution_run_identity(initial_value)
        if (
            identity["device_id"] != device_id.value
            or identity["workspace_id"] != workspace_id.value
            or identity["ownership_token_digest"] != ownership_token_digest
        ):
            raise RunStoreError("initial Run immutable bindings are inconsistent")
        try:
            self._publish(
                directory / "identity.json",
                canonical_document_bytes(identity),
                "create-run-identity",
            )
            self._publish(
                directory / "ownership-token.bin",
                ownership_token,
                "create-run-token",
            )
            revision_path = directory / "revisions" / "00000001.json"
            self._publish(revision_path, initial_payload, "create-run-revision")
            self._publish(
                directory / "head.json",
                _head_bytes(initial),
                "create-run-head",
            )
            self._publish(
                directory / "state.json",
                canonical_document_bytes(
                    {
                        "authority_phase": AuthorityPhase.ACQUISITION_PENDING.value,
                        "status": initial_status.value,
                        "terminal": False,
                    }
                ),
                "create-run-state",
            )
            self._write_index(
                device_id,
                (
                    ActiveDeviceRun(
                        run_id,
                        workspace_id,
                        1,
                        initial.digest,
                        initial_status,
                        AuthorityPhase.ACQUISITION_PENDING,
                    ),
                ),
            )
        except Exception:
            self._remove_unpublished_workspace(directory)
            raise
        lease = self.acquire_run(run_id)
        return lease, workspace_id

    def load_chain(self, run_id: RunId) -> VerifiedRunChain:
        workspace = self._workspace_for_run(run_id)
        identity = self._read_object(workspace / "identity.json")
        if set(identity) != _IDENTITY_FIELDS:
            raise CorruptRunStore("workspace identity fields are incomplete")
        if _required_string(identity, "run_id") != run_id.value:
            raise CorruptRunStore("workspace identity does not match Run")
        head = self._read_object(workspace / "head.json")
        head_revision = _required_int(head, "revision")
        revisions: list[StoredRevision] = []
        previous_digest: str | None = None
        previous_value: dict[str, object] | None = None
        terminal_seen = False
        for number in range(1, head_revision + 1):
            path = workspace / "revisions" / f"{number:08d}.json"
            try:
                stored = self._validate_revision(self._read_bytes(path))
            except FileNotFoundError as error:
                raise CorruptRunStore("Run revision chain has a gap") from error
            value = decode_json_object(stored.payload)
            if stored.revision != number:
                raise CorruptRunStore("Run revision number mismatch")
            if _required_string(value, "run_id") != run_id.value:
                raise CorruptRunStore("Run revision identity mismatch")
            try:
                revision_identity = execution_run_identity(value)
            except ValueError as error:
                raise CorruptRunStore(
                    "Run immutable identity bindings are malformed"
                ) from error
            if revision_identity != identity:
                raise CorruptRunStore("Run immutable identity bindings changed")
            actual_previous = value.get("previous_revision_digest")
            if actual_previous != previous_digest:
                raise CorruptRunStore("Run revision chain digest mismatch")
            try:
                status = RunStatus(_required_string(value, "status"))
                evidence = value.get("evidence")
                if not isinstance(evidence, list):
                    raise ValueError("Run evidence is not an array")
                validate_execution_evidence_sequence(
                    tuple(evidence),
                    status=status,
                    resource_registry=self._resource_registry,
                )
            except (TypeError, ValueError) as error:
                raise CorruptRunStore("Run evidence chain is invalid") from error
            if terminal_seen and (
                previous_value is None
                or not is_post_terminal_cleanup_successor(
                    previous_value,
                    value,
                    resource_registry=self._resource_registry,
                )
            ):
                raise CorruptRunStore("terminal Run has an invalid successor")
            if status in TERMINAL_RUN_STATUSES and not evidence_proves_terminal_cleanup(
                value,
                resource_registry=self._resource_registry,
            ):
                raise CorruptRunStore("terminal Run summary is not evidence-backed")
            previous_digest = stored.digest
            previous_value = value
            terminal_seen = status in TERMINAL_RUN_STATUSES
            revisions.append(stored)
        if not revisions or (
            head.get("digest") != revisions[-1].digest
            or head_revision != revisions[-1].revision
        ):
            raise CorruptRunStore("Run head does not match revision chain")
        state = self._read_object(workspace / "state.json")
        terminal = _required_bool(state, "terminal")
        if terminal != terminal_seen:
            raise CorruptRunStore("Run terminal state does not match canonical head")
        return VerifiedRunChain(tuple(revisions), revisions[-1], terminal)

    def load_identity(self, run_id: RunId) -> dict[str, object]:
        workspace = self._workspace_for_run(run_id)
        identity = self._read_object(workspace / "identity.json")
        if set(identity) != _IDENTITY_FIELDS:
            raise CorruptRunStore("workspace identity fields are incomplete")
        if _required_string(identity, "run_id") != run_id.value:
            raise CorruptRunStore("workspace identity does not match Run")
        try:
            token = self._read_bytes(workspace / "ownership-token.bin")
        except FileNotFoundError as error:
            raise CorruptRunStore("ownership token is absent") from error
        if _sha256(token) != identity.get("ownership_token_digest"):
            raise CorruptRunStore("ownership token verification failed")
        return identity

    def compare_and_append(
        self,
        lease: RevisionLease,
        expected_revision: int,
        expected_digest: str,
        payload: bytes,
        intent: AppendIntent,
    ) -> StoredRevision:
        self._require_run_lease(lease)
        chain = self.load_chain(lease.run_id)
        if (
            chain.head.revision != expected_revision
            or chain.head.digest != expected_digest
        ):
            raise CompareConflict("Run head changed")
        proposed = self._validate_revision(payload)
        value = decode_json_object(payload)
        if (
            proposed.revision != expected_revision + 1
            or value.get("previous_revision_digest") != expected_digest
            or value.get("run_id") != lease.run_id.value
        ):
            raise RunStoreError("proposed revision does not extend current head")
        if intent.terminal != (intent.next_status in TERMINAL_RUN_STATUSES):
            raise RunStoreError("append terminal intent does not match status")
        if value.get("status") != intent.next_status.value:
            raise RunStoreError("append status intent does not match payload")
        if execution_run_identity(value) != execution_run_identity(
            decode_json_object(chain.head.payload)
        ):
            raise RunStoreError("Run immutable identity bindings changed")
        if chain.terminal and not is_post_terminal_cleanup_successor(
            decode_json_object(chain.head.payload),
            value,
            resource_registry=self._resource_registry,
        ):
            raise CompareConflict("terminal Run only accepts cleanup receipts")
        try:
            return self._complete_append(
                lease,
                expected_revision,
                expected_digest,
                proposed,
                intent,
            )
        except AcknowledgementLost:
            try:
                return self._complete_append(
                    lease,
                    expected_revision,
                    expected_digest,
                    proposed,
                    intent,
                )
            except AcknowledgementLost as retry_error:
                raise CompareConflict(
                    "append acknowledgement reconciliation was lost twice"
                ) from retry_error
            except (CompareConflict, CorruptRunStore) as retry_error:
                raise CompareConflict(
                    "append acknowledgement reconciliation failed"
                ) from retry_error

    def _complete_append(
        self,
        lease: RevisionLease,
        expected_revision: int,
        expected_digest: str,
        proposed: StoredRevision,
        intent: AppendIntent,
    ) -> StoredRevision:
        workspace = self._workspace_for_run(lease.run_id)
        chain = self.load_chain(lease.run_id)
        if chain.head.payload == proposed.payload:
            pass
        elif (
            chain.head.revision == expected_revision
            and chain.head.digest == expected_digest
        ):
            revision_path = workspace / "revisions" / f"{proposed.revision:08d}.json"
            try:
                existing = self._read_bytes(revision_path)
            except FileNotFoundError:
                self._publish(
                    revision_path,
                    proposed.payload,
                    f"append-revision-{proposed.revision}",
                )
            else:
                if existing != proposed.payload:
                    raise CompareConflict("different successor revision already exists")
            self._publish(
                workspace / "head.json",
                _head_bytes(proposed),
                f"append-head-{proposed.revision}",
            )
        else:
            raise CompareConflict("Run head changed during append")

        phase = intent.authority_phase
        if (
            intent.device_index is DeviceIndexIntent.ADD_OR_RETAIN_ACTIVE
            and phase is None
        ):
            raise RunStoreError("active index intent requires authority phase")
        old_state = self._read_object(workspace / "state.json")
        old_phase = old_state.get("authority_phase")
        self._publish(
            workspace / "state.json",
            canonical_document_bytes(
                {
                    "authority_phase": phase.value if phase is not None else old_phase,
                    "status": intent.next_status.value,
                    "terminal": intent.terminal,
                }
            ),
            f"append-state-{proposed.revision}",
        )
        self._apply_index_intent(lease, proposed, intent)
        self._durability.acknowledge(
            f"compare-and-append:{lease.run_id.value}:{proposed.revision}"
        )
        completed = self.load_chain(lease.run_id)
        if completed.head != proposed:
            raise CorruptRunStore("append did not durably advance the Run head")
        if intent.device_index is DeviceIndexIntent.ADD_OR_RETAIN_ACTIVE:
            identity = self._read_object(workspace / "identity.json")
            active = self.find_active_by_device(
                DeviceId(_required_string(identity, "device_id"))
            )
            if not any(
                entry.run_id == lease.run_id
                and entry.revision == proposed.revision
                and entry.revision_digest == proposed.digest
                and entry.status is intent.next_status
                and entry.authority_phase is phase
                for entry in active
            ):
                raise CorruptRunStore("append did not durably reconcile the index")
        return proposed

    def attach(
        self,
        lease: RevisionLease,
        kind: str,
        codec: str,
        payload: bytes,
    ) -> AttachmentRef:
        self._require_run_lease(lease)
        _require_safe_code(kind, "attachment kind")
        _require_safe_code(codec, "attachment codec")
        digest = _sha256(payload)
        reference = AttachmentRef(digest, kind, codec)
        workspace = self._workspace_for_run(lease.run_id)
        digest_hex = digest.removeprefix("sha256:")
        path = workspace / "attachments" / digest_hex
        metadata_path = workspace / "attachments" / f"{digest_hex}.json"
        metadata = canonical_document_bytes(
            {"codec": codec, "digest": digest, "kind": kind}
        )
        try:
            existing_payload = self._read_bytes(path)
        except FileNotFoundError:
            pass
        else:
            if (
                existing_payload != payload
                or self._read_bytes(metadata_path) != metadata
            ):
                raise CorruptRunStore("content-addressed attachment mismatch")
            return reference
        self._publish(path, payload, f"attach:{digest}")
        self._publish(metadata_path, metadata, f"attach-metadata:{digest}")
        return reference

    def read_attachment(
        self,
        lease: RevisionLease,
        reference: AttachmentRef,
    ) -> LoadedAttachment:
        self._require_run_lease(lease)
        return self._read_attachment(lease.run_id, reference)

    def _read_attachment(
        self,
        run_id: RunId,
        reference: AttachmentRef,
    ) -> LoadedAttachment:
        workspace = self._workspace_for_run(run_id)
        digest_hex = reference.digest.removeprefix("sha256:")
        path = workspace / "attachments" / digest_hex
        metadata = self._read_object(workspace / "attachments" / f"{digest_hex}.json")
        expected = {
            "codec": reference.codec,
            "digest": reference.digest,
            "kind": reference.kind,
        }
        payload = self._read_bytes(path)
        if metadata != expected or _sha256(payload) != reference.digest:
            raise CorruptRunStore("attachment verification failed")
        return LoadedAttachment(reference, payload)

    def record_operational_receipt(
        self,
        lease: RevisionLease,
        kind: str,
        resource_id: str,
        payload: bytes,
    ) -> str:
        """Persist post-terminal operational evidence without revising truth."""
        self._require_run_lease(lease)
        _require_safe_code(kind, "receipt kind")
        _require_safe_code(resource_id, "receipt Resource ID")
        attachment = self.attach(lease, kind, f"{kind}-v1", payload)
        receipt = canonical_document_bytes(
            {
                "attachment": {
                    "codec": attachment.codec,
                    "digest": attachment.digest,
                    "kind": attachment.kind,
                },
                "kind": kind,
                "resource_id": resource_id,
                "schema_version": 1,
            }
        )
        digest = _sha256(receipt)
        directory = self._workspace_for_run(lease.run_id) / "receipts"
        directory.mkdir(mode=0o700, exist_ok=True)
        os.chmod(directory, 0o700)
        self._publish(
            directory / f"{digest.removeprefix('sha256:')}.json",
            receipt,
            f"receipt:{digest}",
        )
        return digest

    def record_corrupt_recovery_evidence(
        self,
        lease: RevisionLease,
        value: dict[str, object],
    ) -> StoredRevision:
        """Persist a closed abandonment/quarantine record beside a corrupt chain."""
        self._require_run_lease(lease)
        try:
            record = decode_execution_evidence(
                value,
                resource_registry=self._resource_registry,
            )
        except ValueError as error:
            raise RunStoreError("corrupt recovery evidence is invalid") from error
        if record.kind not in {
            ExecutionEvidenceKind.RUN_ABANDONMENT_APPROVAL,
            ExecutionEvidenceKind.AUTHORITY_EVIDENCE,
        }:
            raise RunStoreError("corrupt recovery evidence kind is not allowed")
        identity = self.load_identity(lease.run_id)
        if (
            record.bindings.run_id != lease.run_id.value
            or record.bindings.workspace_id != lease.workspace_id.value
            or record.bindings.device_id != identity["device_id"]
            or record.bindings.plan_id != identity["plan_id"]
            or record.bindings.plan_full_digest != identity["plan_full_digest"]
            or record.bindings.binding_digest != identity["binding_digest"]
        ):
            raise RunStoreError("corrupt recovery evidence binding changed")
        payload = canonical_document_bytes(value)
        digest = _sha256(payload)
        directory = self._workspace_for_run(lease.run_id) / "receipts"
        directory.mkdir(mode=0o700, exist_ok=True)
        os.chmod(directory, 0o700)
        path = directory / f"{record.kind.value}.{digest.removeprefix('sha256:')}.json"
        self._publish(path, payload, f"corrupt-recovery:{record.kind.value}")
        return StoredRevision(0, digest, payload)

    def seal_corrupt_quarantine(
        self,
        lease: RevisionLease,
        abandonment_digest: str,
        quarantine_digest: str,
    ) -> None:
        """Seal a corrupt Run only after typed abandonment and quarantine receipts."""
        self._require_run_lease(lease)
        workspace = self._workspace_for_run(lease.run_id)
        receipts = workspace / "receipts"
        expected = {
            ExecutionEvidenceKind.RUN_ABANDONMENT_APPROVAL: abandonment_digest,
            ExecutionEvidenceKind.AUTHORITY_EVIDENCE: quarantine_digest,
        }
        for kind, digest in expected.items():
            path = receipts / f"{kind.value}.{digest.removeprefix('sha256:')}.json"
            value = decode_json_object(self._read_bytes(path))
            record = decode_execution_evidence(
                value,
                resource_registry=self._resource_registry,
            )
            if (
                record.kind is not kind
                or _sha256(canonical_document_bytes(value)) != digest
            ):
                raise RunStoreError("corrupt recovery receipt verification failed")
        identity = self.load_identity(lease.run_id)
        self._publish(
            workspace / "seal.json",
            canonical_document_bytes(
                {
                    "ownership_released_or_quarantined": True,
                    "terminal_digest": abandonment_digest,
                    "terminal_revision": 0,
                }
            ),
            "seal-corrupt-quarantine",
        )
        self._publish(
            workspace / "state.json",
            canonical_document_bytes(
                {
                    "authority_phase": AuthorityPhase.RELEASE_PENDING.value,
                    "status": RunStatus.FAILED_RECOVERY_REQUIRED.value,
                    "terminal": True,
                }
            ),
            "state-corrupt-quarantine",
        )
        self._remove_index_entry(
            DeviceId(_required_string(identity, "device_id")),
            lease.run_id,
        )

    def load_operational_receipts(
        self,
        run_id: RunId,
        kind: str,
    ) -> tuple[OperationalReceipt, ...]:
        _require_safe_code(kind, "receipt kind")
        directory = self._workspace_for_run(run_id) / "receipts"
        if not directory.exists():
            return ()
        receipts: list[OperationalReceipt] = []
        for path in sorted(directory.iterdir()):
            receipt_bytes = self._read_bytes(path)
            if _sha256(receipt_bytes) != "sha256:" + path.stem:
                raise CorruptRunStore("operational receipt digest mismatch")
            try:
                value = decode_json_object(receipt_bytes)
            except ValueError as error:
                raise CorruptRunStore("operational receipt is malformed") from error
            if set(value) != {
                "attachment",
                "kind",
                "resource_id",
                "schema_version",
            }:
                raise CorruptRunStore("operational receipt is malformed")
            if value["kind"] != kind or value["schema_version"] != 1:
                continue
            attachment = value["attachment"]
            if not isinstance(attachment, dict):
                raise CorruptRunStore("operational receipt attachment is malformed")
            reference = AttachmentRef(
                _required_string(attachment, "digest"),
                _required_string(attachment, "kind"),
                _required_string(attachment, "codec"),
            )
            loaded = self._read_attachment(run_id, reference)
            receipts.append(
                OperationalReceipt(
                    "sha256:" + path.stem,
                    kind,
                    _required_string(value, "resource_id"),
                    reference,
                    loaded.payload,
                )
            )
        return tuple(receipts)

    def load_ownership_token(self, lease: RevisionLease) -> bytes:
        self._require_run_lease(lease)
        workspace = self._workspace_for_run(lease.run_id)
        identity = self._read_object(workspace / "identity.json")
        try:
            token = self._read_bytes(workspace / "ownership-token.bin")
        except FileNotFoundError as error:
            raise CorruptRunStore("ownership token is absent") from error
        if _sha256(token) != identity.get("ownership_token_digest"):
            raise CorruptRunStore("ownership token verification failed")
        return token

    def finalize_and_seal(
        self,
        lease: RevisionLease,
        intent: SealIntent,
    ) -> StoredRevision:
        self._require_run_lease(lease)
        chain = self.load_chain(lease.run_id)
        if not chain.terminal or chain.head.revision != intent.terminal_revision:
            raise RunStoreError("seal requires the durable terminal head")
        head_value = decode_json_object(chain.head.payload)
        cleanup = head_value.get("cleanup")
        authority = head_value.get("authority")
        ownership_state = (
            authority.get("ownership_state") if isinstance(authority, dict) else None
        )
        cleanup_allows_seal = isinstance(cleanup, dict) and (
            (
                ownership_state == "released"
                and cleanup.get("state") == "complete"
                and cleanup.get("leftover_count") == 0
            )
            or ownership_state == "quarantined"
        )
        if (
            not cleanup_allows_seal
            or not isinstance(authority, dict)
            or ownership_state not in {"released", "quarantined"}
            or authority.get("device_index_intent")
            != "remove_after_release_or_quarantine"
            or not intent.ownership_released_or_quarantined
            or not evidence_proves_terminal_cleanup(
                head_value,
                resource_registry=self._resource_registry,
            )
        ):
            raise RunStoreError(
                "seal requires completed cleanup for release or quarantine truth"
            )
        workspace = self._workspace_for_run(lease.run_id)
        identity = self._read_object(workspace / "identity.json")
        seal = {
            "ownership_released_or_quarantined": (
                intent.ownership_released_or_quarantined
            ),
            "terminal_digest": chain.head.digest,
            "terminal_revision": chain.head.revision,
        }
        self._publish(
            workspace / "seal.json",
            canonical_document_bytes(seal),
            f"seal:{lease.run_id.value}",
        )
        if intent.ownership_released_or_quarantined:
            self._remove_index_entry(
                DeviceId(_required_string(identity, "device_id")),
                lease.run_id,
            )
        return chain.head

    def find_active_by_device(
        self,
        device_id: DeviceId,
    ) -> tuple[ActiveDeviceRun, ...]:
        scanned = self._scan_active(device_id)
        cached = self._read_index(device_id)
        if cached != scanned:
            raise CorruptRunStore(
                "active Device index disagrees with verified workspace scan"
            )
        return scanned

    def rebuild_active_device_index(self) -> tuple[ActiveDeviceRun, ...]:
        by_device: dict[str, list[ActiveDeviceRun]] = {}
        for directory in self._workspace_directories():
            identity = self._read_object(directory / "identity.json")
            device_id = DeviceId(_required_string(identity, "device_id"))
            active = self._active_from_workspace(directory)
            if active is not None:
                by_device.setdefault(device_id.value, []).append(active)
        index_directory = self._root / "device-index"
        expected_paths = {
            self._index_path(DeviceId(device_id)) for device_id in by_device
        }
        for existing in index_directory.iterdir():
            if existing.is_symlink() or not existing.is_file():
                raise CorruptRunStore("active Device index contains unsafe object")
            if existing not in expected_paths:
                existing.unlink()
        all_entries: list[ActiveDeviceRun] = []
        for value, entries in sorted(by_device.items()):
            ordered = tuple(sorted(entries, key=lambda item: item.run_id.value))
            self._write_index(DeviceId(value), ordered)
            all_entries.extend(ordered)
        self._durability.sync_directory(str(index_directory))
        return tuple(sorted(all_entries, key=lambda item: item.run_id.value))

    def _scan_active(self, device_id: DeviceId) -> tuple[ActiveDeviceRun, ...]:
        entries = []
        for directory in self._workspace_directories():
            identity = self._read_object(directory / "identity.json")
            if identity.get("device_id") != device_id.value:
                continue
            active = self._active_from_workspace(directory)
            if active is not None:
                entries.append(active)
        return tuple(sorted(entries, key=lambda item: item.run_id.value))

    def _active_from_workspace(self, directory: Path) -> ActiveDeviceRun | None:
        identity = self._read_object(directory / "identity.json")
        state = self._read_object(directory / "state.json")
        terminal = _required_bool(state, "terminal")
        seal_path = directory / "seal.json"
        if terminal and seal_path.exists():
            seal = self._read_object(seal_path)
            if seal.get("ownership_released_or_quarantined") is True:
                return None
        phase_value = state.get("authority_phase")
        if phase_value is None:
            return None
        try:
            if not isinstance(phase_value, str):
                raise CorruptRunStore("workspace authority phase is invalid")
            phase = AuthorityPhase(phase_value)
            status = RunStatus(_required_string(state, "status"))
        except ValueError as error:
            raise CorruptRunStore("unknown workspace state") from error
        run_id = RunId(_required_string(identity, "run_id"))
        chain = self.load_chain(run_id)
        return ActiveDeviceRun(
            run_id,
            WorkspaceId(_required_string(identity, "workspace_id")),
            chain.head.revision,
            chain.head.digest,
            status,
            phase,
        )

    def _apply_index_intent(
        self,
        lease: RevisionLease,
        revision: StoredRevision,
        intent: AppendIntent,
    ) -> None:
        workspace = self._workspace_for_run(lease.run_id)
        identity = self._read_object(workspace / "identity.json")
        device_id = DeviceId(_required_string(identity, "device_id"))
        if intent.device_index is DeviceIndexIntent.NO_CHANGE:
            return
        if intent.device_index is DeviceIndexIntent.REMOVE_AFTER_RELEASE_OR_QUARANTINE:
            raise RunStoreError("active index removal requires explicit seal")
        current = [
            entry
            for entry in self._read_index(device_id)
            if entry.run_id != lease.run_id
        ]
        if intent.authority_phase is None:
            raise RunStoreError("authority phase is required")
        current.append(
            ActiveDeviceRun(
                lease.run_id,
                lease.workspace_id,
                revision.revision,
                revision.digest,
                intent.next_status,
                intent.authority_phase,
            )
        )
        self._write_index(
            device_id,
            tuple(sorted(current, key=lambda item: item.run_id.value)),
        )

    def _remove_index_entry(self, device_id: DeviceId, run_id: RunId) -> None:
        entries = tuple(
            entry for entry in self._read_index(device_id) if entry.run_id != run_id
        )
        self._write_index(device_id, entries)

    def _read_index(self, device_id: DeviceId) -> tuple[ActiveDeviceRun, ...]:
        path = self._index_path(device_id)
        if not path.exists():
            return ()
        value = self._read_object(path)
        if set(value) != {"device_id", "entries", "schema_version"}:
            raise CorruptRunStore("active Device index shape is invalid")
        if value["schema_version"] != 1 or value["device_id"] != device_id.value:
            raise CorruptRunStore("active Device index identity is invalid")
        raw_entries = value["entries"]
        if not isinstance(raw_entries, list):
            raise CorruptRunStore("active Device index entries are invalid")
        entries = []
        for raw in raw_entries:
            if not isinstance(raw, dict) or set(raw) != {
                "authority_phase",
                "revision",
                "revision_digest",
                "run_id",
                "status",
                "workspace_id",
            }:
                raise CorruptRunStore("active Device index entry is invalid")
            try:
                entries.append(
                    ActiveDeviceRun(
                        RunId(_required_string(raw, "run_id")),
                        WorkspaceId(_required_string(raw, "workspace_id")),
                        _required_int(raw, "revision"),
                        _required_string(raw, "revision_digest"),
                        RunStatus(_required_string(raw, "status")),
                        AuthorityPhase(_required_string(raw, "authority_phase")),
                    )
                )
            except ValueError as error:
                raise CorruptRunStore("active Device index code is invalid") from error
        if entries != sorted(entries, key=lambda item: item.run_id.value):
            raise CorruptRunStore("active Device index is not ordered")
        return tuple(entries)

    def _write_index(
        self,
        device_id: DeviceId,
        entries: tuple[ActiveDeviceRun, ...],
    ) -> None:
        value = {
            "device_id": device_id.value,
            "entries": [
                {
                    "authority_phase": entry.authority_phase.value,
                    "revision": entry.revision,
                    "revision_digest": entry.revision_digest,
                    "run_id": entry.run_id.value,
                    "status": entry.status.value,
                    "workspace_id": entry.workspace_id.value,
                }
                for entry in entries
            ],
            "schema_version": 1,
        }
        self._publish(
            self._index_path(device_id),
            canonical_document_bytes(value),
            f"index:{_opaque_key(device_id.value)}",
        )

    def _index_path(self, device_id: DeviceId) -> Path:
        return self._root / "device-index" / f"{_opaque_key(device_id.value)}.json"

    def _workspace_for_run(self, run_id: RunId) -> Path:
        found: list[Path] = []
        for directory in self._workspace_directories():
            identity = self._read_object(directory / "identity.json")
            if identity.get("run_id") == run_id.value:
                found.append(directory)
        if not found:
            raise FileNotFoundError("Run workspace not found")
        if len(found) != 1:
            raise CorruptRunStore("multiple workspaces claim one Run")
        return found[0]

    def _workspace_directories(self) -> tuple[Path, ...]:
        result = []
        for path in (self._root / "runs").iterdir():
            if path.is_symlink() or not path.is_dir():
                raise CorruptRunStore("unsafe object in Run workspace root")
            result.append(path)
        return tuple(sorted(result))

    def _validate_revision(self, payload: bytes) -> StoredRevision:
        try:
            value = decode_json_object(payload)
        except ValueError as error:
            raise CorruptRunStore("Run revision is not valid JSON") from error
        if canonical_document_bytes(value) != payload:
            raise CorruptRunStore("Run revision is not canonical")
        revision = _required_int(value, "revision")
        digest = _required_string(value, "current_digest")
        without_digest = dict(value)
        without_digest.pop("current_digest", None)
        if digest != _sha256(canonical_document_bytes(without_digest)):
            raise CorruptRunStore("Run revision digest mismatch")
        try:
            status = RunStatus(_required_string(value, "status"))
            evidence = value.get("evidence")
            if not isinstance(evidence, list):
                raise ValueError("Run evidence is not an array")
            validate_execution_evidence_sequence(
                tuple(evidence),
                status=status,
                resource_registry=self._resource_registry,
            )
            if status in TERMINAL_RUN_STATUSES and not evidence_proves_terminal_cleanup(
                value,
                resource_registry=self._resource_registry,
            ):
                raise ValueError("terminal summary is not evidence-backed")
        except (TypeError, ValueError) as error:
            raise CorruptRunStore("Run evidence is invalid") from error
        return StoredRevision(revision, digest, payload)

    def _publish(self, path: Path, payload: bytes, operation_id: str) -> None:
        temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
        try:
            try:
                self._durability.write_private(str(temporary), payload)
            except AcknowledgementLost:
                if not self._matches_payload(temporary, payload):
                    raise
            try:
                self._durability.full_sync_file(str(temporary))
            except AcknowledgementLost:
                if not self._matches_payload(temporary, payload):
                    raise
            try:
                self._durability.atomic_replace(str(temporary), str(path))
            except AcknowledgementLost:
                if not self._matches_payload(path, payload):
                    raise
            try:
                self._durability.sync_directory(str(path.parent))
            except AcknowledgementLost:
                if not self._matches_payload(path, payload):
                    raise
            if self._read_bytes(path) != payload:
                raise CorruptRunStore("published bytes failed verification")
            self._durability.acknowledge(operation_id)
        finally:
            if temporary.exists():
                temporary.unlink()

    def _read_object(self, path: Path) -> dict[str, object]:
        try:
            return decode_json_object(self._read_bytes(path))
        except (DurabilityError, FileNotFoundError, ValueError) as error:
            raise CorruptRunStore("RunStore object is malformed") from error

    def _read_bytes(self, path: Path) -> bytes:
        try:
            return read_regular_file(path)
        except FileNotFoundError:
            raise
        except DurabilityError as error:
            raise CorruptRunStore("RunStore object is unsafe") from error

    def _matches_payload(self, path: Path, payload: bytes) -> bool:
        try:
            return self._read_bytes(path) == payload
        except FileNotFoundError, CorruptRunStore:
            return False

    def _acquire_lock(self, path: Path) -> tuple[str, int]:
        if path.exists() and (
            path.is_symlink() or not stat.S_ISREG(path.lstat().st_mode)
        ):
            raise CorruptRunStore("lease object is unsafe")
        flags = os.O_RDWR | os.O_CREAT
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(path, flags, 0o600)
        os.fchmod(descriptor, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            os.close(descriptor)
            raise LeaseUnavailable("lease is already held") from error
        token = secrets.token_hex(32)
        os.ftruncate(descriptor, 0)
        os.write(descriptor, token.encode("ascii"))
        os.fsync(descriptor)
        return token, descriptor

    def _release_lock(self, token: str, held: dict[str, int]) -> None:
        descriptor = held.pop(token, None)
        if descriptor is None:
            raise LeaseUnavailable("lease is not held by this RunStore")
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)

    def _require_device_lease(
        self,
        lease: DeviceLease,
        device_id: DeviceId,
    ) -> None:
        if lease.device_id != device_id or lease.token not in self._device_descriptors:
            raise LeaseUnavailable("valid Device lease required")

    def _require_run_lease(self, lease: RevisionLease) -> None:
        if lease.token not in self._run_descriptors:
            raise LeaseUnavailable("valid Run revision lease required")
        workspace = self._workspace_for_run(lease.run_id)
        identity = self._read_object(workspace / "identity.json")
        if identity.get("workspace_id") != lease.workspace_id.value:
            raise LeaseUnavailable("Run lease workspace mismatch")

    def _remove_unpublished_workspace(self, directory: Path) -> None:
        if not directory.exists():
            return
        for path in sorted(directory.rglob("*"), reverse=True):
            if path.is_file():
                path.unlink()
            elif path.is_dir():
                path.rmdir()
        directory.rmdir()


def _sha256(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _opaque_key(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _head_bytes(revision: StoredRevision) -> bytes:
    return canonical_document_bytes(
        {"digest": revision.digest, "revision": revision.revision}
    )


def _required_string(value: dict[str, object], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise CorruptRunStore(f"{key} must be a nonempty string")
    return item


def _required_int(value: dict[str, object], key: str) -> int:
    item = value.get(key)
    if type(item) is not int or item < 1:
        raise CorruptRunStore(f"{key} must be a positive integer")
    return item


def _required_bool(value: dict[str, object], key: str) -> bool:
    item = value.get(key)
    if type(item) is not bool:
        raise CorruptRunStore(f"{key} must be a boolean")
    return item


def _require_safe_code(value: str, label: str) -> None:
    if (
        not value
        or len(value) > 128
        or any(
            character not in "abcdefghijklmnopqrstuvwxyz0123456789._-"
            for character in value
        )
    ):
        raise RunStoreError(f"{label} is invalid")
