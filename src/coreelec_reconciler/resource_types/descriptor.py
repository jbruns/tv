"""Immutable Resource Type descriptors."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol

from coreelec_reconciler.domain.configuration import (
    DesiredPresence,
    KodiSmartPlaylistIntent,
)
from coreelec_reconciler.domain.execution import (
    AttachmentRef,
    MutationDisposition,
    MutationReceipt,
    MutationTrace,
)
from coreelec_reconciler.domain.observation import ObservationDisposition

if TYPE_CHECKING:
    from coreelec_reconciler.domain.configuration import ProfileRootCapability, Resource
    from coreelec_reconciler.domain.identifiers import DeviceId
    from coreelec_reconciler.resource_types.managed_file.observation import (
        ManagedFileObservation,
    )
    from coreelec_reconciler.resource_types.managed_file.paths import (
        ResolvedManagedAddress,
    )
    from coreelec_reconciler.resource_types.managed_file.preparation import (
        PreparationBinding,
        PreparedManagedFile,
    )
    from coreelec_reconciler.transports.interfaces import ReadResult


@dataclass(frozen=True, slots=True)
class IntentValidationError(Exception):
    path: tuple[str | int, ...]
    safe_message: str


type IntentParser = Callable[
    [Mapping[str, object], DesiredPresence],
    KodiSmartPlaylistIntent,
]
type StateAddressResolver = Callable[
    [KodiSmartPlaylistIntent],
    tuple[str, ...],
]
type IntentEncoder = Callable[[KodiSmartPlaylistIntent], Mapping[str, object]]
type IntentDecoder = Callable[[Mapping[str, object]], KodiSmartPlaylistIntent]
type PlanEvidenceDecoder = Callable[
    [str, int, Mapping[str, object]],
    tuple[Mapping[str, object], str],
]
type ObservationEvidenceDecoder = Callable[
    [str, int, Mapping[str, object]],
    Mapping[str, object],
]


@dataclass(frozen=True, slots=True)
class EncodedObservationEvidence:
    payload: Mapping[str, object]
    disposition: ObservationDisposition
    raw_content: bytes | None
    state_addresses: tuple[str, ...]
    observer_code: str
    observer_version: int


type ObservationEvidenceEncoder = Callable[[object], EncodedObservationEvidence]
type ObservationEvidenceChecker = Callable[
    [object, object, object],
    tuple[str, ...],
]
type ObservationAddressValidator = Callable[[tuple[str, ...]], None]
type ObservationAddressChecker = Callable[[tuple[str, ...]], tuple[str, ...]]


class ResourceObservationContext(Protocol):
    """Read-only, identity-bound capabilities available during observation."""

    @property
    def device_id(self) -> DeviceId: ...

    @property
    def resource_id(self) -> str: ...

    @property
    def resource_type(self) -> str: ...

    @property
    def state_addresses(self) -> tuple[str, ...]: ...

    @property
    def profile_root(self) -> ProfileRootCapability | None: ...

    def lstat(self, path: str) -> ReadResult: ...

    def read(self, path: str, limit: int) -> ReadResult: ...


class ErasedResourceObserver(Protocol):
    def observe(self) -> object: ...


@dataclass(frozen=True, slots=True)
class ErasedResourceObserverAdapter[ObservationT]:
    observation_type: type[ObservationT]
    observe_typed: Callable[[], ObservationT]

    def observe(self) -> object:
        observation = self.observe_typed()
        if not isinstance(observation, self.observation_type):
            raise TypeError("Resource Observation type does not match descriptor")
        return observation


type ResourceObservationFactory = Callable[
    [ResourceObservationContext],
    ErasedResourceObserver,
]


class ErasedResourceExecution(Protocol):
    """Private heterogeneous execution seam; persisted values remain typed."""

    def observe(self) -> object: ...

    def assess(self, observation: object) -> object: ...

    def prepare(self, change: object) -> object: ...

    def apply(self, prepared: object) -> object: ...

    def rollback(self, prepared: object) -> object: ...

    def cleanup(self, prepared: object, terminal_evidence_ref: str) -> object: ...


class AttachmentStore(Protocol):
    def attach(self, kind: str, codec: str, payload: bytes) -> AttachmentRef: ...

    def read_attachment(self, reference: AttachmentRef) -> bytes: ...


@dataclass(frozen=True, slots=True)
class ErasedResourceExecutionAdapter[ObservationT, ChangeT, PreparedT]:
    """Runtime-checked erasure for one fully typed Resource implementation."""

    observation_type: type[ObservationT]
    change_type: type[ChangeT]
    prepared_type: type[PreparedT]
    observe_typed: Callable[[], ObservationT]
    assess_typed: Callable[[ObservationT], object]
    prepare_typed: Callable[[ChangeT], PreparedT]
    apply_typed: Callable[[PreparedT], object]
    rollback_typed: Callable[[PreparedT], object]
    cleanup_typed: Callable[[PreparedT, str], object]

    def observe(self) -> object:
        return self.observe_typed()

    def assess(self, observation: object) -> object:
        if not isinstance(observation, self.observation_type):
            raise TypeError("Resource Observation type does not match descriptor")
        return self.assess_typed(observation)

    def prepare(self, change: object) -> object:
        if not isinstance(change, self.change_type):
            raise TypeError("Resource Change type does not match descriptor")
        return self.prepare_typed(change)

    def apply(self, prepared: object) -> object:
        if not isinstance(prepared, self.prepared_type):
            raise TypeError("prepared Resource type does not match descriptor")
        return self.apply_typed(prepared)

    def rollback(self, prepared: object) -> object:
        if not isinstance(prepared, self.prepared_type):
            raise TypeError("prepared Resource type does not match descriptor")
        return self.rollback_typed(prepared)

    def cleanup(self, prepared: object, terminal_evidence_ref: str) -> object:
        if not isinstance(prepared, self.prepared_type):
            raise TypeError("prepared Resource type does not match descriptor")
        return self.cleanup_typed(prepared, terminal_evidence_ref)


class ManagedFileCapabilities(Protocol):
    """Least-authority primitives shared by Resource Types and execution."""

    def lstat(self, path: str) -> ReadResult: ...

    def read(self, path: str, limit: int) -> ReadResult: ...

    def stage_write(
        self, path: str, content: bytes, mode: int, operation_id: str
    ) -> MutationReceipt: ...

    def chmod(self, path: str, mode: int, operation_id: str) -> MutationReceipt: ...

    def atomic_replace(
        self, staged_path: str, destination: str, operation_id: str
    ) -> MutationReceipt: ...

    def remove(self, path: str, operation_id: str) -> MutationReceipt: ...

    def restore(
        self,
        path: str,
        content: bytes | None,
        mode: int | None,
        operation_id: str,
    ) -> MutationReceipt: ...

    def cleanup(self, path: str, operation_id: str) -> MutationReceipt: ...


class ManagedFileVerificationStatus(StrEnum):
    MATCHED = "matched"
    MISMATCH = "mismatch"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ManagedFileVerification:
    status: ManagedFileVerificationStatus
    observation: ManagedFileObservation


@dataclass(frozen=True, slots=True)
class ManagedFileExecutionResult:
    mutation: MutationTrace
    verification: ManagedFileVerification
    rollback: MutationTrace | None = None
    rollback_verification: ManagedFileVerification | None = None
    cleanup: MutationTrace | None = None

    @property
    def converged(self) -> bool:
        return self.verification.status is ManagedFileVerificationStatus.MATCHED

    @property
    def recovery_required(self) -> bool:
        return (
            self.verification.status is ManagedFileVerificationStatus.UNKNOWN
            or any(
                receipt.disposition is MutationDisposition.AMBIGUOUS
                for trace in (self.rollback, self.cleanup)
                if trace is not None
                for receipt in trace.receipts
            )
            or (
                self.rollback_verification is not None
                and self.rollback_verification.status
                is not ManagedFileVerificationStatus.MATCHED
            )
        )


class ManagedFileLifecycle(Protocol):
    def apply(
        self,
        prepared: PreparedManagedFile,
        *,
        resource_id: str,
        change_id: str,
        rollback_approved: bool,
        verify: Callable[[ManagedFileObservation], bool | None] | None = None,
    ) -> ManagedFileExecutionResult: ...

    def rollback(
        self,
        prepared: PreparedManagedFile,
        *,
        resource_id: str,
        change_id: str,
    ) -> tuple[MutationTrace | None, ManagedFileVerification]: ...

    def cleanup(
        self,
        prepared: PreparedManagedFile,
        *,
        resource_id: str,
        change_id: str,
        terminal_evidence_ref: str,
    ) -> MutationTrace: ...


@dataclass(frozen=True, slots=True)
class ResourceExecutionContext:
    """Capability-scoped inputs for one Device/Run Resource execution."""

    resource: Resource
    files: ManagedFileCapabilities
    attachments: AttachmentStore
    lifecycle: ManagedFileLifecycle
    address: ResolvedManagedAddress
    binding: PreparationBinding
    observed_at: Callable[[], str]


type ResourceExecutionFactory = Callable[
    [ResourceExecutionContext],
    ErasedResourceExecution,
]
type PreparedEncoder = Callable[[object], bytes]
type PreparedDecoder = Callable[[bytes, AttachmentStore], object]
type PlannedChangeDecoder = Callable[
    [Mapping[str, object], ResourceExecutionContext, bool],
    object,
]


@dataclass(frozen=True, slots=True)
class ResourceDescriptor:
    type_code: str
    parse_intent: IntentParser
    state_addresses: StateAddressResolver
    encode_intent: IntentEncoder
    decode_intent: IntentDecoder
    decode_plan_evidence: PlanEvidenceDecoder
    execution: ErasedResourceExecution | None = None
    execution_factory: ResourceExecutionFactory | None = None
    encode_prepared: PreparedEncoder | None = None
    decode_prepared: PreparedDecoder | None = None
    decode_planned_change: PlannedChangeDecoder | None = None
    observation_payload_kind: str | None = None
    observation_payload_version: int | None = None
    observation_policy_digest: str | None = None
    encode_observation_evidence: ObservationEvidenceEncoder | None = None
    decode_observation_evidence: ObservationEvidenceDecoder | None = None
    check_observation_evidence: ObservationEvidenceChecker | None = None
    validate_observation_addresses: ObservationAddressValidator | None = None
    check_observation_addresses: ObservationAddressChecker | None = None
    _observation_factory: ResourceObservationFactory | None = None

    def observe(self, context: ResourceObservationContext) -> object:
        if self._observation_factory is None:
            raise ValueError("Resource Type has no observation factory")
        return self._observation_factory(context).observe()
