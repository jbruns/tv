import hashlib
import os
from copy import deepcopy
from dataclasses import dataclass, replace
from pathlib import Path
from typing import cast

import pytest

from coreelec_reconciler.application.commands import ApplyCommand, ReportCommand
from coreelec_reconciler.application.outcomes import ApplyOutcome, ReportOutcome
from coreelec_reconciler.application.reconciler import (
    ApplicationData,
    ExecutionApplicationWorkflows,
)
from coreelec_reconciler.domain.configuration import Resource
from coreelec_reconciler.domain.execution import (
    CleanupMutationIntent,
    FinalizeMode,
    MarkerCheckpoint,
    MutationDisposition,
    MutationReceipt,
    MutationTrace,
    NormalizedResourceState,
    Presence,
    PrimitiveKind,
    RecoveryActionCode,
    RemoteMarkerPhase,
    RemoteOwnership,
    RemoteOwnershipIdentity,
    RemoteOwnershipSnapshot,
    RemoteQuarantine,
    RunStatus,
    WorkspaceId,
)
from coreelec_reconciler.domain.identifiers import DeviceId, PlanId, RunId
from coreelec_reconciler.domain.planning import (
    CanonicalPlan,
    CanonicalRunReport,
)
from coreelec_reconciler.execution.authority import (
    AcquiredAuthority,
    AuthorityCoordinator,
)
from coreelec_reconciler.execution.composition import (
    ApprovalGrant,
    DeviceAuthorityObservation,
    ProductionExecutionFactory,
    RunStoreExecutionFinalizer,
    SavedPlanExecutionRequest,
)
from coreelec_reconciler.execution.engine import (
    ApprovedPlan,
    ExecutableChange,
    ExecutionEngine,
    M3AuthorityRecovery,
    RecoveryAuthority,
    RecoveryCoordinator,
    RecoveryDriver,
)
from coreelec_reconciler.execution.local_durability import DurabilityError
from coreelec_reconciler.execution.plan_store import PlanStore
from coreelec_reconciler.execution.recovery import inspect_recovery
from coreelec_reconciler.execution.run_adapters import (
    RecoveryEnvironment,
    RemoteOwnershipReader,
    ResourceContextProvider,
    ResourceContextProviderFactory,
    RunClock,
    RunStoreBoundAuthorityState,
    RunStoreExecutionPersistence,
)
from coreelec_reconciler.execution.run_store import RunStore
from coreelec_reconciler.reporting.canonical_json import (
    canonical_document_bytes,
    decode_json_object,
)
from coreelec_reconciler.reporting.execution_documents import (
    build_execution_run_report,
    decode_execution_run_report,
)
from coreelec_reconciler.reporting.planning_documents import (
    decode_plan,
    decode_run_report,
)
from coreelec_reconciler.resource_types.descriptor import (
    AttachmentStore,
    ErasedResourceExecution,
    ManagedFileCapabilities,
    ManagedFileExecutionResult,
    ManagedFileLifecycle,
    ManagedFileVerification,
    ManagedFileVerificationStatus,
    ResourceDescriptor,
    ResourceExecutionContext,
)
from coreelec_reconciler.resource_types.kodi_smart_playlist.codecs import (
    decode_intent,
    encode_intent,
)
from coreelec_reconciler.resource_types.kodi_smart_playlist.intent import (
    parse_intent,
)
from coreelec_reconciler.resource_types.kodi_smart_playlist.planning_codecs import (
    decode_plan_evidence,
)
from coreelec_reconciler.resource_types.kodi_smart_playlist.resource_type import (
    state_addresses,
)
from coreelec_reconciler.resource_types.managed_file.observation import (
    ManagedFileObservation,
)
from coreelec_reconciler.resource_types.managed_file.paths import (
    ManagedPath,
    ResolvedManagedAddress,
)
from coreelec_reconciler.resource_types.managed_file.preparation import (
    PreparationBinding,
    PreparationObject,
    PreparedManagedFile,
    decode_prepared_managed_file,
    prepare_managed_file,
)
from coreelec_reconciler.resource_types.registry import ResourceRegistry
from tests.fakes.runtime import FakeManagedFiles
from tests.unit.execution.test_execution_documents import (
    RUN_ID,
    run_value,
    unchecked_run_bytes,
)

FIXTURES = Path(__file__).parents[2] / "fixtures" / "canonical"


@pytest.fixture(autouse=True)
def _avoid_physical_fsync(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os, "fsync", lambda _fd: None)


class _Clock:
    def __init__(self, now: str = "2026-09-19T08:02:00Z") -> None:
        self.now = now

    def utc_now(self) -> str:
        return self.now


class _DeviceAuthority:
    def __init__(
        self,
        device: dict[str, object],
        *,
        binding_digest: str | None = None,
        boot_id: str = "boot.opaque",
        platform_identity: str | None = None,
        host_key: str | None = None,
        second: DeviceAuthorityObservation | None = None,
    ) -> None:
        self.observation = DeviceAuthorityObservation(
            DeviceId(cast(str, device["logical_id"])),
            binding_digest
            or (
                "sha256:" + hashlib.sha256(canonical_document_bytes(device)).hexdigest()
            ),
            boot_id,
            platform_identity
            or cast(str, device["observed_platform_identity_fingerprint"]),
            host_key or cast(str, device["ssh_host_key_fingerprint"]),
        )
        self.second = second
        self.calls = 0

    def observe_authority(self, device_id: DeviceId) -> DeviceAuthorityObservation:
        self.calls += 1
        if self.calls == 2 and self.second is not None:
            return self.second
        return self.observation


class _FinalizerAuthority:
    def __init__(self) -> None:
        self.releases: list[tuple[RunId, str]] = []

    def release(self, run_id: RunId, terminal_digest: str) -> MutationReceipt:
        self.releases.append((run_id, terminal_digest))
        return MutationReceipt("release", MutationDisposition.APPLIED)

    def quarantine(self, run_id: RunId) -> MutationReceipt:
        raise AssertionError("normal completion must not quarantine")


class _AcquiringAuthority:
    def __init__(self, store: RunStore) -> None:
        self.store = store
        self.calls = 0

    def acquire(self, request: object) -> AcquiredAuthority:
        from coreelec_reconciler.execution.authority import AuthorityAcquisitionRequest

        assert isinstance(request, AuthorityAcquisitionRequest)
        self.calls += 1
        device_lease = self.store.acquire_device(request.device_id)
        token = b"production-token"
        token_digest = "sha256:" + hashlib.sha256(token).hexdigest()
        revision_lease, workspace_id = self.store.create_run(
            device_lease,
            request.run_id,
            request.device_id,
            token,
            token_digest,
            request.initial_revision(token_digest),
        )
        identity = request.identity(workspace_id)
        return AcquiredAuthority(
            device_lease,
            revision_lease,
            workspace_id,
            RemoteOwnership(
                identity,
                token_digest,
                1,
                RemoteMarkerPhase.ACQUIRED,
                "sha256:" + "6" * 64,
            ),
        )


class _QuarantiningCoordinator:
    def checkpoint(
        self,
        authority: AcquiredAuthority,
        expected_phase: RemoteMarkerPhase,
        next_phase: RemoteMarkerPhase,
        evidence_digest: str | None,
        *,
        updated_at: str,
    ) -> AcquiredAuthority:
        return replace(
            authority,
            ownership=replace(
                authority.ownership,
                generation=authority.ownership.generation + 1,
                phase=next_phase,
                marker_digest="sha256:" + "7" * 64,
            ),
        )

    def quarantine(
        self,
        authority: AcquiredAuthority,
        incident_receipt_digest: str,
        *,
        updated_at: str,
    ) -> RemoteQuarantine:
        return RemoteQuarantine(
            authority.ownership.identity,
            "sha256:" + "8" * 64,
            "sha256:" + "9" * 64,
        )


@dataclass(frozen=True)
class _TypedChange:
    change_id: str


class _Change:
    def __init__(
        self,
        resource_id: str = "skin.playlist.new-shows",
        requires: tuple[str, ...] = (),
    ) -> None:
        self.resource_id = resource_id
        self.requires = requires
        self.disruptive = False
        self.change = _TypedChange(f"change.{resource_id}")
        self.prepared: PreparedManagedFile | None = None
        self.journal: RunStoreExecutionPersistence | None = None

    def prepare(self) -> object:
        if self.prepared is None:
            raise AssertionError("test Change preparation was not configured")
        return self.prepared

    def apply(self, prepared: object) -> ManagedFileExecutionResult:
        observation = ManagedFileObservation(
            ResolvedManagedAddress(
                "special://profile/playlists/video/NewShows.xsp",
                ManagedPath("/storage/.kodi/userdata/playlists/video/NewShows.xsp"),
            ),
            NormalizedResourceState(
                Presence.PRESENT,
                "regular",
                "sha256:" + "d" * 64,
                0o644,
            ),
            b"desired",
        )
        return ManagedFileExecutionResult(
            MutationTrace(()),
            ManagedFileVerification(
                ManagedFileVerificationStatus.MATCHED,
                observation,
            ),
        )

    def cleanup(self, prepared: object, terminal_evidence_ref: str) -> object:
        if self.journal is None:
            return MutationTrace(())
        operation_id = f"operation.{self.resource_id}.cleanup"
        intent = CleanupMutationIntent(
            operation_id,
            PrimitiveKind.CLEANUP,
            "cleanup.new-shows",
            terminal_evidence_ref,
            MarkerCheckpoint(
                _Remote()
                .read_ownership(DeviceId("living-room.ugoos-am6b-plus"))
                .identity,
                "sha256:"
                + "202b6cddfe21dac0427445df8c1756ec0a9bbc10f3b74cd4c693ebef3e63ae48",
                1,
                RemoteMarkerPhase.TERMINAL_RELEASE_PENDING,
                "sha256:" + "6" * 64,
            ),
            1,
        )
        self.journal.record_intent(RunId(RUN_ID), self.resource_id, intent)
        trace = MutationTrace(
            (MutationReceipt(operation_id, MutationDisposition.APPLIED),)
        )
        managed = cast(PreparedManagedFile, prepared)
        self.journal.record_primitive_outcome(
            RunId(RUN_ID),
            self.resource_id,
            trace,
            ManagedFileObservation(managed.address, managed.before, None),
        )
        return trace


class _CleanupFailureChange(_Change):
    def cleanup(self, prepared: object, terminal_evidence_ref: str) -> object:
        raise OSError("cleanup failed")


class _Runtime:
    rollback_events: list[str] | None = None

    def __init__(self, resource_id: str = "") -> None:
        self.resource_id = resource_id

    def observe(self) -> object:
        return object()

    def assess(self, observation: object) -> object:
        return object()

    def prepare(self, change: object) -> object:
        return change

    def apply(self, prepared: object) -> object:
        return object()

    def rollback(self, prepared: object) -> object:
        managed = cast(PreparedManagedFile, prepared)
        if self.rollback_events is not None:
            self.rollback_events.append(self.resource_id)
        return (
            MutationTrace(()),
            ManagedFileVerification(
                ManagedFileVerificationStatus.MATCHED,
                ManagedFileObservation(managed.address, managed.before, None),
            ),
        )

    def cleanup(self, prepared: object, terminal_evidence_ref: str) -> object:
        return MutationTrace(())


class _Contexts:
    def __init__(
        self,
        *,
        device_id: str = "living-room.ugoos-am6b-plus",
        run_id: str = RUN_ID,
        resource_id: str | None = None,
        change_id: str | None = None,
        binding_digest: str = "sha256:" + "a" * 64,
        logical_address: str = "special://profile/playlists/video/NewShows.xsp",
        device_path: str = "/storage/.kodi/userdata/playlists/video/NewShows.xsp",
    ) -> None:
        self.device_id = device_id
        self.run_id = run_id
        self.resource_id = resource_id
        self.change_id = change_id
        self.binding_digest = binding_digest
        self.logical_address = logical_address
        self.device_path = device_path

    def bind(self, journal: object) -> ResourceContextProvider:
        return cast(ResourceContextProvider, self)

    def context(
        self,
        run_id: RunId,
        resource_id: str,
        type_code: str,
        attachments: AttachmentStore,
    ) -> ResourceExecutionContext:
        return ResourceExecutionContext(
            cast(Resource, object()),
            cast(ManagedFileCapabilities, object()),
            attachments,
            cast(ManagedFileLifecycle, object()),
            ResolvedManagedAddress(
                self.logical_address,
                ManagedPath(self.device_path),
            ),
            PreparationBinding(
                self.device_id,
                self.binding_digest,
                self.run_id,
                self.resource_id or resource_id,
                self.change_id or f"change.{resource_id}",
            ),
            _Clock().utc_now,
        )


class _PlanContexts(_Contexts):
    def context(
        self,
        run_id: RunId,
        resource_id: str,
        type_code: str,
        attachments: AttachmentStore,
    ) -> ResourceExecutionContext:
        leaf = resource_id.rsplit(".", maxsplit=1)[-1]
        return ResourceExecutionContext(
            cast(Resource, object()),
            cast(ManagedFileCapabilities, object()),
            attachments,
            cast(ManagedFileLifecycle, object()),
            ResolvedManagedAddress(
                f"special://profile/playlists/video/{leaf.title()}.xsp",
                ManagedPath(
                    f"/storage/.kodi/userdata/playlists/video/{leaf.title()}.xsp"
                ),
            ),
            PreparationBinding(
                self.device_id,
                self.binding_digest,
                self.run_id,
                resource_id,
                f"change.{resource_id}.update",
            ),
            _Clock().utc_now,
        )


class _CountingContexts(_Contexts):
    def __init__(self, **kwargs: str) -> None:
        super().__init__(**kwargs)
        self.bind_calls = 0
        self.context_calls = 0

    def bind(self, journal: object) -> ResourceContextProvider:
        self.bind_calls += 1
        return cast(ResourceContextProvider, self)

    def context(
        self,
        run_id: RunId,
        resource_id: str,
        type_code: str,
        attachments: AttachmentStore,
    ) -> ResourceExecutionContext:
        self.context_calls += 1
        return super().context(run_id, resource_id, type_code, attachments)


class _Inspections:
    def read_remote_ownership(self, run_id: RunId) -> RemoteOwnershipSnapshot:
        return RemoteOwnershipSnapshot(
            Presence.ABSENT,
            None,
            None,
            None,
            None,
            None,
            None,
        )

    def read_remote_quarantine(self, run_id: RunId) -> Presence:
        return Presence.ABSENT

    def live_helper(self, run_id: RunId) -> bool | None:
        return False


class _OwnershipInspections(_Inspections):
    def __init__(self, field: str | None = None) -> None:
        reader = _Remote() if field is None else _MismatchedRemote(field)
        self.ownership = reader.read_ownership(DeviceId("living-room.ugoos-am6b-plus"))

    def read_remote_ownership(self, run_id: RunId) -> RemoteOwnershipSnapshot:
        return RemoteOwnershipSnapshot(
            Presence.PRESENT,
            self.ownership.generation,
            self.ownership.marker_digest,
            self.ownership.token_digest,
            self.ownership.identity,
            self.ownership.phase,
            None,
        )


class _Remote:
    def read_ownership(self, device_id: DeviceId) -> RemoteOwnership:
        return RemoteOwnership(
            RemoteOwnershipIdentity(
                device_id,
                RunId(RUN_ID),
                WorkspaceId(f"workspace:{RUN_ID}"),
                "019950f8-4c00-7000-8000-000000000101",
                "sha256:" + "b" * 64,
                "sha256:" + "a" * 64,
                "boot.opaque",
            ),
            "sha256:"
            + "202b6cddfe21dac0427445df8c1756ec0a9bbc10f3b74cd4c693ebef3e63ae48",
            1,
            RemoteMarkerPhase.VERIFYING,
            "sha256:" + "c" * 64,
        )


class _MismatchedRemote:
    def __init__(self, field: str) -> None:
        self.field = field

    def read_ownership(self, device_id: DeviceId) -> RemoteOwnership:
        ownership = _Remote().read_ownership(device_id)
        if self.field == "token_digest":
            return replace(ownership, token_digest="sha256:" + "f" * 64)
        if self.field == "device_id":
            identity = replace(ownership.identity, device_id=DeviceId("other-device"))
        elif self.field == "run_id":
            identity = replace(
                ownership.identity,
                run_id=RunId("019950f8-4c00-7000-8000-000000000699"),
            )
        elif self.field == "workspace_id":
            identity = replace(
                ownership.identity,
                workspace_id=WorkspaceId(
                    "workspace:019950f8-4c00-7000-8000-000000000699"
                ),
            )
        elif self.field == "plan_full_digest":
            identity = replace(
                ownership.identity, plan_full_digest="sha256:" + "f" * 64
            )
        elif self.field == "binding_digest":
            identity = replace(ownership.identity, binding_digest="sha256:" + "f" * 64)
        elif self.field == "plan_id":
            identity = replace(ownership.identity, plan_id="wrong-plan")
        elif self.field == "boot_id":
            identity = replace(ownership.identity, boot_id="wrong-boot")
        else:
            raise AssertionError(f"unsupported field {self.field}")
        return replace(ownership, identity=identity)


class _ApplicationData:
    def __init__(self, plan: ApprovedPlan, store: RunStore) -> None:
        self._plan = plan
        self._store = store

    def approved_plan(
        self, plan_id: PlanId, approval_scopes: tuple[str, ...]
    ) -> ApprovedPlan:
        return self._plan

    def report(self, command: ReportCommand) -> ReportOutcome:
        report = decode_execution_run_report(
            self._store.load_chain(command.run_id).head.payload,
            resource_registry=_registry(),
        )
        return ReportOutcome(report)


def _registry() -> ResourceRegistry:
    return ResourceRegistry.create(
        (
            ResourceDescriptor(
                "KodiSmartPlaylist",
                parse_intent,
                state_addresses,
                encode_intent,
                decode_intent,
                decode_plan_evidence,
                execution_factory=lambda context: cast(
                    ErasedResourceExecution,
                    _Runtime(context.binding.resource_id),
                ),
                encode_prepared=lambda value: (
                    cast(PreparedManagedFile, value).manifest_bytes
                ),
                decode_prepared=lambda content, attachments: (
                    decode_prepared_managed_file(content, attachments)
                ),
                decode_planned_change=lambda value, context, rollback: _TypedChange(
                    str(value["change_id"])
                ),
            ),
        )
    )


def _reject_planned_change(
    value: object,
    context: object,
    rollback_approved: bool,
) -> object:
    raise ValueError("resolved configuration differs from approved Plan")


def _create(
    store: RunStore,
    resource_ids: tuple[str, ...] = ("skin.playlist.new-shows",),
) -> None:
    device = DeviceId("living-room.ugoos-am6b-plus")
    lease = store.acquire_device(device)
    value = run_value()
    results = value["resource_results"]
    assert isinstance(results, list)
    first_result = results[0]
    assert isinstance(first_result, dict)
    value["resource_results"] = [
        {**deepcopy(first_result), "resource_id": resource_id}
        for resource_id in resource_ids
    ]
    report = build_execution_run_report(value)
    run_lease, _ = store.create_run(
        lease,
        RunId(RUN_ID),
        device,
        b"ownership-token",
        "sha256:" + hashlib.sha256(b"ownership-token").hexdigest(),
        report.canonical_bytes,
    )
    store.release_run(run_lease)
    store.release_device(lease)


def _adapter(
    store: RunStore,
    contexts: ResourceContextProvider | None = None,
    environment: RecoveryEnvironment | None = None,
) -> RunStoreExecutionPersistence:
    return RunStoreExecutionPersistence(
        store,
        RunId(RUN_ID),
        _registry(),
        {"skin.playlist.new-shows": "KodiSmartPlaylist"},
        contexts or cast(ResourceContextProvider, _Contexts()),
        environment or cast(RecoveryEnvironment, _Inspections()),
        cast(RunClock, _Clock()),
    )


def _prepared(
    persistence: RunStoreExecutionPersistence,
    resource_id: str = "skin.playlist.new-shows",
    *,
    filename: str = "NewShows.xsp",
    change_id: str | None = None,
    binding_digest: str = "sha256:" + "a" * 64,
) -> PreparedManagedFile:
    files = FakeManagedFiles()
    desired = NormalizedResourceState(
        Presence.PRESENT,
        "regular",
        "sha256:" + hashlib.sha256(b"desired").hexdigest(),
        0o644,
    )
    return prepare_managed_file(
        reader=files,
        attachments=persistence.attachment_store,
        address=ResolvedManagedAddress(
            f"special://profile/playlists/video/{filename}",
            ManagedPath(f"/storage/.kodi/userdata/playlists/video/{filename}"),
        ),
        binding=PreparationBinding(
            "living-room.ugoos-am6b-plus",
            binding_digest,
            RUN_ID,
            resource_id,
            change_id or f"change.{resource_id}",
        ),
        expected_before=NormalizedResourceState(Presence.ABSENT, None, None, None),
        desired=desired,
        desired_content=b"desired",
        allowed_intermediates=(),
        staged_object=PreparationObject(
            "stage.new-shows",
            desired.content_digest or "",
        ),
        cleanup_object=PreparationObject("cleanup.new-shows", "sha256:" + "c" * 64),
        read_limit=1024,
    )


def test_journal_persists_preparation_and_reconstructs_after_restart(
    tmp_path: Path,
) -> None:
    root = tmp_path / "runs"
    first_store = RunStore(root, resource_registry=_registry())
    _create(first_store)
    first = _adapter(first_store)
    change = _Change()
    change.prepared = _prepared(first)
    change.journal = first
    first.start(ApprovedPlan(RunId(RUN_ID), (cast(ExecutableChange, change),)))
    first.prepared(RunId(RUN_ID), "skin.playlist.new-shows", change.prepared)
    first.close()

    restarted = _adapter(RunStore(root, resource_registry=_registry()))
    resources = restarted.resources(RunId(RUN_ID))

    assert len(resources) == 1
    assert resources[0].resource_id == "skin.playlist.new-shows"
    assert restarted.load_chain(RunId(RUN_ID)).head.revision == 3
    restarted.close()


def test_execution_attachment_store_rejects_unregistered_codec(
    tmp_path: Path,
) -> None:
    store = RunStore(tmp_path / "runs", resource_registry=_registry())
    _create(store)
    persistence = _adapter(store)

    with pytest.raises(ValueError, match="not registered"):
        persistence.attachment_store.attach("private-evidence", "private-v1", b"{}")

    persistence.close()


def test_restart_rejects_every_preparation_context_mismatch(tmp_path: Path) -> None:
    root = tmp_path / "runs"
    store = RunStore(root, resource_registry=_registry())
    _create(store)
    first = _adapter(store)
    change = _Change()
    change.prepared = _prepared(first)
    first.start(ApprovedPlan(RunId(RUN_ID), (cast(ExecutableChange, change),)))
    first.prepared(RunId(RUN_ID), change.resource_id, change.prepared)
    first.close()
    mismatches = (
        ("run_id", "019950f8-4c00-7000-8000-000000000699"),
        ("device_id", "other-device"),
        ("binding_digest", "sha256:" + "f" * 64),
        ("logical_address", "special://profile/playlists/video/Other.xsp"),
        ("device_path", "/storage/.kodi/userdata/playlists/video/Other.xsp"),
        ("change_id", "change.skin.playlist.other"),
    )
    for field, value in mismatches:
        contexts = _Contexts(**{field: value})
        restarted = _adapter(
            RunStore(root, resource_registry=_registry()),
            cast(ResourceContextProvider, contexts),
        )
        with pytest.raises(ValueError, match="current execution context"):
            restarted.resources(RunId(RUN_ID))
        restarted.close()


def test_runstore_recovery_inspection_is_rebuilt_from_durable_evidence(
    tmp_path: Path,
) -> None:
    root = tmp_path / "runs"
    store = RunStore(root, resource_registry=_registry())
    _create(store)
    first = _adapter(store)
    first.start(ApprovedPlan(RunId(RUN_ID), (cast(ExecutableChange, _Change()),)))
    first.prepared(
        RunId(RUN_ID),
        "skin.playlist.new-shows",
        _prepared(first),
    )
    first.close()
    restarted = _adapter(RunStore(root, resource_registry=_registry()))

    inspection = inspect_recovery(restarted.inspection_port(RunId(RUN_ID)))

    assert inspection.evidence.chain_valid
    assert inspection.evidence.preparation_complete
    assert inspection.evidence.forward_work_unperformed
    assert not inspection.evidence.cleanup_complete
    assert tuple(action.code.value for action in inspection.actions) == (
        "inspect",
        "resume_verification",
        "rollback",
        "finalize",
        "finalize",
    )
    restarted.close()


def test_recovery_inspection_rejects_remote_identity_mismatch(
    tmp_path: Path,
) -> None:
    root = tmp_path / "runs"
    store = RunStore(root, resource_registry=_registry())
    _create(store)
    persistence = RunStoreExecutionPersistence(
        store,
        RunId(RUN_ID),
        _registry(),
        {"skin.playlist.new-shows": "KodiSmartPlaylist"},
        cast(ResourceContextProvider, _Contexts()),
        cast(RecoveryEnvironment, _OwnershipInspections("token_digest")),
        cast(RunClock, _Clock()),
    )
    change = _Change()
    change.prepared = _prepared(persistence)
    persistence.start(ApprovedPlan(RunId(RUN_ID), (cast(ExecutableChange, change),)))
    persistence.prepared(RunId(RUN_ID), change.resource_id, change.prepared)

    inspection = inspect_recovery(persistence.inspection_port(RunId(RUN_ID)))

    assert not inspection.evidence.binding_matches
    assert inspection.evidence.remote_integrity_valid is False
    assert all(
        not action.allowed or action.code is RecoveryActionCode.INSPECT
        for action in inspection.actions
    )
    persistence.close()


@pytest.mark.parametrize("corruption", ("revision", "codec", "manifest", "attachment"))
def test_corrupt_recovery_allows_only_inspect_and_approved_abandonment(
    tmp_path: Path,
    corruption: str,
) -> None:
    root = tmp_path / "runs"
    store = RunStore(root, resource_registry=_registry())
    _create(store)
    first = _adapter(store)
    change = _Change()
    change.prepared = _prepared(first)
    first.start(ApprovedPlan(RunId(RUN_ID), (cast(ExecutableChange, change),)))
    first.prepared(RunId(RUN_ID), change.resource_id, change.prepared)
    head = first.load_chain(RunId(RUN_ID)).head
    first.close()
    workspace = (
        root / "runs" / hashlib.sha256(f"workspace:{RUN_ID}".encode()).hexdigest()
    )
    revision_path = workspace / "revisions" / f"{head.revision:08d}.json"
    if corruption == "revision":
        revision_path.write_bytes(b"{}")
    elif corruption == "attachment":
        value = decode_json_object(head.payload)
        preparation = next(
            item
            for item in cast(list[dict[str, object]], value["evidence"])
            if item["payload_kind"] == "ResourcePreparationCompleted"
        )
        references = cast(list[dict[str, object]], preparation["attachment_refs"])
        reference = next(
            item for item in references if item["kind"] == "resource-preparation"
        )
        attachment_path = (
            workspace
            / "attachments"
            / cast(str, reference["digest"]).removeprefix("sha256:")
        )
        attachment_path.write_bytes(b"corrupt")
    else:
        value = decode_json_object(head.payload)
        preparation = next(
            item
            for item in cast(list[dict[str, object]], value["evidence"])
            if item["payload_kind"] == "ResourcePreparationCompleted"
        )
        if corruption == "codec":
            references = cast(list[dict[str, object]], preparation["attachment_refs"])
            reference = next(
                item for item in references if item["kind"] == "resource-preparation"
            )
            reference["codec"] = "unknown-preparation-v1"
        else:
            payload = cast(dict[str, object], preparation["payload"])
            payload["manifest_digest"] = "sha256:" + "f" * 64
        changed = unchecked_run_bytes(value)
        changed_value = decode_json_object(changed)
        revision_path.write_bytes(changed)
        (workspace / "head.json").write_bytes(
            canonical_document_bytes(
                {
                    "digest": changed_value["current_digest"],
                    "revision": head.revision,
                }
            )
        )
    restarted_store = RunStore(root, resource_registry=_registry())
    persistence = _adapter(
        restarted_store,
        environment=cast(RecoveryEnvironment, _OwnershipInspections()),
    )
    authorities = RunStoreBoundAuthorityState(
        restarted_store,
        _Remote(),
        persistence.revision_lease,
    )
    recovery_authority = M3AuthorityRecovery(
        cast(AuthorityCoordinator, _QuarantiningCoordinator()),
        authorities,
        _Clock(),
        persistence,
    )
    coordinator = RecoveryCoordinator(persistence, recovery_authority)

    inspection = coordinator.inspect(RunId(RUN_ID))

    assert [action.code for action in inspection.actions if action.allowed] == [
        RecoveryActionCode.INSPECT,
        RecoveryActionCode.FINALIZE,
    ]
    abandon = next(
        action
        for action in inspection.actions
        if action.code is RecoveryActionCode.FINALIZE and action.allowed
    )
    assert abandon.finalize_mode is FinalizeMode.ABANDON

    outcome = coordinator.finalize(
        RunId(RUN_ID),
        FinalizeMode.ABANDON,
        approval="approval.operator",
        reason=f"{corruption} evidence is corrupt",
    )

    assert outcome.status is RunStatus.FAILED_RECOVERY_REQUIRED
    assert not outcome.cleanup_complete
    assert (
        restarted_store.find_active_by_device(DeviceId("living-room.ugoos-am6b-plus"))
        == ()
    )
    seal = decode_json_object((workspace / "seal.json").read_bytes())
    state = decode_json_object((workspace / "state.json").read_bytes())
    receipts = tuple((workspace / "receipts").glob("*.json"))
    assert seal["ownership_released_or_quarantined"] is True
    assert seal["terminal_revision"] == 0
    assert state["status"] == RunStatus.FAILED_RECOVERY_REQUIRED.value
    assert state["terminal"] is True
    assert len(receipts) == 2
    authorities.close(RunId(RUN_ID))
    persistence.close()


def test_ambiguous_cleanup_receipt_is_not_classified_complete_after_restart(
    tmp_path: Path,
) -> None:
    root = tmp_path / "runs"
    store = RunStore(root, resource_registry=_registry())
    _create(store)
    first = _adapter(store)
    first.start(ApprovedPlan(RunId(RUN_ID), (cast(ExecutableChange, _Change()),)))
    first.prepared(
        RunId(RUN_ID),
        "skin.playlist.new-shows",
        _prepared(first),
    )
    first.record_cleanup(
        RunId(RUN_ID),
        "skin.playlist.new-shows",
        MutationTrace((MutationReceipt("cleanup", MutationDisposition.AMBIGUOUS),)),
    )
    first.close()

    restarted = _adapter(RunStore(root, resource_registry=_registry()))
    inspection = inspect_recovery(restarted.inspection_port(RunId(RUN_ID)))

    assert not inspection.evidence.cleanup_complete
    restarted.close()


def _saved_plan_request() -> tuple[
    SavedPlanExecutionRequest, CanonicalPlan, CanonicalRunReport
]:
    plan = decode_plan((FIXTURES / "plan-actionable.json").read_bytes())
    planning_run = decode_run_report(
        (FIXTURES / "run-awaiting-approval.json").read_bytes(),
        plan,
    )
    value = decode_json_object(plan.canonical_bytes)
    device = value["device"]
    digests = value["input_digests"]
    assert isinstance(device, dict)
    assert isinstance(digests, dict)
    request = SavedPlanExecutionRequest(
        PlanId(plan.plan_id),
        RunId(RUN_ID),
        DeviceId("living-room.ugoos-am6b-plus"),
        RunId(planning_run.run_id),
        device,
        cast(dict[str, str], digests),
        (
            ApprovalGrant(
                "apply",
                "actor.local-admin",
                "noninteractive_cli",
                "2026-09-19T08:01:00Z",
            ),
        ),
        "2026-09-19T08:01:00Z",
    )
    return request, plan, planning_run


def _device_binding(device: dict[str, object]) -> str:
    return "sha256:" + hashlib.sha256(canonical_document_bytes(device)).hexdigest()


def _canonical_plan(value: dict[str, object]) -> bytes:
    semantic = {
        key: item
        for key, item in value.items()
        if key
        not in {
            "plan_id",
            "created_at",
            "expires_at",
            "full_digest",
            "semantic_digest",
        }
    }
    producer = dict(cast(dict[str, object], semantic["producer"]))
    producer.pop("version")
    semantic["producer"] = producer
    value["semantic_digest"] = (
        "sha256:" + hashlib.sha256(canonical_document_bytes(semantic)).hexdigest()
    )
    without_full = dict(value)
    without_full.pop("full_digest")
    value["full_digest"] = (
        "sha256:" + hashlib.sha256(canonical_document_bytes(without_full)).hexdigest()
    )
    return canonical_document_bytes(value)


def _canonical_run(value: dict[str, object]) -> bytes:
    without_current = dict(value)
    without_current.pop("current_digest")
    value["current_digest"] = (
        "sha256:"
        + hashlib.sha256(canonical_document_bytes(without_current)).hexdigest()
    )
    return canonical_document_bytes(value)


def _saved_multi_plan_request() -> tuple[
    SavedPlanExecutionRequest, CanonicalPlan, CanonicalRunReport
]:
    plan = decode_plan((FIXTURES / "plan-actionable-multi.json").read_bytes())
    planning_run = decode_run_report(
        (FIXTURES / "run-awaiting-approval-multi.json").read_bytes(),
        plan,
    )
    value = decode_json_object(plan.canonical_bytes)
    device = cast(dict[str, object], value["device"])
    digests = cast(dict[str, str], value["input_digests"])
    return (
        SavedPlanExecutionRequest(
            PlanId(plan.plan_id),
            RunId(RUN_ID),
            DeviceId(cast(str, device["logical_id"])),
            RunId(planning_run.run_id),
            device,
            digests,
            (
                ApprovalGrant(
                    "apply",
                    "actor.local-admin",
                    "noninteractive_cli",
                    "2026-09-19T08:01:00Z",
                ),
            ),
            "2026-09-19T08:01:00Z",
        ),
        plan,
        planning_run,
    )


@pytest.fixture(scope="module")
def saved_plan_environment(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[RunStore, PlanStore, ResourceRegistry]:
    request, plan, planning_run = _saved_plan_request()
    registry = _registry()
    root = tmp_path_factory.mktemp("saved-plan-environment")
    store = RunStore(root / "runs", resource_registry=registry)
    plans = PlanStore(root / "plans")
    plans.save(plan, planning_run)
    assert request.plan_id == PlanId(plan.plan_id)
    return store, plans, registry


def _saved_plan_with_unchanged_resources() -> tuple[
    SavedPlanExecutionRequest, CanonicalPlan, CanonicalRunReport
]:
    plan_value = decode_json_object(
        (FIXTURES / "plan-actionable-multi.json").read_bytes()
    )
    resources = cast(list[dict[str, object]], plan_value["resources"])
    evidence = cast(list[dict[str, object]], plan_value["evidence"])
    alpha = deepcopy(resources[0])
    beta = deepcopy(resources[1])
    alpha_evidence = deepcopy(evidence[0])

    def renamed(value: dict[str, object], suffix: str) -> dict[str, object]:
        content = (
            canonical_document_bytes(value)
            .decode()
            .replace("skin.playlist.alpha", f"skin.playlist.{suffix}")
        )
        return decode_json_object(
            content.replace("Alpha.xsp", f"{suffix.title()}.xsp").encode()
        )

    independent = renamed(alpha, "independent")
    independent["changes"] = []
    independent["desired_relation"] = "satisfied"
    independent["requires"] = []
    bridge = renamed(alpha, "bridge")
    bridge["changes"] = []
    bridge["desired_relation"] = "satisfied"
    bridge["requires"] = ["skin.playlist.alpha"]
    beta["requires"] = ["skin.playlist.bridge"]
    resources[:] = [alpha, independent, bridge, beta]
    evidence[:] = [
        alpha_evidence,
        renamed(alpha_evidence, "independent"),
        renamed(alpha_evidence, "bridge"),
        evidence[1],
    ]
    plan = decode_plan(_canonical_plan(plan_value))

    run_value = decode_json_object(
        (FIXTURES / "run-awaiting-approval-multi.json").read_bytes()
    )
    results = cast(list[dict[str, object]], run_value["resource_results"])
    alpha_result = deepcopy(results[0])
    independent_result = deepcopy(alpha_result)
    independent_result["resource_id"] = "skin.playlist.independent"
    independent_result["latest_observed_relation"] = "satisfied"
    independent_result["mutation_outcome"] = "not_required"
    independent_result["verification_outcome"] = "fresh_match"
    independent_result["final_convergence"] = "converged"
    bridge_result = deepcopy(alpha_result)
    bridge_result["resource_id"] = "skin.playlist.bridge"
    bridge_result["latest_observed_relation"] = "satisfied"
    bridge_result["mutation_outcome"] = "not_required"
    bridge_result["verification_outcome"] = "fresh_match"
    bridge_result["final_convergence"] = "converged"
    results[:] = [alpha_result, independent_result, bridge_result, results[1]]
    plan_reference = cast(dict[str, object], run_value["plan_reference"])
    plan_reference["plan_full_digest"] = plan.full_digest
    planning_run = decode_run_report(_canonical_run(run_value), plan)
    request, _, _ = _saved_multi_plan_request()
    return (
        replace(
            request,
            plan_id=PlanId(plan.plan_id),
            originating_run_id=RunId(planning_run.run_id),
        ),
        plan,
        planning_run,
    )


def test_saved_plan_approval_creates_bound_run_and_only_encoded_changes(
    tmp_path: Path,
) -> None:
    request, plan, planning_run = _saved_plan_request()
    registry = _registry()
    store = RunStore(tmp_path / "runs", resource_registry=registry)
    plans = PlanStore(tmp_path / "plans")
    plans.save(plan, planning_run)
    authority = _AcquiringAuthority(store)
    device = cast(dict[str, object], request.expected_device)
    device_authority = _DeviceAuthority(device)
    factory = ProductionExecutionFactory(
        plans,
        store,
        registry,
        {"skin.playlist.new-shows": "KodiSmartPlaylist"},
        cast(
            ResourceContextProviderFactory,
            _Contexts(binding_digest=_device_binding(device)),
        ),
        cast(RecoveryEnvironment, _Inspections()),
        device_authority,
        cast(AuthorityCoordinator, authority),
        cast(RemoteOwnershipReader, object()),
        cast(RunClock, _Clock()),
    )

    approved = factory.approve_saved_plan(request)

    assert authority.calls == 1
    assert approved.approved_plan.run_id == request.execution_run_id
    assert tuple(change.resource_id for change in approved.approved_plan.changes) == (
        "skin.playlist.new-shows",
    )
    assert (
        decode_json_object(store.load_chain(request.execution_run_id).head.payload)[
            "status"
        ]
        == RunStatus.READY.value
    )
    run = decode_json_object(store.load_chain(request.execution_run_id).head.payload)
    run_authority = cast(dict[str, object], run["authority"])
    assert run_authority["binding_digest"] == _device_binding(device)
    assert run_authority["boot_id"] == "boot.opaque"
    assert run["started_at"] == "2026-09-19T08:02:00Z"
    assert device_authority.calls == 2
    approved.services.close()


def test_saved_plan_projects_unchanged_resources_for_execution_and_restart(
    tmp_path: Path,
) -> None:
    request, plan, planning_run = _saved_plan_with_unchanged_resources()
    device = cast(dict[str, object], request.expected_device)
    registry = _registry()
    store = RunStore(tmp_path / "runs", resource_registry=registry)
    plans = PlanStore(tmp_path / "plans")
    plans.save(plan, planning_run)
    authority = _AcquiringAuthority(store)
    resource_types = {
        "skin.playlist.alpha": "KodiSmartPlaylist",
        "skin.playlist.independent": "KodiSmartPlaylist",
        "skin.playlist.bridge": "KodiSmartPlaylist",
        "skin.playlist.beta": "KodiSmartPlaylist",
    }
    factory = ProductionExecutionFactory(
        plans,
        store,
        registry,
        resource_types,
        cast(
            ResourceContextProviderFactory,
            _PlanContexts(binding_digest=_device_binding(device)),
        ),
        cast(RecoveryEnvironment, _Inspections()),
        _DeviceAuthority(device),
        cast(AuthorityCoordinator, authority),
        cast(RemoteOwnershipReader, object()),
        cast(RunClock, _Clock()),
    )

    approved = factory.approve_saved_plan(request)

    assert [
        (change.resource_id, change.requires)
        for change in approved.approved_plan.changes
    ] == [
        ("skin.playlist.alpha", ()),
        ("skin.playlist.beta", ("skin.playlist.alpha",)),
    ]
    initial = decode_json_object(
        store.load_chain(request.execution_run_id).head.payload
    )
    results = {
        cast(str, result["resource_id"]): result
        for result in cast(list[dict[str, object]], initial["resource_results"])
    }
    for resource_id in (
        "skin.playlist.independent",
        "skin.playlist.bridge",
    ):
        assert results[resource_id]["mutation_outcome"] == "not_required"
        assert results[resource_id]["verification_outcome"] == "fresh_match"
        assert results[resource_id]["final_convergence"] == "converged"
    approved.services.persistence.start(approved.approved_plan)
    for change in approved.approved_plan.changes:
        prepared = _prepared(
            approved.services.persistence,
            change.resource_id,
            filename=(
                "Alpha.xsp"
                if change.resource_id == "skin.playlist.alpha"
                else "Beta.xsp"
            ),
            change_id=f"change.{change.resource_id}.update",
            binding_digest=_device_binding(device),
        )
        approved.services.persistence.prepared(
            request.execution_run_id,
            change.resource_id,
            prepared,
        )
    approved.services.close()

    restarted = factory.bind(request.execution_run_id)
    resources = restarted.persistence.resources(request.execution_run_id)
    assert [resource.resource_id for resource in resources] == [
        "skin.playlist.alpha",
        "skin.playlist.beta",
    ]
    rollback_events: list[str] = []
    _Runtime.rollback_events = rollback_events
    try:
        for resource in reversed(resources):
            resource.rollback()
    finally:
        _Runtime.rollback_events = None
    assert rollback_events == [
        "skin.playlist.beta",
        "skin.playlist.alpha",
    ]
    restarted.close()


@pytest.mark.parametrize(
    "mismatch",
    (
        "device_id",
        "device_host",
        "device_port",
        "device_platform",
        "device_host_key",
        "input_authored",
        "input_profile",
        "input_artifact",
        "input_capabilities",
        "input_observation",
        "input_aggregate",
        "origin",
        "not_yet_valid",
        "caller_backdated_after_expiry",
        "approval_missing",
        "approval_extra",
        "approval_duplicate",
        "approval_actor",
        "approval_mechanism",
        "approval_before_plan",
        "approval_after_trusted_time",
    ),
)
def test_saved_plan_approval_fails_before_run_creation_on_mismatch(
    saved_plan_environment: tuple[RunStore, PlanStore, ResourceRegistry],
    mismatch: str,
) -> None:
    request, _, _ = _saved_plan_request()
    clock = _Clock()
    if mismatch.startswith("device_"):
        device = deepcopy(dict(request.expected_device))
        endpoint = cast(dict[str, object], device["endpoint"])
        if mismatch == "device_id":
            device["logical_id"] = "other-device"
        elif mismatch == "device_host":
            endpoint["host"] = "other.example.test"
        elif mismatch == "device_port":
            endpoint["port"] = 2200
        elif mismatch == "device_platform":
            device["observed_platform_identity_fingerprint"] = "sha256:" + "f" * 64
        else:
            device["ssh_host_key_fingerprint"] = "SHA256:other"
        request = replace(request, expected_device=device)
    elif mismatch.startswith("input_"):
        key = {
            "input_authored": "authored_configuration",
            "input_profile": "resolved_profile",
            "input_artifact": "artifact_resolution",
            "input_capabilities": "controller_capabilities",
            "input_observation": "observation_snapshot",
            "input_aggregate": "aggregate_semantic",
        }[mismatch]
        digests = dict(request.input_digests)
        digests[key] = "sha256:" + "f" * 64
        request = replace(
            request,
            input_digests=digests,
        )
    elif mismatch == "origin":
        request = replace(
            request,
            originating_run_id=RunId("019950f8-4c00-7000-8000-000000000699"),
        )
    elif mismatch == "caller_backdated_after_expiry":
        request = replace(request, now="2026-09-19T08:01:00Z")
        clock = _Clock("2030-01-01T00:00:00Z")
    elif mismatch == "not_yet_valid":
        clock = _Clock("2026-09-19T08:00:59Z")
    elif mismatch == "approval_missing":
        request = replace(request, approval_grants=())
    elif mismatch == "approval_extra":
        request = replace(
            request,
            approval_grants=(
                *request.approval_grants,
                ApprovalGrant(
                    "rollback",
                    "actor.local-admin",
                    "noninteractive_cli",
                    request.now,
                ),
            ),
        )
    elif mismatch == "approval_duplicate":
        request = replace(
            request,
            approval_grants=(
                *request.approval_grants,
                request.approval_grants[0],
            ),
        )
    else:
        grant = request.approval_grants[0]
        replacements = {
            "approval_actor": replace(grant, actor=""),
            "approval_mechanism": replace(grant, mechanism=""),
            "approval_before_plan": replace(grant, granted_at="2026-09-19T08:00:59Z"),
            "approval_after_trusted_time": replace(
                grant, granted_at="2026-09-19T08:02:01Z"
            ),
        }
        request = replace(request, approval_grants=(replacements[mismatch],))
    store, plans, registry = saved_plan_environment
    authority = _AcquiringAuthority(store)
    device = cast(dict[str, object], request.expected_device)
    factory = ProductionExecutionFactory(
        plans,
        store,
        registry,
        {"skin.playlist.new-shows": "KodiSmartPlaylist"},
        cast(
            ResourceContextProviderFactory,
            _Contexts(binding_digest=_device_binding(device)),
        ),
        cast(RecoveryEnvironment, _Inspections()),
        _DeviceAuthority(device),
        cast(AuthorityCoordinator, authority),
        cast(RemoteOwnershipReader, object()),
        cast(RunClock, clock),
    )

    with pytest.raises(ValueError):
        factory.approve_saved_plan(request)

    assert authority.calls == 0


def test_saved_plan_preflight_rejects_locally_without_execution_side_effects(
    saved_plan_environment: tuple[RunStore, PlanStore, ResourceRegistry],
) -> None:
    request, _, _ = _saved_plan_request()
    request = replace(
        request,
        originating_run_id=RunId("019950f8-4c00-7000-8000-000000000699"),
    )
    store, plans, registry = saved_plan_environment
    authority = _AcquiringAuthority(store)
    device = cast(dict[str, object], request.expected_device)
    device_authority = _DeviceAuthority(device)
    contexts = _CountingContexts(binding_digest=_device_binding(device))
    factory = ProductionExecutionFactory(
        plans,
        store,
        registry,
        {"skin.playlist.new-shows": "KodiSmartPlaylist"},
        cast(ResourceContextProviderFactory, contexts),
        cast(RecoveryEnvironment, _Inspections()),
        device_authority,
        cast(AuthorityCoordinator, authority),
        cast(RemoteOwnershipReader, object()),
        cast(RunClock, _Clock()),
    )

    with pytest.raises(ValueError, match="origin binding"):
        factory.preflight_saved_plan(request)

    assert device_authority.calls == 0
    assert contexts.bind_calls == 0
    assert contexts.context_calls == 0
    assert authority.calls == 0
    with pytest.raises(FileNotFoundError):
        store.load_chain(request.execution_run_id)


@pytest.mark.parametrize("failure", ("stale", "tampered"))
def test_saved_plan_preparation_rejects_invalid_preflight_before_side_effects(
    saved_plan_environment: tuple[RunStore, PlanStore, ResourceRegistry],
    failure: str,
) -> None:
    request, _, _ = _saved_plan_request()
    store, plans, registry = saved_plan_environment
    authority = _AcquiringAuthority(store)
    device = cast(dict[str, object], request.expected_device)
    device_authority = _DeviceAuthority(device)
    contexts = _CountingContexts(binding_digest=_device_binding(device))
    clock = _Clock()
    factory = ProductionExecutionFactory(
        plans,
        store,
        registry,
        {"skin.playlist.new-shows": "KodiSmartPlaylist"},
        cast(ResourceContextProviderFactory, contexts),
        cast(RecoveryEnvironment, _Inspections()),
        device_authority,
        cast(AuthorityCoordinator, authority),
        cast(RemoteOwnershipReader, object()),
        cast(RunClock, clock),
    )
    preflight = factory.preflight_saved_plan(request)
    if failure == "stale":
        clock.now = "2030-01-01T00:00:00Z"
    else:
        preflight = replace(
            preflight,
            execution_run_id=RunId("019950f8-4c00-7000-8000-000000000699"),
        )

    with pytest.raises(ValueError, match=r"stale|altered"):
        factory.prepare_saved_plan(preflight, device_authority.observation)

    assert contexts.bind_calls == 0
    assert contexts.context_calls == 0
    assert authority.calls == 0
    with pytest.raises(FileNotFoundError):
        store.load_chain(preflight.execution_run_id)


def test_saved_plan_approval_rejects_unknown_plan_before_authority(
    tmp_path: Path,
) -> None:
    request, _, _ = _saved_plan_request()
    registry = _registry()
    store = RunStore(tmp_path / "runs", resource_registry=registry)
    authority = _AcquiringAuthority(store)
    device = cast(dict[str, object], request.expected_device)
    factory = ProductionExecutionFactory(
        PlanStore(tmp_path / "plans"),
        store,
        registry,
        {"skin.playlist.new-shows": "KodiSmartPlaylist"},
        cast(
            ResourceContextProviderFactory,
            _Contexts(binding_digest=_device_binding(device)),
        ),
        cast(RecoveryEnvironment, _Inspections()),
        _DeviceAuthority(device),
        cast(AuthorityCoordinator, authority),
        cast(RemoteOwnershipReader, object()),
        cast(RunClock, _Clock()),
    )

    with pytest.raises(DurabilityError):
        factory.approve_saved_plan(request)

    assert authority.calls == 0


def test_saved_plan_decoding_failure_precedes_authority_acquisition(
    tmp_path: Path,
) -> None:
    request, plan, planning_run = _saved_plan_request()
    base = _registry().descriptor("KodiSmartPlaylist")
    assert base is not None
    registry = ResourceRegistry.create(
        (replace(base, decode_planned_change=_reject_planned_change),)
    )
    store = RunStore(tmp_path / "runs", resource_registry=registry)
    plans = PlanStore(tmp_path / "plans")
    plans.save(plan, planning_run)
    authority = _AcquiringAuthority(store)
    device = cast(dict[str, object], request.expected_device)
    factory = ProductionExecutionFactory(
        plans,
        store,
        registry,
        {"skin.playlist.new-shows": "KodiSmartPlaylist"},
        cast(
            ResourceContextProviderFactory,
            _Contexts(binding_digest=_device_binding(device)),
        ),
        cast(RecoveryEnvironment, _Inspections()),
        _DeviceAuthority(device),
        cast(AuthorityCoordinator, authority),
        cast(RemoteOwnershipReader, object()),
        cast(RunClock, _Clock()),
    )

    with pytest.raises(ValueError, match="differs from approved Plan"):
        factory.approve_saved_plan(request)

    assert authority.calls == 0


@pytest.mark.parametrize(
    "mismatch",
    ("binding_digest", "boot_id", "platform_identity", "host_key"),
)
def test_saved_plan_rejects_spoofed_or_changed_device_authority(
    saved_plan_environment: tuple[RunStore, PlanStore, ResourceRegistry],
    mismatch: str,
) -> None:
    request, _, _ = _saved_plan_request()
    device = cast(dict[str, object], request.expected_device)
    expected_probe = _DeviceAuthority(device)
    if mismatch == "binding_digest":
        probe = _DeviceAuthority(device, binding_digest="sha256:" + "f" * 64)
    elif mismatch == "platform_identity":
        probe = _DeviceAuthority(device, platform_identity="sha256:" + "f" * 64)
    elif mismatch == "host_key":
        probe = _DeviceAuthority(device, host_key="SHA256:other")
    else:
        probe = _DeviceAuthority(
            device,
            second=replace(expected_probe.observation, boot_id="boot.changed"),
        )
    store, plans, registry = saved_plan_environment
    authority = _AcquiringAuthority(store)
    factory = ProductionExecutionFactory(
        plans,
        store,
        registry,
        {"skin.playlist.new-shows": "KodiSmartPlaylist"},
        cast(
            ResourceContextProviderFactory,
            _Contexts(binding_digest=_device_binding(device)),
        ),
        cast(RecoveryEnvironment, _Inspections()),
        probe,
        cast(AuthorityCoordinator, authority),
        cast(RemoteOwnershipReader, object()),
        cast(RunClock, _Clock()),
    )

    with pytest.raises(ValueError, match="Device authority identity"):
        factory.approve_saved_plan(request)

    assert authority.calls == 0


def test_normal_finalizer_releases_with_exact_terminal_digest_after_cleanup(
    tmp_path: Path,
) -> None:
    store = RunStore(tmp_path / "runs", resource_registry=_registry())
    _create(store)
    persistence = _adapter(store)
    authority = _FinalizerAuthority()
    engine = ExecutionEngine(
        persistence,
        cast(RecoveryDriver, object()),
        finalizer=RunStoreExecutionFinalizer(
            persistence, cast(RecoveryAuthority, authority)
        ),
    )

    change = _Change()
    change.prepared = _prepared(persistence)
    change.journal = persistence
    result = engine.start(
        ApprovedPlan(RunId(RUN_ID), (cast(ExecutableChange, change),))
    )
    chain = persistence.load_chain(RunId(RUN_ID))
    terminal = next(
        revision
        for revision in chain.revisions
        if decode_json_object(revision.payload)["status"] == "converged"
    )

    assert authority.releases == [(RunId(RUN_ID), terminal.digest)]
    assert result.cleanup_complete is True
    persistence.close()


def test_normal_finalizer_does_not_release_when_cleanup_is_incomplete(
    tmp_path: Path,
) -> None:
    store = RunStore(tmp_path / "runs", resource_registry=_registry())
    _create(store)
    persistence = _adapter(store)
    authority = _FinalizerAuthority()
    engine = ExecutionEngine(
        persistence,
        cast(RecoveryDriver, object()),
        finalizer=RunStoreExecutionFinalizer(
            persistence, cast(RecoveryAuthority, authority)
        ),
    )

    change = _CleanupFailureChange()
    change.prepared = _prepared(persistence)
    change.journal = persistence
    result = engine.start(
        ApprovedPlan(
            RunId(RUN_ID),
            (cast(ExecutableChange, change),),
        )
    )

    assert authority.releases == []
    assert result.cleanup_complete is False
    persistence.close()


def test_bound_authority_reconstructs_local_leases_and_remote_identity(
    tmp_path: Path,
) -> None:
    store = RunStore(tmp_path / "runs", resource_registry=_registry())
    _create(store)
    state = RunStoreBoundAuthorityState(store, _Remote())

    authority = state.load(RunId(RUN_ID))

    assert authority.revision_lease.workspace_id == WorkspaceId(f"workspace:{RUN_ID}")
    assert authority.ownership.identity.run_id == RunId(RUN_ID)
    state.close(RunId(RUN_ID))


@pytest.mark.parametrize(
    "field",
    (
        "device_id",
        "run_id",
        "workspace_id",
        "plan_id",
        "plan_full_digest",
        "binding_digest",
        "boot_id",
        "token_digest",
    ),
)
def test_bound_authority_rejects_every_remote_identity_mismatch(
    tmp_path: Path,
    field: str,
) -> None:
    store = RunStore(tmp_path / "runs", resource_registry=_registry())
    _create(store)
    state = RunStoreBoundAuthorityState(store, _MismatchedRemote(field))

    with pytest.raises(ValueError, match="does not bind"):
        state.load(RunId(RUN_ID))


def test_bound_authority_mismatch_preserves_injected_revision_lease(
    tmp_path: Path,
) -> None:
    store = RunStore(tmp_path / "runs", resource_registry=_registry())
    _create(store)
    persistence = _adapter(store)
    state = RunStoreBoundAuthorityState(
        store,
        _MismatchedRemote("token_digest"),
        persistence.revision_lease,
    )

    with pytest.raises(ValueError, match="does not bind"):
        state.load(RunId(RUN_ID))

    assert persistence.load_chain(RunId(RUN_ID)).head.revision == 1
    persistence.close()


def test_bound_authority_mismatch_releases_locally_acquired_revision_lease(
    tmp_path: Path,
) -> None:
    store = RunStore(tmp_path / "runs", resource_registry=_registry())
    _create(store)
    state = RunStoreBoundAuthorityState(store, _MismatchedRemote("token_digest"))

    with pytest.raises(ValueError, match="does not bind"):
        state.load(RunId(RUN_ID))

    lease = store.acquire_run(RunId(RUN_ID))
    store.release_run(lease)


def test_public_apply_uses_concrete_runstore_journal_across_restart(
    tmp_path: Path,
) -> None:
    root = tmp_path / "runs"
    store = RunStore(root, resource_registry=_registry())
    _create(store)
    persistence = _adapter(store)
    change = _Change()
    change.prepared = _prepared(persistence)
    change.journal = persistence
    plan = ApprovedPlan(RunId(RUN_ID), (cast(ExecutableChange, change),))
    engine = ExecutionEngine(persistence, cast(RecoveryDriver, object()))
    workflows = ExecutionApplicationWorkflows(
        cast(ApplicationData, _ApplicationData(plan, store)),
        engine,
    )

    outcome = workflows.apply(
        ApplyCommand(
            ".",
            PlanId("019950f8-4c00-7000-8000-000000000101"),
            ("apply",),
        )
    )
    persistence.close()

    assert isinstance(outcome, ApplyOutcome)
    assert outcome.status is RunStatus.CONVERGED
    assert outcome.cleanup_complete
    restarted = RunStore(root, resource_registry=_registry())
    assert restarted.load_chain(RunId(RUN_ID)).terminal
    assert restarted.load_chain(RunId(RUN_ID)).head.revision > 1
