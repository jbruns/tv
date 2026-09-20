"""Standalone canonical read-only verification Runs."""

import base64
import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, cast

from coreelec_reconciler.domain.canonical_json import (
    canonical_document_bytes,
    decode_json_object,
)
from coreelec_reconciler.domain.execution import (
    AppendIntent,
    DeviceIndexIntent,
    EvidenceObserver,
    ExecutionEvidenceBindings,
    ExecutionEvidenceKind,
    RunStatus,
    VerifiedRunChain,
    build_execution_evidence,
)
from coreelec_reconciler.domain.identifiers import DeviceId, RunId
from coreelec_reconciler.domain.planning import CanonicalRunReport
from coreelec_reconciler.execution.run_store import RunStore
from coreelec_reconciler.execution.runtime import RuntimeValues
from coreelec_reconciler.persistence.document_codecs import (
    CanonicalExecutionDocumentCodec,
)
from coreelec_reconciler.persistence.execution_documents import (
    decode_execution_run_report,
)
from coreelec_reconciler.resource_types.managed_file.observation import (
    ManagedFileObservation,
)
from coreelec_reconciler.resource_types.managed_file.preparation import (
    normalized_state_digest,
)
from coreelec_reconciler.resource_types.registry import ResourceRegistry


class VerificationRelation(StrEnum):
    CONVERGED = "converged"
    DIVERGENT = "divergent"
    UNVERIFIABLE = "unverifiable"


class ResourceVerifier(Protocol):
    def observe(self) -> object: ...

    def assess(self, observation: object) -> object: ...


@dataclass(frozen=True, slots=True)
class CanonicalVerificationBinding:
    desired_state_codec: str
    desired_state: bytes
    desired_state_digest: str
    verification_policy_codec: str
    verification_policy: bytes
    verification_policy_digest: str

    @classmethod
    def create(
        cls,
        *,
        desired_state_codec: str,
        desired_state: bytes,
        verification_policy_codec: str,
        verification_policy: bytes,
    ) -> CanonicalVerificationBinding:
        return cls(
            desired_state_codec,
            desired_state,
            _digest(desired_state),
            verification_policy_codec,
            verification_policy,
            _digest(verification_policy),
        )

    def validate(self) -> None:
        if not self.desired_state_codec or not self.verification_policy_codec:
            raise ValueError("verification binding codecs must be explicit")
        if (
            canonical_document_bytes(decode_json_object(self.desired_state))
            != self.desired_state
            or canonical_document_bytes(decode_json_object(self.verification_policy))
            != self.verification_policy
        ):
            raise ValueError("verification binding bytes must be canonical")
        if (
            _digest(self.desired_state) != self.desired_state_digest
            or _digest(self.verification_policy) != self.verification_policy_digest
        ):
            raise ValueError("verification binding digest mismatch")


@dataclass(frozen=True, slots=True)
class VerificationResource:
    resource_id: str
    resource_type: str
    state_addresses: tuple[str, ...]
    requires: tuple[str, ...]
    binding: CanonicalVerificationBinding
    execution: ResourceVerifier


@dataclass(frozen=True, slots=True)
class VerificationRequest:
    device_id: DeviceId
    resources: tuple[VerificationResource, ...]
    binding_digest: str
    boot_id: str


@dataclass(frozen=True, slots=True)
class ResourceVerification:
    resource_id: str
    relation: VerificationRelation


@dataclass(frozen=True, slots=True)
class VerificationRunResult:
    run_report: CanonicalRunReport
    resources: tuple[ResourceVerification, ...]

    @property
    def run_id(self) -> RunId:
        return RunId(self.run_report.run_id)

    @property
    def relation(self) -> VerificationRelation:
        relations = {item.relation for item in self.resources}
        if VerificationRelation.UNVERIFIABLE in relations:
            return VerificationRelation.UNVERIFIABLE
        if VerificationRelation.DIVERGENT in relations:
            return VerificationRelation.DIVERGENT
        return VerificationRelation.CONVERGED


@dataclass(frozen=True, slots=True)
class _ObservedVerification:
    result: ResourceVerification
    observation: ManagedFileObservation


class CanonicalVerificationRuns:
    """Observe and assess selected Resources without constructing a Plan."""

    def __init__(
        self,
        store: RunStore,
        registry: ResourceRegistry,
        runtime: RuntimeValues,
    ) -> None:
        self._store = store
        self._registry = registry
        self._runtime = runtime
        self._documents = CanonicalExecutionDocumentCodec()

    def verify(self, request: VerificationRequest) -> VerificationRunResult:
        ordered = _dependency_order(request.resources, self._registry)
        run_id = RunId(self._runtime.new_uuid7())
        origin_id = self._runtime.new_uuid7()
        scope_id = self._runtime.new_uuid7()
        started_at = self._runtime.utc_now()
        token = self._runtime.new_ownership_token()
        token_digest = _digest(token)
        scope_digest = _scope_digest(request, ordered)
        initial = self._documents.build(
            _initial_report(
                request,
                ordered,
                run_id,
                origin_id,
                scope_id,
                scope_digest,
                token_digest,
                started_at,
            ),
            self._registry,
        )
        device_lease = self._store.acquire_device(request.device_id)
        try:
            lease, _ = self._store.create_read_only_run(
                device_lease,
                run_id,
                request.device_id,
                token,
                token_digest,
                initial.canonical_bytes,
            )
        finally:
            self._store.release_device(device_lease)
        try:
            return self._continue(lease.run_id, ordered, lease)
        finally:
            self._store.release_run(lease)

    def restart(
        self,
        run_id: RunId,
        resources: tuple[VerificationResource, ...],
    ) -> VerificationRunResult:
        ordered = _dependency_order(resources, self._registry)
        lease = self._store.acquire_run(run_id)
        try:
            return self._continue(run_id, ordered, lease)
        finally:
            self._store.release_run(lease)

    def report(self, run_id: RunId) -> VerificationRunResult:
        chain = self._store.load_chain(run_id)
        report = decode_execution_run_report(
            chain.head.payload,
            resource_registry=self._registry,
        )
        return VerificationRunResult(report, _reported_resources(report))

    def _continue(
        self,
        run_id: RunId,
        resources: tuple[VerificationResource, ...],
        lease: object,
    ) -> VerificationRunResult:
        from coreelec_reconciler.domain.execution import RevisionLease

        if not isinstance(lease, RevisionLease):
            raise TypeError("verification requires a Run revision lease")
        chain = self._store.load_chain(run_id)
        value = decode_json_object(chain.head.payload)
        authority = _mapping(value, "authority")
        reference = _mapping(value, "plan_reference")
        stored_ids = tuple(
            str(item["resource_id"]) for item in _objects(value, "resource_results")
        )
        if stored_ids != tuple(item.resource_id for item in resources):
            raise ValueError("verification restart Resource selection changed")
        if reference.get("plan_full_digest") != _selection_digest(
            DeviceId(str(value["device_id"])),
            str(authority["binding_digest"]),
            resources,
        ):
            raise ValueError("verification restart scope binding changed")
        completed = _completed_prefix(chain, resources)
        if chain.terminal:
            return self.report(run_id)
        if RunStatus(str(value["status"])) is RunStatus.READY:
            executing = dict(value)
            executing.update(
                {
                    "current_digest": "",
                    "lifecycle_history": ["ready", "executing"],
                    "previous_revision_digest": chain.head.digest,
                    "revision": chain.head.revision + 1,
                    "status": "executing",
                }
            )
            report = self._documents.build(executing, self._registry)
            self._store.compare_and_append(
                lease,
                chain.head.revision,
                chain.head.digest,
                report.canonical_bytes,
                AppendIntent(
                    RunStatus.EXECUTING,
                    False,
                    DeviceIndexIntent.NO_CHANGE,
                ),
            )
            chain = self._store.load_chain(run_id)
            value = decode_json_object(chain.head.payload)
            completed = _completed_prefix(chain, resources)
        for resource in resources[completed:]:
            observed = _observe(resource)
            checkpoint = _checkpoint_report(
                value,
                chain.head.digest,
                observed,
                resource,
                self._runtime,
                self._registry,
            )
            report = self._documents.build(checkpoint, self._registry)
            self._store.compare_and_append(
                lease,
                chain.head.revision,
                chain.head.digest,
                report.canonical_bytes,
                AppendIntent(
                    RunStatus.EXECUTING,
                    False,
                    DeviceIndexIntent.NO_CHANGE,
                ),
            )
            chain = self._store.load_chain(run_id)
            value = decode_json_object(chain.head.payload)
            completed = _completed_prefix(chain, resources)
        terminal = _terminal_report(
            value,
            chain.head.digest,
            self._runtime,
        )
        report = self._documents.build(terminal, self._registry)
        self._store.compare_and_append(
            lease,
            chain.head.revision,
            chain.head.digest,
            report.canonical_bytes,
            AppendIntent(
                report.status,
                True,
                DeviceIndexIntent.NO_CHANGE,
            ),
        )
        return VerificationRunResult(
            report,
            _reported_resources(report),
        )


def _dependency_order(
    resources: tuple[VerificationResource, ...],
    registry: ResourceRegistry,
) -> tuple[VerificationResource, ...]:
    if not resources:
        raise ValueError("verification requires at least one selected Resource")
    by_id = {item.resource_id: item for item in resources}
    if len(by_id) != len(resources):
        raise ValueError("verification Resource IDs must be unique")
    for item in resources:
        item.binding.validate()
        if registry.descriptor(item.resource_type) is None:
            raise ValueError("verification Resource Type is not registered")
        if not item.state_addresses or tuple(sorted(set(item.state_addresses))) != (
            item.state_addresses
        ):
            raise ValueError("verification State Addresses must be sorted and unique")
        if any(requirement not in by_id for requirement in item.requires):
            raise ValueError("selected verification omits a Resource dependency")
    ordered: list[VerificationResource] = []
    pending = list(resources)
    while pending:
        completed = {done.resource_id for done in ordered}
        ready = [
            item
            for item in pending
            if all(requirement in completed for requirement in item.requires)
        ]
        if not ready:
            raise ValueError("verification Resource dependencies contain a cycle")
        for item in ready:
            ordered.append(item)
            pending.remove(item)
    return tuple(ordered)


def _observe(resource: VerificationResource) -> _ObservedVerification:
    observation = resource.execution.observe()
    if not isinstance(observation, ManagedFileObservation):
        raise TypeError("verification Resource produced unsupported Observation")
    if observation.address.logical_address not in resource.state_addresses:
        raise ValueError("verification Observation is outside selected State Addresses")
    assessment = resource.execution.assess(observation)
    relation = getattr(getattr(assessment, "relation", None), "value", None)
    return _ObservedVerification(
        ResourceVerification(
            resource.resource_id,
            {
                "satisfied": VerificationRelation.CONVERGED,
                "divergent": VerificationRelation.DIVERGENT,
                "unverifiable": VerificationRelation.UNVERIFIABLE,
            }.get(str(relation), VerificationRelation.UNVERIFIABLE),
        ),
        observation,
    )


def _scope_digest(
    request: VerificationRequest,
    resources: tuple[VerificationResource, ...],
) -> str:
    return _selection_digest(request.device_id, request.binding_digest, resources)


def _selection_digest(
    device_id: DeviceId,
    binding_digest: str,
    resources: tuple[VerificationResource, ...],
) -> str:
    return _digest(
        canonical_document_bytes(
            {
                "binding_digest": binding_digest,
                "device_id": device_id.value,
                "resources": [
                    {
                        "requires": list(item.requires),
                        "resource_id": item.resource_id,
                        "resource_type": item.resource_type,
                        "state_addresses": list(item.state_addresses),
                        "verification_binding": {
                            "desired_state_base64": base64.b64encode(
                                item.binding.desired_state
                            ).decode("ascii"),
                            "desired_state_codec": item.binding.desired_state_codec,
                            "desired_state_digest": item.binding.desired_state_digest,
                            "verification_policy_base64": base64.b64encode(
                                item.binding.verification_policy
                            ).decode("ascii"),
                            "verification_policy_codec": (
                                item.binding.verification_policy_codec
                            ),
                            "verification_policy_digest": (
                                item.binding.verification_policy_digest
                            ),
                        },
                    }
                    for item in resources
                ],
            }
        )
    )


def _initial_report(
    request: VerificationRequest,
    resources: tuple[VerificationResource, ...],
    run_id: RunId,
    origin_id: str,
    scope_id: str,
    scope_digest: str,
    token_digest: str,
    started_at: str,
) -> dict[str, object]:
    return {
        "approvals": [],
        "attachments": [],
        "attempts": [],
        "authority": {
            "binding_digest": request.binding_digest,
            "boot_id": request.boot_id,
            "cleanup_state": "not_started",
            "device_index_intent": "no_change",
            "marker_digest": None,
            "marker_generation": None,
            "marker_phase": None,
            "ownership_state": "unknown",
            "ownership_token_digest": token_digest,
        },
        "cleanup": {"leftover_count": 0, "state": "not_started"},
        "current_digest": "",
        "device_id": request.device_id.value,
        "ended_at": None,
        "evidence": [],
        "failures": [],
        "kind": "CoreElecReconcilerRunReport",
        "lifecycle_history": ["ready"],
        "originating_planning_run_id": origin_id,
        "plan_reference": {
            "originating_planning_run_id": origin_id,
            "plan_full_digest": scope_digest,
            "plan_id": scope_id,
        },
        "previous_revision_digest": None,
        "producer": {"name": "coreelec-reconciler", "version": "0.1.0"},
        "recovery": {
            "actions": [],
            "required": False,
            "workspace_id": f"workspace:{run_id.value}",
        },
        "resource_results": [
            {
                "decisive_attempt_id": None,
                "desired_disposition": "verify",
                "final_convergence": "pending",
                "latest_observed_relation": "unknown",
                "mutation_outcome": "not_required",
                "post_effect_verification": "not_applicable",
                "resource_id": item.resource_id,
                "rollback_outcome": "not_attempted",
                "verification_outcome": "not_started",
            }
            for item in resources
        ],
        "revision": 1,
        "run_id": run_id.value,
        "schema_version": 1,
        "started_at": started_at,
        "status": "ready",
    }


def _checkpoint_report(
    value: dict[str, object],
    previous_digest: str,
    observed: _ObservedVerification,
    resource: VerificationResource,
    runtime: RuntimeValues,
    registry: ResourceRegistry,
) -> dict[str, object]:
    authority = _mapping(value, "authority")
    reference = _mapping(value, "plan_reference")
    recovery = _mapping(value, "recovery")
    bindings_base = {
        "binding_digest": authority["binding_digest"],
        "device_id": value["device_id"],
        "plan_full_digest": reference["plan_full_digest"],
        "plan_id": reference["plan_id"],
        "run_id": value["run_id"],
        "workspace_id": recovery["workspace_id"],
    }
    result = observed.result
    observation = observed.observation
    evidence_id = f"evidence.{result.resource_id}.observation"
    bindings = ExecutionEvidenceBindings(
        str(bindings_base["device_id"]),
        str(bindings_base["run_id"]),
        str(bindings_base["workspace_id"]),
        str(bindings_base["plan_id"]),
        str(bindings_base["plan_full_digest"]),
        str(bindings_base["binding_digest"]),
        result.resource_id,
        f"verify.{result.resource_id}",
    )
    relation = {
        VerificationRelation.CONVERGED: "post",
        VerificationRelation.DIVERGENT: "other",
        VerificationRelation.UNVERIFIABLE: "unknown",
    }[result.relation]
    state = observation.state
    evidence = list(_objects(value, "evidence"))
    evidence.append(
        build_execution_evidence(
            evidence_id=evidence_id,
            observed_at=runtime.utc_now(),
            observer=EvidenceObserver("managed-file-observer", 1),
            subject_kind="resource",
            subject_id=result.resource_id,
            resource_type=resource.resource_type,
            bindings=bindings,
            state_addresses=resource.state_addresses,
            attachment_refs=(),
            attempt=1,
            kind=ExecutionEvidenceKind.MANAGED_FILE_OBSERVATION,
            payload={
                "content_digest": state.content_digest,
                "entry_kind": state.entry_kind,
                "managed_mode": state.managed_mode,
                "normalized_state_digest": normalized_state_digest(state),
                "presence": state.presence.value,
                "relation": relation,
            },
            resource_registry=registry,
        )
    )
    evidence.append(
        build_execution_evidence(
            evidence_id=f"evidence.{result.resource_id}.execution",
            observed_at=runtime.utc_now(),
            observer=EvidenceObserver("managed-file-executor", 1),
            subject_kind="resource",
            subject_id=result.resource_id,
            resource_type=resource.resource_type,
            bindings=bindings,
            state_addresses=resource.state_addresses,
            attachment_refs=(),
            attempt=1,
            kind=ExecutionEvidenceKind.RESOURCE_EXECUTION_RESULT,
            payload={
                "intent_evidence_ref": None,
                "mutation_outcome": "not_required",
                "outcome_evidence_ref": None,
            },
            resource_registry=registry,
        )
    )
    outcome = {
        VerificationRelation.CONVERGED: "matched",
        VerificationRelation.DIVERGENT: "mismatch",
        VerificationRelation.UNVERIFIABLE: "unknown",
    }[result.relation]
    evidence.append(
        build_execution_evidence(
            evidence_id=f"evidence.{result.resource_id}.verification",
            observed_at=runtime.utc_now(),
            observer=EvidenceObserver("managed-file-verifier", 1),
            subject_kind="resource",
            subject_id=result.resource_id,
            resource_type=resource.resource_type,
            bindings=bindings,
            state_addresses=resource.state_addresses,
            attachment_refs=(),
            attempt=1,
            kind=ExecutionEvidenceKind.RESOURCE_VERIFICATION_RESULT,
            payload={
                "observation_evidence_ref": evidence_id,
                "outcome": outcome,
                "post_effect": False,
                "relation": relation,
            },
            resource_registry=registry,
        )
    )
    resource_results = list(_objects(value, "resource_results"))
    result_index = next(
        index
        for index, item in enumerate(resource_results)
        if item.get("resource_id") == result.resource_id
    )
    resource_results[result_index] = {
        "decisive_attempt_id": None,
        "desired_disposition": "verify",
        "final_convergence": (
            "converged"
            if result.relation is VerificationRelation.CONVERGED
            else "failed_known"
        ),
        "latest_observed_relation": relation,
        "mutation_outcome": "not_required",
        "post_effect_verification": "not_applicable",
        "resource_id": result.resource_id,
        "rollback_outcome": "not_attempted",
        "verification_outcome": outcome,
    }
    checkpoint = dict(value)
    checkpoint.update(
        {
            "current_digest": "",
            "evidence": evidence,
            "previous_revision_digest": previous_digest,
            "resource_results": resource_results,
            "revision": _integer(value, "revision") + 1,
        }
    )
    return checkpoint


def _terminal_report(
    value: dict[str, object],
    previous_digest: str,
    runtime: RuntimeValues,
) -> dict[str, object]:
    resources = _objects(value, "resource_results")
    converged = all(item.get("verification_outcome") == "matched" for item in resources)
    terminal = dict(value)
    terminal_authority = dict(_mapping(value, "authority"))
    terminal_authority["cleanup_state"] = "complete"
    terminal.update(
        {
            "authority": terminal_authority,
            "cleanup": {"leftover_count": 0, "state": "complete"},
            "current_digest": "",
            "ended_at": runtime.utc_now(),
            "lifecycle_history": [
                "ready",
                "executing",
                "converged" if converged else "failed_partial",
            ],
            "previous_revision_digest": previous_digest,
            "revision": _integer(value, "revision") + 1,
            "status": "converged" if converged else "failed_partial",
        }
    )
    return terminal


def _reported_resources(report: CanonicalRunReport) -> tuple[ResourceVerification, ...]:
    value = decode_json_object(report.canonical_bytes)
    result: list[ResourceVerification] = []
    for item in _objects(value, "resource_results"):
        outcome = item.get("verification_outcome")
        relation = {
            "matched": VerificationRelation.CONVERGED,
            "mismatch": VerificationRelation.DIVERGENT,
            "unknown": VerificationRelation.UNVERIFIABLE,
        }.get(str(outcome), VerificationRelation.UNVERIFIABLE)
        result.append(ResourceVerification(str(item["resource_id"]), relation))
    return tuple(result)


def _completed_prefix(
    chain: VerifiedRunChain,
    resources: tuple[VerificationResource, ...],
) -> int:
    expected_ids = tuple(item.resource_id for item in resources)
    previous_count = 0
    previous_evidence: tuple[dict[str, object], ...] = ()
    previous_results: tuple[dict[str, object], ...] | None = None
    for revision_index, revision in enumerate(chain.revisions):
        value = decode_json_object(revision.payload)
        results = _objects(value, "resource_results")
        if tuple(str(item.get("resource_id")) for item in results) != expected_ids:
            raise ValueError("verification checkpoint Resource order changed")
        outcomes = tuple(item.get("verification_outcome") for item in results)
        completed = 0
        while completed < len(outcomes) and outcomes[completed] != "not_started":
            completed += 1
        if any(outcome != "not_started" for outcome in outcomes[completed:]):
            raise ValueError("verification checkpoints contain a completed-prefix gap")
        evidence = _objects(value, "evidence")
        if len(evidence) != completed * 3:
            raise ValueError("verification checkpoint evidence count is invalid")
        for index, resource in enumerate(resources[:completed]):
            chunk = evidence[index * 3 : index * 3 + 3]
            expected = (
                (
                    f"evidence.{resource.resource_id}.observation",
                    ExecutionEvidenceKind.MANAGED_FILE_OBSERVATION.value,
                ),
                (
                    f"evidence.{resource.resource_id}.execution",
                    ExecutionEvidenceKind.RESOURCE_EXECUTION_RESULT.value,
                ),
                (
                    f"evidence.{resource.resource_id}.verification",
                    ExecutionEvidenceKind.RESOURCE_VERIFICATION_RESULT.value,
                ),
            )
            for record, (evidence_id, kind) in zip(chunk, expected, strict=True):
                subject = _mapping(record, "subject")
                bindings = _mapping(record, "bindings")
                if (
                    record.get("evidence_id") != evidence_id
                    or record.get("payload_kind") != kind
                    or record.get("resource_type") != resource.resource_type
                    or record.get("state_addresses") != list(resource.state_addresses)
                    or subject != {"id": resource.resource_id, "kind": "resource"}
                    or bindings.get("resource_id") != resource.resource_id
                    or bindings.get("change_id") != f"verify.{resource.resource_id}"
                ):
                    raise ValueError("verification checkpoint evidence order changed")
        if revision_index == 0:
            if completed != 0:
                raise ValueError("initial verification revision is already completed")
        elif completed not in {previous_count, previous_count + 1}:
            raise ValueError("verification checkpoint prefix is not contiguous")
        elif completed == previous_count:
            if evidence != previous_evidence or (
                previous_results is not None and results != previous_results
            ):
                raise ValueError("verification revision changed without a checkpoint")
        else:
            if evidence[: len(previous_evidence)] != previous_evidence:
                raise ValueError("verification checkpoint rewrote prior evidence")
            if (
                previous_results is not None
                and results[:previous_count] != previous_results[:previous_count]
            ):
                raise ValueError("verification checkpoint rewrote completed results")
        previous_count = completed
        previous_evidence = evidence
        previous_results = results
    if chain.terminal and previous_count != len(resources):
        raise ValueError(
            "terminal verification Run has an incomplete checkpoint prefix"
        )
    return previous_count


def _digest(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _mapping(value: Mapping[str, object], key: str) -> dict[str, object]:
    item = value.get(key)
    if not isinstance(item, dict):
        raise ValueError(f"verification Run {key} is malformed")
    return cast(dict[str, object], item)


def _objects(
    value: Mapping[str, object],
    key: str,
) -> tuple[dict[str, object], ...]:
    items = value.get(key)
    if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
        raise ValueError(f"verification Run {key} is malformed")
    return tuple(cast(dict[str, object], item) for item in items)


def _integer(value: Mapping[str, object], key: str) -> int:
    item = value.get(key)
    if type(item) is not int:
        raise ValueError(f"verification Run {key} is malformed")
    return item
