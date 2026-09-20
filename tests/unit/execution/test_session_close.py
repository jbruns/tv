from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

from coreelec_reconciler.domain.execution import (
    AllowedRecoveryAction,
    RecoveryActionCode,
    SessionCloseDisposition,
)
from coreelec_reconciler.domain.identifiers import DeviceId
from coreelec_reconciler.domain.planning import DesiredRelation
from coreelec_reconciler.execution.run_store import RunStore
from coreelec_reconciler.execution.runtime import FiniteRuntimeValues
from coreelec_reconciler.execution.session_close import (
    DurableSessionClose,
    PreservedRunResult,
    SessionCloseRequest,
)
from coreelec_reconciler.execution.verification import (
    CanonicalVerificationRuns,
    VerificationRequest,
    VerificationResource,
    VerificationRunResult,
)
from coreelec_reconciler.resource_types.builtins import built_in_resource_registry

from .test_verification import _binding, _ReadOnlyExecution, _runtime


def _terminal_run(tmp_path: Path) -> tuple[RunStore, VerificationRunResult]:
    registry = built_in_resource_registry()
    store = RunStore(tmp_path / "runs", resource_registry=registry)
    resource = VerificationResource(
        "resource",
        "KodiSmartPlaylist",
        ("special://profile/playlists/video/resource.xsp",),
        (),
        _binding("resource"),
        _ReadOnlyExecution("resource", DesiredRelation.SATISFIED, []),
    )
    result = CanonicalVerificationRuns(store, registry, _runtime()).verify(
        VerificationRequest(
            DeviceId("device.test"),
            (resource,),
            "sha256:" + "1" * 64,
            "boot",
        )
    )
    return store, result


def test_close_failure_is_sanitized_and_idempotent_before_lease_release(
    tmp_path: Path,
) -> None:
    store, result = _terminal_run(tmp_path)
    runtime = FiniteRuntimeValues(
        utc_instants=("2026-09-20T05:01:00Z",),
    )
    closer = DurableSessionClose(store, runtime)
    request = SessionCloseRequest(
        "019950f8-4c00-7000-8000-000000000701",
        "session.019950f8-4c00-7000-8000-000000000801",
    )
    lease = store.acquire_run(result.run_id)

    def fail() -> SessionCloseDisposition:
        raise TimeoutError("credential=do-not-persist")

    first = closer.close(
        request,
        result.run_report,
        (),
        fail,
        lease=lease,
    )
    second = closer.close(
        request,
        result.run_report,
        (),
        lambda: SessionCloseDisposition.COMPLETE,
        lease=lease,
    )
    store.release_run(lease)

    assert first.run_report is result.run_report
    assert first.close.disposition is SessionCloseDisposition.FAILED
    assert first.close.issue_code == "session_close.timeout"
    assert first.close.record is not None
    assert b"credential" not in first.close.record.canonical_bytes
    assert second.close.record == first.close.record


def test_unknown_close_after_release_preserves_result_and_guidance(
    tmp_path: Path,
) -> None:
    store, result = _terminal_run(tmp_path)
    closer = DurableSessionClose(
        store,
        FiniteRuntimeValues(utc_instants=("2026-09-20T05:01:00Z",)),
    )
    request = SessionCloseRequest(
        "019950f8-4c00-7000-8000-000000000702",
        "session.019950f8-4c00-7000-8000-000000000802",
    )
    guidance = (
        AllowedRecoveryAction(
            RecoveryActionCode.INSPECT,
            None,
            True,
            "recovery.workspace-present",
            False,
            False,
        ),
    )

    closed = closer.close(
        request,
        result.run_report,
        guidance,
        lambda: SessionCloseDisposition.UNKNOWN,
    )
    inspected = closer.inspect(request, result.run_report, guidance)

    assert closed.run_id == result.run_id
    assert closed.run_report is result.run_report
    assert closed.recovery_guidance is guidance
    assert closed.close.disposition is SessionCloseDisposition.UNKNOWN
    assert closed.close.issue_code == "session_close.unknown"
    assert inspected == closed


def test_concurrent_close_for_same_session_attempts_teardown_once(
    tmp_path: Path,
) -> None:
    store, result = _terminal_run(tmp_path)
    request = SessionCloseRequest(
        "019950f8-4c00-7000-8000-000000000703",
        "session.019950f8-4c00-7000-8000-000000000803",
    )
    first_attempt_entered = Event()
    allow_first_attempt = Event()
    second_call_started = Event()
    second_attempt_entered = Event()

    def first_attempt() -> SessionCloseDisposition:
        first_attempt_entered.set()
        assert allow_first_attempt.wait(timeout=5)
        return SessionCloseDisposition.COMPLETE

    def second_attempt() -> SessionCloseDisposition:
        second_attempt_entered.set()
        return SessionCloseDisposition.COMPLETE

    first_closer = DurableSessionClose(
        store,
        FiniteRuntimeValues(utc_instants=("2026-09-20T05:01:00Z",)),
    )
    second_closer = DurableSessionClose(
        store,
        FiniteRuntimeValues(utc_instants=("2026-09-20T05:02:00Z",)),
    )

    def second_close() -> PreservedRunResult:
        second_call_started.set()
        return second_closer.close(
            request,
            result.run_report,
            (),
            second_attempt,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(
            first_closer.close,
            request,
            result.run_report,
            (),
            first_attempt,
        )
        assert first_attempt_entered.wait(timeout=5)
        second_future = executor.submit(second_close)
        assert second_call_started.wait(timeout=5)
        second_attempted_while_first_was_blocked = second_attempt_entered.wait(
            timeout=0.01
        )
        allow_first_attempt.set()
        first = first_future.result(timeout=5)
        second = second_future.result(timeout=5)

    assert not second_attempted_while_first_was_blocked
    assert not second_attempt_entered.is_set()
    assert first.close.record is not None
    assert second.run_report is result.run_report
