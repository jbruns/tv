"""Production composition root for the Reconciler."""

from __future__ import annotations

import base64
import hashlib
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast

from coreelec_reconciler.application.commands import (
    ObserveCommand,
    PlanCommand,
    ReportCommand,
    ValidateCommand,
    VerifyCommand,
)
from coreelec_reconciler.application.outcomes import (
    ApprovalResolution,
    ObservationOutcome,
    PlanOutcome,
    ReportOutcome,
    UnsupportedOutcome,
    UnsupportedReason,
    ValidationOutcome,
    VerifyOutcome,
)
from coreelec_reconciler.application.reconciler import (
    ApplicationDependencies,
    ApplicationReconciler,
    CapabilityUnavailableError,
    ExecutionApplicationWorkflows,
    Reconciler,
)
from coreelec_reconciler.domain.configuration import (
    ResolvedConfiguration,
    ResolvedDevice,
)
from coreelec_reconciler.domain.execution import (
    MarkerCheckpoint,
    MutationIntent,
    MutationTrace,
    Presence,
    PrimitiveKind,
    RemoteMarkerPhase,
    RemoteOwnership,
    RemoteOwnershipSnapshot,
)
from coreelec_reconciler.domain.identifiers import (
    DeviceId,
    PlanId,
    RunId,
    SelectorId,
)
from coreelec_reconciler.domain.planning import (
    CanonicalPlan,
    PlanningRuntime,
    SuppliedPlanningInput,
)
from coreelec_reconciler.execution.authority import (
    AuthorityCoordinator,
    RemoteAuthorityBackend,
)
from coreelec_reconciler.execution.composition import (
    ApprovalGrant,
    BoundExecutionServices,
    DeviceAuthorityObservation,
    PreparedExecution,
    ProductionExecutionFactory,
    SavedPlanExecutionRequest,
)
from coreelec_reconciler.execution.engine import (
    ApprovedPlan,
    ExecutionEngine,
    ExecutionOutcome,
    RecoveryRequest,
)
from coreelec_reconciler.execution.plan_store import PlanStore, PlanStoreError
from coreelec_reconciler.execution.recovery import RecoveryInspection
from coreelec_reconciler.execution.run_adapters import ManagedFileLifecycleFactory
from coreelec_reconciler.execution.runtime import RuntimeValues, SystemRuntimeValues
from coreelec_reconciler.inventory.ledger import validate_ledger
from coreelec_reconciler.reporting.canonical_json import decode_json_object
from coreelec_reconciler.resource_types.descriptor import (
    AttachmentStore,
    ManagedFileCapabilities,
    ManagedFileExecutionResult,
    ManagedFileLifecycle,
    ManagedFileVerification,
)
from coreelec_reconciler.resource_types.managed_file.observation import (
    ManagedFileObservation,
)
from coreelec_reconciler.resource_types.managed_file.preparation import (
    PreparedManagedFile,
)
from coreelec_reconciler.transports.interfaces import (
    DeviceCapabilitySnapshot,
    DeviceIdentity,
    DeviceSession,
    ManagedFileReader,
)

if TYPE_CHECKING:
    from coreelec_reconciler.execution.run_store import RunStore


@dataclass(frozen=True, slots=True)
class BootstrapSettings:
    repository_root: str
    state_root: str | None = None
    environment_secret_names: tuple[tuple[str, str], ...] = ()
    pinned_host_keys: tuple[tuple[str, str], ...] = ()
    session_opener: Callable[[ResolvedDevice, frozenset[str]], DeviceSession] | None = (
        field(default=None, repr=False, compare=False)
    )
    runtime_values: RuntimeValues | None = field(
        default=None, repr=False, compare=False
    )
    host_key_fingerprint: Callable[[ResolvedDevice], str] | None = field(
        default=None, repr=False, compare=False
    )


class _ProductionDeviceSession(Protocol):
    @property
    def identity(self) -> DeviceIdentity: ...

    @property
    def capabilities(self) -> DeviceCapabilitySnapshot: ...

    @property
    def managed_files(self) -> ManagedFileReader: ...

    @property
    def managed_file_mutations(self) -> ManagedFileCapabilities: ...

    def remote_ownership(self, workspace_key: str) -> RemoteAuthorityBackend: ...

    def close(self) -> None: ...


@dataclass(slots=True)
class ProductionServices:
    """Lazy production Adapter access owned exclusively by the composition root."""

    settings: BootstrapSettings
    environment: Mapping[str, str]
    _store: RunStore | None = None
    _plans: PlanStore | None = None
    _runtime: RuntimeValues | None = None

    def open_device_session(
        self,
        device: ResolvedDevice,
        required_capabilities: frozenset[str],
    ) -> DeviceSession:
        if self.settings.session_opener is not None:
            return self.settings.session_opener(device, required_capabilities)
        from coreelec_reconciler.adapters.paramiko_session import (
            ParamikoSessionFactory,
        )
        from coreelec_reconciler.adapters.secrets import (
            EnvironmentSecretResolver,
            MappingHostKeyResolver,
        )
        from coreelec_reconciler.config.device import (
            resolve_device_session_parameters,
        )

        secrets = EnvironmentSecretResolver(
            dict(self.settings.environment_secret_names), self.environment
        )
        parameters = resolve_device_session_parameters(device, secrets)
        sessions = ParamikoSessionFactory(
            MappingHostKeyResolver(dict(self.settings.pinned_host_keys))
        )
        return sessions.open(parameters, required_capabilities)

    @property
    def runtime(self) -> RuntimeValues:
        if self._runtime is None:
            self._runtime = self.settings.runtime_values or SystemRuntimeValues()
        return self._runtime

    def state_root(self) -> Path:
        configured = self.settings.state_root
        return (
            Path(configured)
            if configured is not None
            else Path.home() / ".local" / "state" / "coreelec-reconciler"
        )

    def run_store(self) -> RunStore:
        from coreelec_reconciler.execution.run_store import RunStore

        if self._store is not None:
            return self._store
        self._store = RunStore(self.state_root() / "runs")
        return self._store

    def plan_store(self) -> PlanStore:
        if self._plans is None:
            self._plans = PlanStore(self.state_root() / "plans")
        return self._plans

    def state_root_exists(self) -> bool:
        return self.state_root().is_dir()

    def host_key_fingerprint(self, device: ResolvedDevice) -> str:
        if self.settings.host_key_fingerprint is not None:
            return self.settings.host_key_fingerprint(device)
        from coreelec_reconciler.adapters.secrets import MappingHostKeyResolver

        pinned = MappingHostKeyResolver(
            dict(self.settings.pinned_host_keys)
        ).resolve_host_key(device.host_key_reference)
        digest = hashlib.sha256(pinned.key.asbytes()).digest()
        return "SHA256:" + base64.b64encode(digest).decode().rstrip("=")


class _RemoteViews:
    def __init__(self, backend: RemoteAuthorityBackend, run_store: RunStore) -> None:
        from coreelec_reconciler.execution.authority import _RemoteAuthority

        self._remote = _RemoteAuthority(backend)
        self._run_store = run_store

    def read_ownership(self, device_id: DeviceId) -> RemoteOwnership:
        snapshot = self._remote.inspect(device_id.value)
        if (
            snapshot.presence is not Presence.PRESENT
            or snapshot.identity is None
            or snapshot.token_digest is None
            or snapshot.generation is None
            or snapshot.phase is None
            or snapshot.marker_digest is None
        ):
            raise ValueError("remote ownership is unavailable or invalid")
        return RemoteOwnership(
            snapshot.identity,
            snapshot.token_digest,
            snapshot.generation,
            snapshot.phase,
            snapshot.marker_digest,
        )

    def read_remote_ownership(self, run_id: RunId) -> RemoteOwnershipSnapshot:
        identity = self._run_store.load_identity(run_id)
        return self._remote.inspect(cast(str, identity["device_id"]))

    def read_remote_quarantine(self, run_id: RunId) -> Presence:
        identity = self._run_store.load_identity(run_id)
        return self._remote.inspect_quarantine(cast(str, identity["device_id"]))

    def live_helper(self, run_id: RunId) -> bool | None:
        del run_id
        return None


class _DeviceAuthorityProbe:
    def __init__(
        self,
        session: _ProductionDeviceSession,
        expected_device: Mapping[str, object],
        platform_identity: str,
        host_key_fingerprint: str,
    ) -> None:
        self._session = session
        self._expected_device = dict(expected_device)
        self._platform_identity = platform_identity
        self._host_key_fingerprint = host_key_fingerprint

    def observe_authority(self, device_id: DeviceId) -> DeviceAuthorityObservation:
        identity = self._session.identity
        if identity.device_id != device_id or not identity.boot_id:
            raise ValueError("Device session identity changed")
        return DeviceAuthorityObservation(
            device_id,
            _digest_object(self._expected_device),
            identity.boot_id,
            self._platform_identity,
            self._host_key_fingerprint,
        )


class _RunBindings:
    def __init__(self) -> None:
        self._services: dict[str, BoundExecutionServices] = {}

    def put(self, run_id: RunId, services: BoundExecutionServices) -> None:
        self._services[run_id.value] = services

    def get(self, run_id: RunId) -> BoundExecutionServices:
        try:
            return self._services[run_id.value]
        except KeyError:
            raise RuntimeError("execution services are not bound") from None

    def remove(self, run_id: RunId) -> None:
        self._services.pop(run_id.value, None)


class _ProductionMarkerController:
    def __init__(
        self,
        run_id: RunId,
        bindings: _RunBindings,
        authority: AuthorityCoordinator,
        remote: _RemoteViews,
        clock: RuntimeValues,
    ) -> None:
        self._run_id = run_id
        self._bindings = bindings
        self._authority = authority
        self._remote = remote
        self._clock = clock

    def advance(
        self, target: RemoteMarkerPhase, evidence_digest: str | None = None
    ) -> None:
        services = self._bindings.get(self._run_id)
        acquired = services.authorities.load(self._run_id)
        for phase in _phase_path(acquired.ownership.phase, target):
            acquired = self._authority.checkpoint(
                acquired,
                acquired.ownership.phase,
                phase,
                (
                    evidence_digest
                    if phase is RemoteMarkerPhase.TERMINAL_RELEASE_PENDING
                    else None
                ),
                updated_at=self._clock.utc_now(),
            )
            services.authorities.save(self._run_id, acquired)

    def marker(self, primitive: PrimitiveKind) -> MarkerCheckpoint:
        target = (
            RemoteMarkerPhase.TERMINAL_RELEASE_PENDING
            if primitive is PrimitiveKind.CLEANUP
            else RemoteMarkerPhase.MUTATING
        )
        self.advance(target)
        ownership = self._bindings.get(self._run_id).authorities.load(self._run_id)
        return MarkerCheckpoint(
            ownership.ownership.identity,
            ownership.ownership.token_digest,
            ownership.ownership.generation,
            ownership.ownership.phase,
            ownership.ownership.marker_digest,
        )

    def verify(self, marker: MarkerCheckpoint) -> None:
        actual = self._remote.read_ownership(marker.identity.device_id)
        if (
            actual.identity != marker.identity
            or actual.token_digest != marker.token_digest
            or actual.generation != marker.generation
            or actual.phase is not marker.phase
            or actual.marker_digest != marker.marker_digest
        ):
            raise ValueError("remote ownership marker changed")


class _ManagedFileLifecycle:
    def __init__(
        self, executor: ManagedFileLifecycle, marker: _ProductionMarkerController
    ) -> None:
        self._executor = executor
        self._marker = marker

    def apply(
        self,
        prepared: PreparedManagedFile,
        *,
        resource_id: str,
        change_id: str,
        rollback_approved: bool,
        verify: Callable[[ManagedFileObservation], bool | None] | None = None,
    ) -> ManagedFileExecutionResult:
        self._marker.advance(RemoteMarkerPhase.MUTATING)
        result = self._executor.apply(
            prepared,
            resource_id=resource_id,
            change_id=change_id,
            rollback_approved=rollback_approved,
            verify=verify,
        )
        self._marker.advance(RemoteMarkerPhase.VERIFYING)
        return result

    def rollback(
        self,
        prepared: PreparedManagedFile,
        *,
        resource_id: str,
        change_id: str,
    ) -> tuple[MutationTrace | None, ManagedFileVerification]:
        self._marker.advance(RemoteMarkerPhase.ROLLING_BACK)
        result = self._executor.rollback(
            prepared, resource_id=resource_id, change_id=change_id
        )
        self._marker.advance(RemoteMarkerPhase.VERIFYING)
        return result

    def cleanup(
        self,
        prepared: PreparedManagedFile,
        *,
        resource_id: str,
        change_id: str,
        terminal_evidence_ref: str,
    ) -> MutationTrace:
        self._marker.advance(
            RemoteMarkerPhase.TERMINAL_RELEASE_PENDING,
            terminal_evidence_ref,
        )
        return self._executor.cleanup(
            prepared,
            resource_id=resource_id,
            change_id=change_id,
            terminal_evidence_ref=terminal_evidence_ref,
        )


class _LifecycleFactory:
    def __init__(
        self,
        files: ManagedFileCapabilities,
        bindings: _RunBindings,
        authority: AuthorityCoordinator,
        remote: _RemoteViews,
        clock: RuntimeValues,
    ) -> None:
        self._files = files
        self._bindings = bindings
        self._authority = authority
        self._remote = remote
        self._clock = clock

    def lifecycle(
        self,
        run_id: RunId,
        resource_id: str,
        attachments: AttachmentStore,
        intent_checkpoint: Callable[[MutationIntent], None],
        outcome_checkpoint: Callable[[MutationTrace, ManagedFileObservation], None],
    ) -> ManagedFileLifecycle:
        del resource_id
        from coreelec_reconciler.execution.managed_file import ManagedFileExecutor

        marker = _ProductionMarkerController(
            run_id,
            self._bindings,
            self._authority,
            self._remote,
            self._clock,
        )
        executor = ManagedFileExecutor(
            self._files,
            attachments,
            intent_checkpoint,
            marker.marker,
            marker.verify,
            outcome_checkpoint,
        )
        return _ManagedFileLifecycle(executor, marker)


@dataclass(slots=True)
class _BoundRun:
    prepared: PreparedExecution
    session: DeviceSession
    bindings: _RunBindings

    def close(self) -> None:
        self.bindings.remove(self.prepared.approved_plan.run_id)
        try:
            self.prepared.services.close()
        finally:
            self.session.close()


class _ProductionExecutionRouter:
    def __init__(self, services: ProductionServices) -> None:
        self._services = services
        self._prepared: dict[str, _BoundRun] = {}

    def register(
        self,
        prepared: PreparedExecution,
        session: DeviceSession,
        bindings: _RunBindings,
    ) -> None:
        run_id = prepared.approved_plan.run_id
        self._prepared[run_id.value] = _BoundRun(prepared, session, bindings)

    def start(self, approved_plan: ApprovedPlan) -> ExecutionOutcome:
        try:
            bound = self._prepared.pop(approved_plan.run_id.value)
        except KeyError:
            raise CapabilityUnavailableError(
                "apply", "production.execution-binding-unavailable"
            ) from None
        try:
            return bound.prepared.services.engine.start(approved_plan)
        finally:
            bound.close()

    def inspect(self, run_id: RunId) -> RecoveryInspection:
        return cast(RecoveryInspection, self._with_recovery(run_id, "inspect", None))

    def recover(self, run_id: RunId, request: RecoveryRequest) -> ExecutionOutcome:
        return cast(ExecutionOutcome, self._with_recovery(run_id, "recover", request))

    def _with_recovery(
        self,
        run_id: RunId,
        command: str,
        request: RecoveryRequest | None,
    ) -> object:
        try:
            factory, session, bindings = _execution_factory_for_run(
                self._services, run_id
            )
            bound = factory.bind(run_id)
            bindings.put(run_id, bound)
        except (FileNotFoundError, PlanStoreError, ValueError, RuntimeError) as error:
            raise CapabilityUnavailableError(
                "recover", f"production.{command}-unavailable"
            ) from error
        try:
            if request is None:
                return bound.engine.inspect(run_id)
            return bound.engine.recover(run_id, request)
        finally:
            bindings.remove(run_id)
            try:
                bound.close()
            finally:
                session.close()


class _ProductionApplicationData:
    def __init__(
        self,
        services: ProductionServices,
        plan_repository: Callable[[PlanCommand], PlanOutcome],
        router: _ProductionExecutionRouter,
    ) -> None:
        self._services = services
        self._plan_repository = plan_repository
        self._router = router

    def observe(
        self, command: ObserveCommand
    ) -> ObservationOutcome | UnsupportedOutcome:
        planned = self._plan_repository(
            PlanCommand(command.repository_root, command.device_id)
        )
        if planned.run_report is None:
            return _unavailable("observe", "production.observation-unavailable")
        return ObservationOutcome(planned.run_report)

    def plan(self, command: PlanCommand) -> PlanOutcome:
        return self._plan_repository(command)

    def approved_plan(
        self, plan_id: PlanId, approval_scopes: tuple[str, ...]
    ) -> ApprovedPlan | UnsupportedOutcome:
        try:
            prepared, session, bindings = _prepare_execution(
                self._services, plan_id, approval_scopes
            )
        except FileNotFoundError, PlanStoreError, ValueError, RuntimeError:
            return _unavailable("apply", "production.saved-plan-rejected")
        self._router.register(prepared, session, bindings)
        return prepared.approved_plan

    def resolve_approval(
        self,
        plan: CanonicalPlan,
        approval_scopes: tuple[str, ...],
    ) -> ApprovalResolution:
        value = decode_json_object(plan.canonical_bytes)
        requirements = value.get("approval_requirements")
        required = (
            tuple(
                str(item["scope"])
                for item in requirements
                if isinstance(item, dict) and isinstance(item.get("scope"), str)
            )
            if isinstance(requirements, list)
            else ()
        )
        granted = tuple(scope for scope in approval_scopes if scope in required)
        return ApprovalResolution(
            required,
            granted,
            tuple(scope for scope in required if scope not in granted),
        )

    def verify(self, command: VerifyCommand) -> VerifyOutcome | UnsupportedOutcome:
        planned = self._plan_repository(
            PlanCommand(command.repository_root, command.device_id)
        )
        if planned.run_report is None:
            return _unavailable("verify", "production.verification-unavailable")
        return VerifyOutcome(planned.run_report)

    def report(self, command: ReportCommand) -> ReportOutcome | UnsupportedOutcome:
        if not self._services.state_root_exists():
            return _unavailable("report", "production.run-not-found")
        from coreelec_reconciler.execution.run_store import RunStoreError
        from coreelec_reconciler.reporting.execution_documents import (
            decode_execution_run_report,
        )

        try:
            chain = self._services.run_store().load_chain(command.run_id)
            return ReportOutcome(decode_execution_run_report(chain.head.payload))
        except FileNotFoundError, RunStoreError, ValueError:
            return _unavailable("report", "production.run-unavailable")


def _unavailable(command: str, code: str) -> UnsupportedOutcome:
    return UnsupportedOutcome(command, UnsupportedReason.CAPABILITY_UNAVAILABLE, code)


def _digest_object(value: Mapping[str, object]) -> str:
    from coreelec_reconciler.domain.canonical_json import canonical_document_bytes

    return "sha256:" + hashlib.sha256(canonical_document_bytes(value)).hexdigest()


def _phase_path(
    current: RemoteMarkerPhase, target: RemoteMarkerPhase
) -> tuple[RemoteMarkerPhase, ...]:
    if current is target:
        return ()
    if target is RemoteMarkerPhase.MUTATING:
        paths = {
            RemoteMarkerPhase.ACQUIRED: (
                RemoteMarkerPhase.PREPARING,
                RemoteMarkerPhase.PREPARED,
                RemoteMarkerPhase.MUTATING,
            ),
            RemoteMarkerPhase.PREPARING: (
                RemoteMarkerPhase.PREPARED,
                RemoteMarkerPhase.MUTATING,
            ),
            RemoteMarkerPhase.PREPARED: (RemoteMarkerPhase.MUTATING,),
        }
    elif target is RemoteMarkerPhase.VERIFYING:
        paths = {
            RemoteMarkerPhase.MUTATING: (RemoteMarkerPhase.VERIFYING,),
            RemoteMarkerPhase.ROLLING_BACK: (RemoteMarkerPhase.VERIFYING,),
        }
    elif target is RemoteMarkerPhase.ROLLING_BACK:
        paths = {
            RemoteMarkerPhase.MUTATING: (RemoteMarkerPhase.ROLLING_BACK,),
            RemoteMarkerPhase.VERIFYING: (RemoteMarkerPhase.ROLLING_BACK,),
        }
    elif target is RemoteMarkerPhase.TERMINAL_RELEASE_PENDING:
        paths = {
            RemoteMarkerPhase.ACQUIRED: (RemoteMarkerPhase.TERMINAL_RELEASE_PENDING,),
            RemoteMarkerPhase.PREPARING: (RemoteMarkerPhase.TERMINAL_RELEASE_PENDING,),
            RemoteMarkerPhase.PREPARED: (RemoteMarkerPhase.TERMINAL_RELEASE_PENDING,),
            RemoteMarkerPhase.MUTATING: (
                RemoteMarkerPhase.VERIFYING,
                RemoteMarkerPhase.TERMINAL_RELEASE_PENDING,
            ),
            RemoteMarkerPhase.VERIFYING: (RemoteMarkerPhase.TERMINAL_RELEASE_PENDING,),
            RemoteMarkerPhase.ROLLING_BACK: (
                RemoteMarkerPhase.TERMINAL_RELEASE_PENDING,
            ),
        }
    else:
        paths = {}
    try:
        return paths[current]
    except KeyError:
        raise ValueError(
            "remote ownership phase cannot reach requested phase"
        ) from None


def _configuration(
    services: ProductionServices,
    repository_root: str,
    device_id: DeviceId,
) -> ResolvedConfiguration:
    from coreelec_reconciler.config.load import load_configuration

    loaded = load_configuration(
        repository_root or services.settings.repository_root,
        device_id,
        (SelectorId("selector.skin"),),
    )
    if loaded.configuration is None:
        raise ValueError("resolved Device configuration is unavailable")
    return loaded.configuration


def _workspace_key() -> str:
    return hashlib.sha256(b"coreelec-reconciler").hexdigest()


def _remote_backend(session: _ProductionDeviceSession) -> RemoteAuthorityBackend:
    return session.remote_ownership(_workspace_key())


def _execution_factory(
    services: ProductionServices,
    configuration: ResolvedConfiguration,
    session: DeviceSession,
    expected_device: Mapping[str, object],
    change_ids: Mapping[str, str],
) -> tuple[ProductionExecutionFactory, _RunBindings]:
    from coreelec_reconciler.execution.run_adapters import (
        ConfigurationResourceContexts,
    )
    from coreelec_reconciler.resource_types.builtins import (
        built_in_resource_registry,
    )

    production_session = cast(_ProductionDeviceSession, session)
    backend = _remote_backend(production_session)
    remote = _RemoteViews(backend, services.run_store())
    authority = AuthorityCoordinator(
        services.run_store(),
        services.runtime,
        backend,
    )
    bindings = _RunBindings()
    lifecycles = _LifecycleFactory(
        production_session.managed_file_mutations,
        bindings,
        authority,
        remote,
        services.runtime,
    )
    contexts = ConfigurationResourceContexts(
        configuration,
        production_session.managed_file_mutations,
        cast(ManagedFileLifecycleFactory, lifecycles),
        dict(change_ids),
        lambda run_id: _digest_object(expected_device),
        services.runtime.utc_now,
    )
    platform_identity = production_session.identity.binding_digest
    device = configuration.device
    if device is None:
        raise ValueError("resolved Device capabilities are unavailable")
    factory = ProductionExecutionFactory(
        services.plan_store(),
        services.run_store(),
        built_in_resource_registry(),
        {resource.id.value: resource.type for resource in configuration.resources},
        contexts,
        remote,
        _DeviceAuthorityProbe(
            production_session,
            expected_device,
            platform_identity,
            services.host_key_fingerprint(device),
        ),
        authority,
        remote,
        services.runtime,
    )
    return factory, bindings


def _prepare_execution(
    services: ProductionServices,
    plan_id: PlanId,
    approval_scopes: tuple[str, ...],
) -> tuple[PreparedExecution, DeviceSession, _RunBindings]:
    saved = services.plan_store().load(plan_id)
    value = decode_json_object(saved.plan.canonical_bytes)
    device_value = value.get("device")
    if not isinstance(device_value, dict):
        raise ValueError("saved Plan Device is malformed")
    configuration = _configuration(
        services,
        services.settings.repository_root,
        saved.device_id,
    )
    device = configuration.device
    if device is None:
        raise ValueError("resolved Device capabilities are unavailable")
    session = services.open_device_session(
        device,
        frozenset(
            {
                "managed_file.read",
                "managed_file.write",
                "atomic_replace_over_existing",
                "remote_run_ownership",
            }
        ),
    )
    try:
        change_ids = _change_ids(value)
        factory, bindings = _execution_factory(
            services, configuration, session, device_value, change_ids
        )
        now = services.runtime.utc_now()
        request = SavedPlanExecutionRequest(
            plan_id,
            RunId(services.runtime.new_uuid7()),
            saved.device_id,
            saved.originating_run_id,
            device_value,
            dict(saved.input_digests),
            tuple(
                ApprovalGrant(
                    scope,
                    "actor.local-admin",
                    "noninteractive_cli",
                    now,
                )
                for scope in approval_scopes
            ),
            now,
        )
        prepared = factory.approve_saved_plan(request)
        bindings.put(prepared.approved_plan.run_id, prepared.services)
        return prepared, session, bindings
    except Exception:
        session.close()
        raise


def _execution_factory_for_run(
    services: ProductionServices,
    run_id: RunId,
) -> tuple[ProductionExecutionFactory, DeviceSession, _RunBindings]:
    identity = services.run_store().load_identity(run_id)
    device_id = DeviceId(cast(str, identity["device_id"]))
    plan_id = PlanId(cast(str, identity["plan_id"]))
    saved = services.plan_store().load(plan_id)
    plan_value = decode_json_object(saved.plan.canonical_bytes)
    device_value = plan_value.get("device")
    if not isinstance(device_value, dict):
        raise ValueError("saved Plan Device is malformed")
    configuration = _configuration(
        services,
        services.settings.repository_root,
        device_id,
    )
    device = configuration.device
    if device is None:
        raise ValueError("resolved Device capabilities are unavailable")
    session = services.open_device_session(
        device,
        frozenset(
            {
                "managed_file.read",
                "managed_file.write",
                "atomic_replace_over_existing",
                "remote_run_ownership",
            }
        ),
    )
    try:
        factory, bindings = _execution_factory(
            services,
            configuration,
            session,
            device_value,
            _change_ids(plan_value),
        )
        return factory, session, bindings
    except Exception:
        session.close()
        raise


def _change_ids(plan: Mapping[str, object]) -> dict[str, str]:
    result: dict[str, str] = {}
    resources = plan.get("resources")
    if not isinstance(resources, list):
        raise ValueError("saved Plan Resources are malformed")
    for resource in resources:
        if not isinstance(resource, dict):
            raise ValueError("saved Plan Resource is malformed")
        resource_id = resource.get("resource_id")
        changes = resource.get("changes")
        if not isinstance(resource_id, str) or not isinstance(changes, list):
            raise ValueError("saved Plan Resource binding is malformed")
        if changes:
            change = changes[0]
            if not isinstance(change, dict) or not isinstance(
                change.get("change_id"), str
            ):
                raise ValueError("saved Plan Change binding is malformed")
            result[resource_id] = cast(str, change["change_id"])
    return result


def bootstrap(settings: BootstrapSettings) -> Reconciler:
    from coreelec_reconciler.application.supplied_observations import (
        load_supplied_planning_input,
    )
    from coreelec_reconciler.config.load import load_configuration
    from coreelec_reconciler.reporting.planning_documents import (
        build_multi_resource_plan_and_run,
        build_plan_and_run,
    )
    from coreelec_reconciler.resource_types.kodi_smart_playlist.execution import (
        planning_observation,
    )
    from coreelec_reconciler.resource_types.kodi_smart_playlist.planning import (
        assess_playlist,
    )
    from coreelec_reconciler.resource_types.managed_file.observation import (
        observe_managed_file,
    )
    from coreelec_reconciler.resource_types.managed_file.paths import (
        resolve_special_profile_path,
    )

    def validate_repository(command: ValidateCommand) -> ValidationOutcome:
        root = command.repository_root or settings.repository_root
        validation = validate_ledger(Path(root) / "inventory" / "ownership-ledger.json")
        diagnostics = [
            " ".join(
                part
                for part in (
                    diagnostic.code,
                    diagnostic.inventory_id,
                    diagnostic.field,
                    diagnostic.message,
                )
                if part
            )
            for diagnostic in validation.diagnostics
        ]
        if command.device_id is not None:
            loaded = load_configuration(
                root,
                command.device_id,
                (SelectorId("selector.skin"),),
            )
            diagnostics.extend(
                f"{item.code} {item.source} {item.message}"
                for item in loaded.diagnostics
            )
            if command.observations_file is None:
                diagnostics.append(
                    "observation.missing supplied observations are required"
                )
            else:
                try:
                    supplied = load_supplied_planning_input(command.observations_file)
                except ValueError as error:
                    diagnostics.append(f"observation.invalid {error}")
                else:
                    if loaded.configuration is not None:
                        resource = loaded.configuration.resources[0]
                        if supplied.observation.resource_id != resource.id.value:
                            diagnostics.append(
                                "observation.resource-mismatch supplied Resource ID "
                                "does not match selection"
                            )
                        if (
                            supplied.observation.state_address
                            not in resource.state_addresses
                        ):
                            diagnostics.append(
                                "observation.address-mismatch supplied State Address "
                                "does not match selection"
                            )
        return ValidationOutcome(
            valid=validation.valid and not diagnostics,
            diagnostics=tuple(diagnostics),
            row_count=validation.row_count,
            sha256=validation.sha256,
            role_totals=tuple(validation.role_totals.items()),
            disposition_totals=tuple(validation.disposition_totals.items()),
        )

    def plan_repository(command: PlanCommand) -> PlanOutcome:
        loaded = load_configuration(
            command.repository_root or settings.repository_root,
            command.device_id,
            (SelectorId("selector.skin"),),
        )
        if loaded.configuration is None:
            return PlanOutcome(
                run_id=RunId("unavailable"),
                plan_id=None,
                disposition="blocked",
                diagnostics=tuple(
                    f"{item.code} {item.source} {item.message}"
                    for item in loaded.diagnostics
                ),
            )
        if command.observations_file is not None:
            try:
                supplied = load_supplied_planning_input(command.observations_file)
            except ValueError as error:
                return PlanOutcome(
                    run_id=RunId("unavailable"),
                    plan_id=None,
                    disposition="blocked",
                    diagnostics=(f"observation.invalid {error}",),
                )
            if len(loaded.configuration.resources) != 1:
                return PlanOutcome(
                    run_id=RunId(supplied.runtime.planning_run_id),
                    plan_id=None,
                    disposition="blocked",
                    diagnostics=("selection.invalid expected exactly one Resource",),
                )
            resource = loaded.configuration.resources[0]
            if (
                supplied.observation.resource_id != resource.id.value
                or supplied.observation.state_address not in resource.state_addresses
            ):
                return PlanOutcome(
                    run_id=RunId(supplied.runtime.planning_run_id),
                    plan_id=None,
                    disposition="blocked",
                    diagnostics=("observation.binding-mismatch",),
                )
            assessment = assess_playlist(
                resource.intent,
                resource.desired,
                resource.management,
                supplied.observation,
            )
            plan, run = build_plan_and_run(
                loaded.configuration,
                resource,
                supplied,
                assessment,
            )
        else:
            device = loaded.configuration.device
            if device is None:
                return PlanOutcome(
                    run_id=RunId("unavailable"),
                    plan_id=None,
                    disposition="blocked",
                    diagnostics=("device.capabilities-unavailable",),
                )
            try:
                session = services.open_device_session(
                    device, frozenset({"managed_file.read"})
                )
            except RuntimeError:
                return PlanOutcome(
                    run_id=RunId("unavailable"),
                    plan_id=None,
                    disposition="blocked",
                    diagnostics=("device.session-unavailable",),
                )
            try:
                started_at = services.runtime.utc_now()
                runtime = PlanningRuntime(
                    planning_run_id=services.runtime.new_uuid7(),
                    plan_id=services.runtime.new_uuid7(),
                    started_at=started_at,
                    created_at=started_at,
                    ended_at=started_at,
                    expires_at=(
                        datetime.fromisoformat(started_at.replace("Z", "+00:00"))
                        + timedelta(hours=1)
                    )
                    .astimezone(UTC)
                    .isoformat()
                    .replace("+00:00", "Z"),
                    endpoint_host=device.endpoint.host,
                    endpoint_port=device.endpoint.port,
                    ssh_host_key_fingerprint=services.host_key_fingerprint(device),
                    platform_identity_fingerprint=session.identity.binding_digest,
                    controller_capabilities_digest=_digest_object(
                        {
                            "atomic_replace_over_existing": (
                                session.capabilities.atomic_replace_over_existing
                            ),
                            "profile_root": device.profile_root.path,
                        }
                    ),
                    artifact_resolution_digest=_digest_object(
                        {
                            "artifacts": [
                                {
                                    "id": artifact.id.value,
                                    "distribution_sha256": artifact.distribution_sha256,
                                }
                                for artifact in loaded.configuration.artifacts
                            ]
                        }
                    ),
                )
                entries = []
                for resource in loaded.configuration.resources:
                    if len(resource.state_addresses) != 1:
                        raise ValueError(
                            "managed-file Resource requires one State Address"
                        )
                    address = resolve_special_profile_path(
                        resource.state_addresses[0], device.profile_root
                    )
                    observed = observe_managed_file(
                        session.managed_files, address, read_limit=1_048_576
                    )
                    supplied = SuppliedPlanningInput(
                        runtime,
                        planning_observation(
                            resource.id.value,
                            started_at,
                            observed,
                        ),
                    )
                    entries.append(
                        (
                            resource,
                            supplied,
                            assess_playlist(
                                resource.intent,
                                resource.desired,
                                resource.management,
                                supplied.observation,
                            ),
                        )
                    )
                plan, run = build_multi_resource_plan_and_run(
                    loaded.configuration,
                    tuple(entries),
                )
            except (ValueError, RuntimeError) as error:
                return PlanOutcome(
                    run_id=RunId("unavailable"),
                    plan_id=None,
                    disposition="blocked",
                    diagnostics=(f"observation.invalid {error}",),
                )
            finally:
                session.close()
        services.plan_store().save(plan, run)
        return PlanOutcome(
            run_id=RunId(run.run_id),
            plan_id=PlanId(plan.plan_id),
            disposition=plan.disposition.value,
            plan=plan,
            run_report=run,
        )

    services = ProductionServices(settings, os.environ)
    router = _ProductionExecutionRouter(services)
    data = _ProductionApplicationData(services, plan_repository, router)
    return ApplicationReconciler(
        dependencies=ApplicationDependencies(
            ExecutionApplicationWorkflows(data, cast(ExecutionEngine, router)),
            validate_repository,
            plan_repository,
        ),
    )
