"""Durable session-close uncertainty without changing canonical Run truth."""

from collections.abc import Callable
from dataclasses import dataclass

from coreelec_reconciler.domain.execution import (
    AllowedRecoveryAction,
    RevisionLease,
    SessionCloseDisposition,
    SessionCloseFailureCategory,
    SessionCloseInspection,
    SessionCloseIntent,
)
from coreelec_reconciler.domain.identifiers import RunId
from coreelec_reconciler.domain.planning import CanonicalRunReport
from coreelec_reconciler.execution.run_store import (
    CompareConflict,
    CorruptRunStore,
    RunStore,
    RunStoreError,
)
from coreelec_reconciler.execution.runtime import RuntimeValues


@dataclass(frozen=True, slots=True)
class SessionCloseRequest:
    record_id: str
    session_id: str


@dataclass(frozen=True, slots=True)
class PreservedRunResult:
    run_report: CanonicalRunReport
    recovery_guidance: tuple[AllowedRecoveryAction, ...]
    close: SessionCloseInspection

    @property
    def run_id(self) -> RunId:
        return RunId(self.run_report.run_id)


class DurableSessionClose:
    """Close once, persist safe uncertainty, and always preserve Run truth."""

    def __init__(self, store: RunStore, runtime: RuntimeValues) -> None:
        self._store = store
        self._runtime = runtime

    def close(
        self,
        request: SessionCloseRequest,
        run_report: CanonicalRunReport,
        recovery_guidance: tuple[AllowedRecoveryAction, ...],
        attempt: Callable[[], SessionCloseDisposition],
        *,
        lease: RevisionLease | None = None,
    ) -> PreservedRunResult:
        run_id = RunId(run_report.run_id)
        owned_lease = lease is None
        active_lease = lease
        try:
            if active_lease is None:
                active_lease = self._store.acquire_run(run_id)
            existing = self._safe_inspect(run_id, request.session_id)
            if existing.record is not None:
                if existing.record.record_id != request.record_id:
                    return PreservedRunResult(
                        run_report,
                        recovery_guidance,
                        SessionCloseInspection(
                            SessionCloseDisposition.UNKNOWN,
                            None,
                            "session_close.idempotency-conflict",
                        ),
                    )
                return PreservedRunResult(run_report, recovery_guidance, existing)
            if existing.issue_code == "session_close.corrupt":
                return PreservedRunResult(run_report, recovery_guidance, existing)
            disposition, category, code = _attempt_close(attempt)
            self._store.record_session_close(
                active_lease,
                SessionCloseIntent(
                    request.record_id,
                    request.session_id,
                    self._runtime.utc_now(),
                    disposition,
                    category,
                    code,
                ),
            )
        except CompareConflict, CorruptRunStore, RunStoreError, ValueError:
            return PreservedRunResult(
                run_report,
                recovery_guidance,
                SessionCloseInspection(
                    SessionCloseDisposition.UNKNOWN,
                    None,
                    "session_close.record-failed",
                ),
            )
        finally:
            if owned_lease and active_lease is not None:
                self._store.release_run(active_lease)
        return PreservedRunResult(
            run_report,
            recovery_guidance,
            self._safe_inspect(run_id, request.session_id),
        )

    def inspect(
        self,
        request: SessionCloseRequest,
        run_report: CanonicalRunReport,
        recovery_guidance: tuple[AllowedRecoveryAction, ...],
    ) -> PreservedRunResult:
        return PreservedRunResult(
            run_report,
            recovery_guidance,
            self._safe_inspect(RunId(run_report.run_id), request.session_id),
        )

    def _safe_inspect(self, run_id: RunId, session_id: str) -> SessionCloseInspection:
        try:
            return self._store.inspect_session_close(run_id, session_id)
        except CorruptRunStore, RunStoreError, ValueError:
            return SessionCloseInspection(
                SessionCloseDisposition.UNKNOWN,
                None,
                "session_close.inspect-failed",
            )


def _attempt_close(
    attempt: Callable[[], SessionCloseDisposition],
) -> tuple[
    SessionCloseDisposition,
    SessionCloseFailureCategory | None,
    str | None,
]:
    try:
        disposition = attempt()
    except TimeoutError:
        return (
            SessionCloseDisposition.FAILED,
            SessionCloseFailureCategory.TIMEOUT,
            "session_close.timeout",
        )
    except ConnectionError, OSError:
        return (
            SessionCloseDisposition.FAILED,
            SessionCloseFailureCategory.TRANSPORT,
            "session_close.transport",
        )
    except Exception:
        return (
            SessionCloseDisposition.UNKNOWN,
            SessionCloseFailureCategory.LOCAL_RUNTIME,
            "session_close.local-runtime",
        )
    if disposition is SessionCloseDisposition.COMPLETE:
        return disposition, None, None
    return (
        disposition,
        SessionCloseFailureCategory.UNKNOWN,
        f"session_close.{disposition.value}",
    )
