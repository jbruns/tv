"""Progress sinks used by execution tests."""

from coreelec_reconciler.execution.progress import ProgressEvent


class RecordingProgress:
    def __init__(self, *, fail_at: int | None = None) -> None:
        self.events: list[ProgressEvent] = []
        self.fail_at = fail_at

    def emit(self, event: ProgressEvent) -> None:
        if self.fail_at == event.sequence:
            raise OSError("scripted progress failure")
        self.events.append(event)
