"""Typed adapters for canonical Plan and Run document codecs."""

from dataclasses import dataclass

from coreelec_reconciler.domain.planning import CanonicalPlan, CanonicalRunReport
from coreelec_reconciler.persistence.execution_documents import (
    build_execution_run_report,
)
from coreelec_reconciler.persistence.planning_documents import (
    decode_plan,
    decode_run_report,
)
from coreelec_reconciler.resource_types.registry import ResourceRegistry


@dataclass(frozen=True, slots=True)
class CanonicalPlanDocumentCodec:
    def decode_plan(self, content: bytes) -> CanonicalPlan:
        return decode_plan(content)

    def decode_run_report(
        self,
        content: bytes,
        plan: CanonicalPlan,
    ) -> CanonicalRunReport:
        return decode_run_report(content, plan)


@dataclass(frozen=True, slots=True)
class CanonicalExecutionDocumentCodec:
    def build(
        self,
        value: dict[str, object],
        resource_registry: ResourceRegistry,
    ) -> CanonicalRunReport:
        return build_execution_run_report(value, resource_registry)
