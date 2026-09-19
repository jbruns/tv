from coreelec_reconciler.execution.progress import Progress
from tests.fakes.progress import RecordingProgress


def test_progress_is_deterministic_and_sink_failure_is_non_controlling() -> None:
    sink = RecordingProgress(fail_at=2)
    progress = Progress(sink)

    first = progress.emit("run.start", "run")
    second = progress.emit("resource.apply", "run", resource_id="resource")
    third = progress.emit("run.done", "run")

    assert (first.sequence, second.sequence, third.sequence) == (1, 2, 3)
    assert [event.sequence for event in sink.events] == [1, 3]
    assert progress.diagnostics[0].code == "progress.delivery-failed"
