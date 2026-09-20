"""Canonical, restart-safe, observation-only Resource execution."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

from coreelec_reconciler.domain.canonical_json import decode_json_object
from coreelec_reconciler.domain.configuration import ProfileRootCapability
from coreelec_reconciler.domain.execution import AttachmentRef, RevisionLease
from coreelec_reconciler.domain.identifiers import DeviceId, RunId
from coreelec_reconciler.domain.observation import (
    TERMINAL_OBSERVATION_STATUSES,
    CanonicalObservationRun,
    ObservationAppendIntent,
    ObservationRunStatus,
)
from coreelec_reconciler.execution.run_store import RunStore
from coreelec_reconciler.execution.runtime import RuntimeValues
from coreelec_reconciler.persistence.observation_documents import (
    build_observation_run,
)
from coreelec_reconciler.resource_types.registry import ResourceRegistry
from coreelec_reconciler.transports.interfaces import ManagedFileReader, ReadResult


@dataclass(frozen=True, slots=True)
class ObservationInputDigests:
    configuration: str
    profile: str
    artifact_set: str
    capability: str
    selector: str


@dataclass(frozen=True, slots=True)
class ObservationResourceContext:
    device_id: DeviceId
    resource_id: str
    resource_type: str
    state_addresses: tuple[str, ...]
    profile_root: ProfileRootCapability | None
    reader: ManagedFileReader


@dataclass(frozen=True, slots=True)
class ObservationResource:
    resource_id: str
    resource_type: str
    state_addresses: tuple[str, ...]
    requires: tuple[str, ...]
    context: ObservationResourceContext


@dataclass(frozen=True, slots=True)
class ObservationRunRequest:
    run_id: RunId
    device_id: DeviceId
    inputs: ObservationInputDigests
    resources: tuple[ObservationResource, ...]


@dataclass(frozen=True, slots=True)
class ObservationRunInspection:
    run: CanonicalObservationRun
    completed_resource_ids: tuple[str, ...]
    remaining_resource_ids: tuple[str, ...]

    @property
    def terminal(self) -> bool:
        return self.run.status in TERMINAL_OBSERVATION_STATUSES


class CanonicalObservationRuns:
    """Persist fresh Resource observations without Desired State or authority."""

    def __init__(
        self,
        store: RunStore,
        registry: ResourceRegistry,
        runtime: RuntimeValues,
    ) -> None:
        self._store = store
        self._registry = registry
        self._runtime = runtime

    def start(self, request: ObservationRunRequest) -> CanonicalObservationRun:
        scope = _scope(request, self._registry)
        started_at = self._runtime.utc_now()
        initial = build_observation_run(
            {
                "checkpoints": [],
                "completed_resource_ids": [],
                "device_id": request.device_id.value,
                "ended_at": None,
                "kind": "CoreElecReconcilerObservationRun",
                "previous_revision_digest": None,
                "producer": {"name": "coreelec-reconciler", "version": "0.1.0"},
                "revision": 1,
                "run_id": request.run_id.value,
                "schema_version": 1,
                "scope": scope,
                "started_at": started_at,
                "status": ObservationRunStatus.READY.value,
                "workspace_id": f"workspace:{request.run_id.value}",
            },
            resource_registry=self._registry,
        )
        device_lease = self._store.acquire_device(request.device_id)
        try:
            lease, _ = self._store.create_observation_run(
                device_lease,
                request.run_id,
                request.device_id,
                initial.canonical_bytes,
            )
        finally:
            self._store.release_device(device_lease)
        try:
            return self._continue(request, lease)
        finally:
            self._store.release_run(lease)

    def restart(self, request: ObservationRunRequest) -> CanonicalObservationRun:
        expected_scope = _scope(request, self._registry)
        lease = self._store.acquire_run(request.run_id)
        try:
            stored = self._load(request.run_id)
            if (
                stored.device_id != request.device_id.value
                or _scope_value(stored) != expected_scope
            ):
                raise ValueError("observation restart scope binding changed")
            return self._continue(request, lease)
        finally:
            self._store.release_run(lease)

    def report(self, run_id: RunId) -> CanonicalObservationRun:
        return self._load(run_id)

    def inspect(self, run_id: RunId) -> ObservationRunInspection:
        run = self._load(run_id)
        completed = tuple(item.resource_id for item in run.checkpoints)
        return ObservationRunInspection(
            run,
            completed,
            tuple(item.resource_id for item in run.scope.resources[len(completed) :]),
        )

    def _load(self, run_id: RunId) -> CanonicalObservationRun:
        loaded = self._store.load_observation_run(run_id)
        if not isinstance(loaded, CanonicalObservationRun):
            raise TypeError("Run is not a canonical observation Run")
        return loaded

    def _continue(
        self,
        request: ObservationRunRequest,
        lease: RevisionLease,
    ) -> CanonicalObservationRun:
        current = self._load(request.run_id)
        _validate_completed_prefix(current, request.resources)
        if current.status in TERMINAL_OBSERVATION_STATUSES:
            return current
        if current.status is ObservationRunStatus.READY:
            current = self._append(
                lease,
                current,
                ObservationRunStatus.OBSERVING,
                None,
            )
        completed = len(current.checkpoints)
        for index, resource in enumerate(request.resources[completed:], completed):
            descriptor = self._registry.descriptor(resource.resource_type)
            if descriptor is None or descriptor.encode_observation_evidence is None:
                raise ValueError("Resource Type has no registered observation encoder")
            encoded = descriptor.encode_observation_evidence(
                descriptor.observe(_scoped_context(resource.context))
            )
            if encoded.state_addresses != resource.state_addresses:
                raise ValueError(
                    "Observation is outside selected Resource State Addresses"
                )
            attachments: tuple[AttachmentRef, ...] = ()
            if encoded.raw_content is not None:
                attachments = (
                    self._store.attach(
                        lease,
                        "raw-observation",
                        "raw-bytes-v1",
                        encoded.raw_content,
                    ),
                )
            terminal = index + 1 == len(request.resources)
            status = (
                _terminal_status(current, encoded.disposition.value)
                if terminal
                else ObservationRunStatus.OBSERVING
            )
            checkpoint = {
                "disposition": encoded.disposition.value,
                "evidence": {
                    "payload": dict(encoded.payload),
                    "payload_kind": descriptor.observation_payload_kind,
                    "payload_schema_version": descriptor.observation_payload_version,
                },
                "observed_at": self._runtime.utc_now(),
                "observer": {
                    "code": encoded.observer_code,
                    "version": encoded.observer_version,
                },
                "raw_attachments": [
                    {
                        "codec": item.codec,
                        "digest": item.digest,
                        "kind": item.kind,
                    }
                    for item in attachments
                ],
                "resource_id": resource.resource_id,
                "resource_type": resource.resource_type,
                "sequence": index + 1,
                "state_addresses": list(resource.state_addresses),
            }
            current = self._append(lease, current, status, checkpoint)
        return current

    def _append(
        self,
        lease: RevisionLease,
        current: CanonicalObservationRun,
        status: ObservationRunStatus,
        checkpoint: Mapping[str, object] | None,
    ) -> CanonicalObservationRun:
        value = _run_value(current)
        checkpoints = list(cast(list[dict[str, object]], value["checkpoints"]))
        if checkpoint is not None:
            checkpoints.append(dict(checkpoint))
        terminal = status in TERMINAL_OBSERVATION_STATUSES
        value.update(
            {
                "checkpoints": checkpoints,
                "completed_resource_ids": [
                    str(item["resource_id"]) for item in checkpoints
                ],
                "ended_at": self._runtime.utc_now() if terminal else None,
                "previous_revision_digest": current.current_digest,
                "revision": current.revision + 1,
                "status": status.value,
            }
        )
        proposed = build_observation_run(value, resource_registry=self._registry)
        self._store.compare_and_append_observation(
            lease,
            current.revision,
            current.current_digest,
            proposed.canonical_bytes,
            ObservationAppendIntent(status, terminal),
        )
        return self._load(lease.run_id)


def _scope(
    request: ObservationRunRequest,
    registry: ResourceRegistry,
) -> dict[str, object]:
    if not request.resources:
        raise ValueError("observation requires at least one selected Resource")
    seen: set[str] = set()
    resources: list[dict[str, object]] = []
    for resource in request.resources:
        if resource.resource_id in seen:
            raise ValueError("observation Resource IDs must be unique")
        if any(required not in seen for required in resource.requires):
            raise ValueError("observation selection is not dependency ordered")
        descriptor = registry.descriptor(resource.resource_type)
        if (
            descriptor is None
            or descriptor.observation_payload_kind is None
            or descriptor.observation_payload_version is None
            or descriptor.observation_policy_digest is None
            or descriptor.encode_observation_evidence is None
            or descriptor.validate_observation_addresses is None
            or descriptor._observation_factory is None
        ):
            raise ValueError("Resource Type has no complete observation codec")
        descriptor.validate_observation_addresses(resource.state_addresses)
        _validate_context_binding(request, resource)
        resources.append(
            {
                "observation_codec": {
                    "kind": descriptor.observation_payload_kind,
                    "policy_digest": descriptor.observation_policy_digest,
                    "schema_version": descriptor.observation_payload_version,
                },
                "requires": list(resource.requires),
                "resource_id": resource.resource_id,
                "resource_type": resource.resource_type,
                "state_addresses": list(resource.state_addresses),
            }
        )
        seen.add(resource.resource_id)
    scope: dict[str, object] = {
        "artifact_set_digest": request.inputs.artifact_set,
        "capability_digest": request.inputs.capability,
        "configuration_digest": request.inputs.configuration,
        "profile_digest": request.inputs.profile,
        "resources": resources,
        "selector_digest": request.inputs.selector,
    }
    build_observation_run(
        {
            "checkpoints": [],
            "completed_resource_ids": [],
            "device_id": request.device_id.value,
            "ended_at": None,
            "kind": "CoreElecReconcilerObservationRun",
            "previous_revision_digest": None,
            "producer": {"name": "coreelec-reconciler", "version": "0.1.0"},
            "revision": 1,
            "run_id": request.run_id.value,
            "schema_version": 1,
            "scope": scope,
            "started_at": "2000-01-01T00:00:00Z",
            "status": "ready",
            "workspace_id": f"workspace:{request.run_id.value}",
        },
        resource_registry=registry,
    )
    return scope


@dataclass(frozen=True, slots=True)
class _ScopedObservationContext:
    device_id: DeviceId
    resource_id: str
    resource_type: str
    state_addresses: tuple[str, ...]
    profile_root: ProfileRootCapability | None
    _reader: ManagedFileReader

    def lstat(self, path: str) -> ReadResult:
        return self._reader.lstat(path)

    def read(self, path: str, limit: int) -> ReadResult:
        return self._reader.read(path, limit)


def _scoped_context(context: ObservationResourceContext) -> _ScopedObservationContext:
    return _ScopedObservationContext(
        context.device_id,
        context.resource_id,
        context.resource_type,
        context.state_addresses,
        context.profile_root,
        context.reader,
    )


def _validate_context_binding(
    request: ObservationRunRequest,
    resource: ObservationResource,
) -> None:
    context = resource.context
    if (
        context.device_id != request.device_id
        or context.resource_id != resource.resource_id
        or context.resource_type != resource.resource_type
        or context.state_addresses != resource.state_addresses
    ):
        raise ValueError("observation Resource context binding changed")


def _terminal_status(
    current: CanonicalObservationRun,
    next_disposition: str,
) -> ObservationRunStatus:
    dispositions = [checkpoint.disposition.value for checkpoint in current.checkpoints]
    dispositions.append(next_disposition)
    return (
        ObservationRunStatus.OBSERVED
        if all(item == "observed" for item in dispositions)
        else ObservationRunStatus.OBSERVED_PARTIAL
    )


def _validate_completed_prefix(
    run: CanonicalObservationRun,
    resources: tuple[ObservationResource, ...],
) -> None:
    expected = tuple(item.resource_id for item in resources[: len(run.checkpoints)])
    actual = tuple(item.resource_id for item in run.checkpoints)
    if actual != expected:
        raise ValueError("observation restart completed prefix changed")


def _scope_value(run: CanonicalObservationRun) -> dict[str, object]:
    return {
        "artifact_set_digest": run.scope.artifact_set_digest,
        "capability_digest": run.scope.capability_digest,
        "configuration_digest": run.scope.configuration_digest,
        "profile_digest": run.scope.profile_digest,
        "resources": [
            {
                "observation_codec": {
                    "kind": item.codec.kind,
                    "policy_digest": item.codec.policy_digest,
                    "schema_version": item.codec.schema_version,
                },
                "requires": list(item.requires),
                "resource_id": item.resource_id,
                "resource_type": item.resource_type,
                "state_addresses": list(item.state_addresses),
            }
            for item in run.scope.resources
        ],
        "selector_digest": run.scope.selector_digest,
    }


def _run_value(run: CanonicalObservationRun) -> dict[str, object]:
    return decode_json_object(run.canonical_bytes)
