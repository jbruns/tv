"""Deterministic, non-controlling execution progress."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ProgressEvent:
    sequence: int
    code: str
    run_id: str
    resource_id: str | None = None
    operation_id: str | None = None


@dataclass(frozen=True, slots=True)
class PresentationDiagnostic:
    code: str
    safe_message: str


class ProgressSink(Protocol):
    def emit(self, event: ProgressEvent) -> None: ...


class Progress:
    """Emits ordered events while isolating sink failure from execution truth."""

    def __init__(self, sink: ProgressSink | None = None) -> None:
        self._sink = sink
        self._sequence = 0
        self._diagnostics: list[PresentationDiagnostic] = []

    @property
    def diagnostics(self) -> tuple[PresentationDiagnostic, ...]:
        return tuple(self._diagnostics)

    def emit(
        self,
        code: str,
        run_id: str,
        *,
        resource_id: str | None = None,
        operation_id: str | None = None,
    ) -> ProgressEvent:
        self._sequence += 1
        event = ProgressEvent(self._sequence, code, run_id, resource_id, operation_id)
        if self._sink is not None:
            try:
                self._sink.emit(event)
            except Exception:
                self._diagnostics.append(
                    PresentationDiagnostic(
                        "progress.delivery-failed",
                        "A progress update could not be delivered.",
                    )
                )
        return event
