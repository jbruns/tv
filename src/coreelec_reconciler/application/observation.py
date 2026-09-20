"""Application-facing observation workflow with no concrete adapter imports."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from coreelec_reconciler.domain.execution import SessionCloseDisposition
from coreelec_reconciler.domain.identifiers import RunId
from coreelec_reconciler.domain.observation import CanonicalObservationRun
from coreelec_reconciler.execution.observation import (
    ObservationRunInspection,
    ObservationRunRequest,
)
from coreelec_reconciler.execution.session_close import (
    DurableSessionClose,
    PreservedRunResult,
    SessionCloseRequest,
)


class ObservationRuns(Protocol):
    def start(self, request: ObservationRunRequest) -> CanonicalObservationRun: ...

    def restart(self, request: ObservationRunRequest) -> CanonicalObservationRun: ...

    def report(self, run_id: RunId) -> CanonicalObservationRun: ...

    def inspect(self, run_id: RunId) -> ObservationRunInspection: ...


@dataclass(frozen=True, slots=True)
class ObservationApplication:
    """Thin bootstrap-ready boundary over canonical observation execution."""

    runs: ObservationRuns
    session_close: DurableSessionClose

    def observe(self, request: ObservationRunRequest) -> CanonicalObservationRun:
        return self.runs.start(request)

    def restart(self, request: ObservationRunRequest) -> CanonicalObservationRun:
        return self.runs.restart(request)

    def report(self, run_id: RunId) -> CanonicalObservationRun:
        return self.runs.report(run_id)

    def inspect(self, run_id: RunId) -> ObservationRunInspection:
        return self.runs.inspect(run_id)

    def close(
        self,
        request: SessionCloseRequest,
        run: CanonicalObservationRun,
        attempt: Callable[[], SessionCloseDisposition],
    ) -> PreservedRunResult[CanonicalObservationRun]:
        return self.session_close.close(request, run, (), attempt)

    def inspect_close(
        self,
        request: SessionCloseRequest,
        run: CanonicalObservationRun,
    ) -> PreservedRunResult[CanonicalObservationRun]:
        return self.session_close.inspect(request, run, ())
