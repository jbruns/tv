"""Durable repository for canonical Plans and their originating planning Runs."""

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from coreelec_reconciler.domain.canonical_json import decode_json_object
from coreelec_reconciler.domain.identifiers import DeviceId, PlanId, RunId
from coreelec_reconciler.domain.planning import CanonicalPlan, CanonicalRunReport
from coreelec_reconciler.execution.local_durability import (
    AcknowledgementLost,
    LocalDurability,
    PosixLocalDurability,
    read_regular_file,
)
from coreelec_reconciler.persistence.document_codecs import CanonicalPlanDocumentCodec


class PlanStoreError(RuntimeError):
    pass


class PlanNotFound(PlanStoreError):
    pass


class CorruptPlanStore(PlanStoreError):
    pass


class PlanDocumentCodec(Protocol):
    def decode_plan(self, content: bytes) -> CanonicalPlan: ...

    def decode_run_report(
        self,
        content: bytes,
        plan: CanonicalPlan,
    ) -> CanonicalRunReport: ...


@dataclass(frozen=True, slots=True)
class SavedPlan:
    plan: CanonicalPlan
    planning_run: CanonicalRunReport
    device_id: DeviceId
    originating_run_id: RunId
    approval_scopes: tuple[str, ...]
    input_digests: tuple[tuple[str, str], ...]


class PlanStore:
    """Restart-safe content validation for saved planning results."""

    def __init__(
        self,
        root: Path,
        durability: LocalDurability | None = None,
        documents: PlanDocumentCodec | None = None,
    ) -> None:
        self._root = root
        self._documents = documents or CanonicalPlanDocumentCodec()
        self._durability = durability or PosixLocalDurability()
        self._initialize()

    def save(
        self,
        plan: CanonicalPlan,
        planning_run: CanonicalRunReport,
    ) -> SavedPlan:
        verified = _verify_pair(plan, planning_run, self._documents)
        directory = self._directory(PlanId(plan.plan_id))
        if directory.exists() and (directory.is_symlink() or not directory.is_dir()):
            raise CorruptPlanStore("saved Plan path is unsafe")
        directory.mkdir(mode=0o700, exist_ok=True)
        os.chmod(directory, 0o700)
        self._publish_exact(directory / "plan.json", plan.canonical_bytes)
        self._publish_exact(
            directory / "planning-run.json",
            planning_run.canonical_bytes,
        )
        return verified

    def load(self, plan_id: PlanId) -> SavedPlan:
        directory = self._directory(plan_id)
        try:
            plan_bytes = read_regular_file(directory / "plan.json")
            run_bytes = read_regular_file(directory / "planning-run.json")
        except (FileNotFoundError, OSError) as error:
            if not directory.exists():
                raise PlanNotFound("saved Plan does not exist") from error
            raise CorruptPlanStore("saved Plan is incomplete or unsafe") from error
        try:
            plan = self._documents.decode_plan(plan_bytes)
            run = self._documents.decode_run_report(run_bytes, plan)
        except ValueError as error:
            raise CorruptPlanStore("saved Plan validation failed") from error
        if plan.plan_id != plan_id.value:
            raise CorruptPlanStore("saved Plan identity does not match lookup")
        return _saved_plan(plan, run)

    def _initialize(self) -> None:
        if self._root.exists() and (self._root.is_symlink() or not self._root.is_dir()):
            raise CorruptPlanStore("PlanStore root is unsafe")
        self._root.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self._root, 0o700)

    def _directory(self, plan_id: PlanId) -> Path:
        return self._root / hashlib.sha256(plan_id.value.encode()).hexdigest()

    def _publish_exact(self, path: Path, payload: bytes) -> None:
        try:
            existing = read_regular_file(path)
        except FileNotFoundError:
            pass
        else:
            if existing != payload:
                raise CorruptPlanStore("saved Plan content changed")
            return
        staged = path.with_name(path.name + ".new")
        self._durability.write_private(str(staged), payload)
        self._durability.full_sync_file(str(staged))
        self._durability.atomic_replace(str(staged), str(path))
        self._durability.sync_directory(str(path.parent))
        try:
            self._durability.acknowledge(f"save-plan:{path.name}")
        except AcknowledgementLost:
            try:
                saved = read_regular_file(path)
            except (FileNotFoundError, OSError) as error:
                raise PlanStoreError(
                    "saved Plan acknowledgement could not be reconciled"
                ) from error
            if saved != payload:
                raise PlanStoreError(
                    "saved Plan acknowledgement could not be reconciled"
                ) from None


def _verify_pair(
    plan: CanonicalPlan,
    planning_run: CanonicalRunReport,
    documents: PlanDocumentCodec,
) -> SavedPlan:
    try:
        decoded_plan = documents.decode_plan(plan.canonical_bytes)
        decoded_run = documents.decode_run_report(
            planning_run.canonical_bytes, decoded_plan
        )
    except ValueError as error:
        raise PlanStoreError("canonical Plan pair validation failed") from error
    if decoded_plan != plan or decoded_run != planning_run:
        raise PlanStoreError("canonical Plan pair metadata does not match bytes")
    return _saved_plan(decoded_plan, decoded_run)


def _saved_plan(
    plan: CanonicalPlan,
    planning_run: CanonicalRunReport,
) -> SavedPlan:
    value = decode_json_object(plan.canonical_bytes)
    device = value.get("device")
    requirements = value.get("approval_requirements")
    inputs = value.get("input_digests")
    if (
        not isinstance(device, dict)
        or not isinstance(device.get("logical_id"), str)
        or not isinstance(requirements, list)
        or not isinstance(inputs, dict)
    ):
        raise PlanStoreError("canonical Plan source bindings are incomplete")
    scopes: list[str] = []
    for item in requirements:
        if not isinstance(item, dict) or not isinstance(item.get("scope"), str):
            raise PlanStoreError("canonical Plan approval requirements are malformed")
        scopes.append(item["scope"])
    digests = tuple(sorted((str(key), str(item)) for key, item in inputs.items()))
    return SavedPlan(
        plan,
        planning_run,
        DeviceId(device["logical_id"]),
        RunId(str(value["originating_run_id"])),
        tuple(scopes),
        digests,
    )
