from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from coreelec_reconciler.application.commands import (
    ApplyCommand,
    ObserveCommand,
    PlanCommand,
    ReconcileCommand,
    RecoverCommand,
    ReportCommand,
    VerifyCommand,
)
from coreelec_reconciler.application.outcomes import (
    ApplyOutcome,
    CanonicalPlanOutcome,
    ObservationOutcome,
    ReconcileOutcome,
    RecoveryInspectionOutcome,
    ReportOutcome,
    UnsupportedOutcome,
    VerifyOutcome,
)
from coreelec_reconciler.bootstrap import BootstrapSettings, bootstrap
from coreelec_reconciler.domain.canonical_json import decode_json_object
from coreelec_reconciler.domain.execution import (
    RecoveryActionCode,
    RunStatus,
)
from coreelec_reconciler.domain.identifiers import DeviceId
from coreelec_reconciler.transports.interfaces import (
    DeviceCapabilitySnapshot,
    DeviceIdentity,
)
from tests.fakes.device import FakeDevice
from tests.fakes.runtime import FakeManagedFiles

DEVICE_ID = DeviceId("living-room.ugoos-am6b-plus")
MANAGED_PATH = "/storage/.kodi/userdata/playlists/video/NewShows.xsp"


class _Runtime:
    def __init__(self) -> None:
        self._uuid = 0
        self._instant = datetime(2026, 9, 19, 20, 0, tzinfo=UTC)

    def utc_now(self) -> str:
        value = self._instant.isoformat().replace("+00:00", "Z")
        self._instant += timedelta(seconds=1)
        return value

    def new_uuid7(self) -> str:
        self._uuid += 1
        return f"019950f8-4c00-7000-8000-{self._uuid:012d}"

    def new_ownership_token(self) -> bytes:
        return bytes([self._uuid % 251 + 1]) * 32

    def advance(self, delta: timedelta) -> None:
        self._instant += delta


@dataclass
class _Session:
    files: FakeManagedFiles
    remote: FakeDevice
    requested: frozenset[str]
    closed: bool = False
    close_error: Exception | None = None

    @property
    def identity(self) -> DeviceIdentity:
        return DeviceIdentity(DEVICE_ID, "sha256:" + "a" * 64, "boot.synthetic")

    @property
    def capabilities(self) -> DeviceCapabilitySnapshot:
        from coreelec_reconciler.domain.configuration import ProfileRootCapability

        return DeviceCapabilitySnapshot(
            ProfileRootCapability("/storage/.kodi/userdata"), True
        )

    @property
    def managed_files(self) -> FakeManagedFiles:
        return self.files

    @property
    def managed_file_mutations(self) -> FakeManagedFiles:
        return self.files

    def remote_ownership(self, workspace_key: str) -> FakeDevice:
        assert len(workspace_key) == 64
        return self.remote

    def close(self) -> None:
        self.closed = True
        if self.close_error is not None:
            raise self.close_error


def _repository(tmp_path: Path) -> Path:
    source = Path(__file__).parents[1] / "fixtures" / "repository"
    root = tmp_path / "repository"
    shutil.copytree(source, root)
    return root


def test_bootstrap_composes_all_workflows_and_restart_recovery(
    tmp_path: Path,
) -> None:
    root = _repository(tmp_path)
    state = tmp_path / "state"
    files = FakeManagedFiles()
    remote = FakeDevice()
    sessions: list[_Session] = []

    def open_session(device: object, capabilities: frozenset[str]) -> _Session:
        del device
        session = _Session(files, remote, capabilities)
        sessions.append(session)
        return session

    settings = BootstrapSettings(
        str(root),
        state_root=str(state),
        session_opener=open_session,
        runtime_values=_Runtime(),
        host_key_fingerprint=lambda device: "SHA256:synthetic-host-key",
    )
    application = bootstrap(settings)
    assert not state.exists()

    observed = application.execute(ObserveCommand(str(root), DEVICE_ID))
    assert isinstance(observed, ObservationOutcome)
    planned = application.execute(PlanCommand(str(root), DEVICE_ID))
    assert isinstance(planned, CanonicalPlanOutcome)
    awaiting = application.execute(ReconcileCommand(str(root), DEVICE_ID, ()))
    assert isinstance(awaiting, ReconcileOutcome)
    assert awaiting.execution_run_report is None
    assert awaiting.approval is not None
    assert not awaiting.approval.sufficient
    assert files.operations == ()
    assert sessions[-1].requested == frozenset({"managed_file.read"})

    applied = application.execute(ApplyCommand(str(root), planned.plan_id, ("apply",)))
    assert isinstance(applied, ApplyOutcome)
    assert applied.cleanup_complete
    assert files.entry(MANAGED_PATH) is not None
    reported = application.execute(ReportCommand(str(root), applied.run_id))
    assert isinstance(reported, ReportOutcome)
    assert reported.run_report.current_digest == applied.run_report.current_digest

    verified = application.execute(VerifyCommand(str(root), DEVICE_ID))
    assert isinstance(verified, VerifyOutcome)
    assert verified.run_report.status is RunStatus.CONVERGED
    assert sessions[-1].requested == frozenset({"managed_file.read"})

    files.remove(MANAGED_PATH, "test.reconcile-reset")
    reconciled = application.execute(ReconcileCommand(str(root), DEVICE_ID, ("apply",)))
    assert isinstance(reconciled, ReconcileOutcome)
    assert reconciled.execution_run_report is not None

    restarted = bootstrap(settings)
    restart_report = restarted.execute(ReportCommand(str(root), applied.run_id))
    assert isinstance(restart_report, ReportOutcome)
    inspected = restarted.execute(RecoverCommand(str(root), applied.run_id, "inspect"))
    assert isinstance(inspected, RecoveryInspectionOutcome)

    files.remove(MANAGED_PATH, "test.reset")
    interrupted_plan = restarted.execute(PlanCommand(str(root), DEVICE_ID))
    assert isinstance(interrupted_plan, CanonicalPlanOutcome)
    from coreelec_reconciler.domain.execution import MutationDisposition

    files.lost_ack("atomic_replace", applied=False)
    files.fault("cleanup", MutationDisposition.AMBIGUOUS)
    interrupted = restarted.execute(
        ApplyCommand(str(root), interrupted_plan.plan_id, ("apply",))
    )
    assert isinstance(interrupted, ApplyOutcome)
    assert not interrupted.cleanup_complete

    recovery_process = bootstrap(settings)
    interrupted_inspection = recovery_process.execute(
        RecoverCommand(str(root), interrupted.run_id, "inspect")
    )
    assert isinstance(interrupted_inspection, RecoveryInspectionOutcome)
    assert sessions[-1].requested == frozenset({"remote_run_ownership"})
    rejected_action = next(
        action
        for action in interrupted_inspection.actions
        if action.code is not RecoveryActionCode.INSPECT and not action.allowed
    )
    opens_before_rejection = len(sessions)
    with pytest.raises(ValueError, match="not allowed"):
        recovery_process.execute(
            RecoverCommand(
                str(root),
                interrupted.run_id,
                (
                    f"{rejected_action.code.value}:"
                    f"{rejected_action.finalize_mode.value}"
                    if rejected_action.finalize_mode is not None
                    else rejected_action.code.value
                ),
                "synthetic-approval" if rejected_action.requires_approval else None,
                "synthetic reason" if rejected_action.requires_reason else None,
            )
        )
    assert len(sessions) == opens_before_rejection + 1
    assert sessions[-1].requested == frozenset({"remote_run_ownership"})

    assert all(session.closed for session in sessions)
    assert not any(
        isinstance(value, UnsupportedOutcome)
        for value in (
            observed,
            planned,
            awaiting,
            applied,
            reported,
            verified,
            reconciled,
            restart_report,
            inspected,
            interrupted,
            interrupted_inspection,
        )
    )


def test_saved_plan_preflight_rejects_before_opening_a_session(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    sessions: list[_Session] = []
    runtime = _Runtime()
    files = FakeManagedFiles()
    remote = FakeDevice()

    def open_session(device: object, capabilities: frozenset[str]) -> _Session:
        del device
        session = _Session(files, remote, capabilities)
        sessions.append(session)
        return session

    application = bootstrap(
        BootstrapSettings(
            str(root),
            state_root=str(tmp_path / "state"),
            session_opener=open_session,
            runtime_values=runtime,
            host_key_fingerprint=lambda device: "SHA256:synthetic-host-key",
        )
    )
    planned = application.execute(PlanCommand(str(root), DEVICE_ID))
    assert isinstance(planned, CanonicalPlanOutcome)
    opens_after_plan = len(sessions)

    missing = application.execute(ApplyCommand(str(root), planned.plan_id, ()))
    bad = application.execute(
        ApplyCommand(str(root), planned.plan_id, ("unrelated.scope",))
    )
    runtime.advance(timedelta(hours=2))
    expired = application.execute(ApplyCommand(str(root), planned.plan_id, ("apply",)))

    assert all(isinstance(item, UnsupportedOutcome) for item in (missing, bad, expired))
    assert len(sessions) == opens_after_plan


def test_verification_is_read_only_and_reports_semantic_relations(
    tmp_path: Path,
) -> None:
    from tests.fakes.runtime import FakeManagedEntry

    root = _repository(tmp_path)
    state = tmp_path / "state"
    files = FakeManagedFiles()
    remote = FakeDevice()
    sessions: list[_Session] = []

    def open_session(device: object, capabilities: frozenset[str]) -> _Session:
        del device
        session = _Session(files, remote, capabilities)
        sessions.append(session)
        return session

    application = bootstrap(
        BootstrapSettings(
            str(root),
            state_root=str(state),
            session_opener=open_session,
            runtime_values=_Runtime(),
            host_key_fingerprint=lambda device: "SHA256:synthetic-host-key",
        )
    )
    planned = application.execute(PlanCommand(str(root), DEVICE_ID))
    assert isinstance(planned, CanonicalPlanOutcome)
    applied = application.execute(ApplyCommand(str(root), planned.plan_id, ("apply",)))
    assert isinstance(applied, ApplyOutcome)
    plans_before = tuple((state / "plans").iterdir())

    converged = application.execute(VerifyCommand(str(root), DEVICE_ID))
    assert isinstance(converged, VerifyOutcome)
    assert converged.run_report.status is RunStatus.CONVERGED
    assert sessions[-1].requested == frozenset({"managed_file.read"})

    files.put(MANAGED_PATH, FakeManagedEntry(0o644, b"<smartplaylist/>"))
    divergent = application.execute(VerifyCommand(str(root), DEVICE_ID))
    assert isinstance(divergent, VerifyOutcome)
    assert divergent.run_report.status is RunStatus.FAILED_PARTIAL

    files.put(MANAGED_PATH, FakeManagedEntry(0o644, b"", readable=False))
    unverifiable = application.execute(VerifyCommand(str(root), DEVICE_ID))
    assert isinstance(unverifiable, VerifyOutcome)
    unverifiable_value = decode_json_object(unverifiable.run_report.canonical_bytes)
    resource_results = unverifiable_value["resource_results"]
    assert isinstance(resource_results, list)
    first_result = resource_results[0]
    assert isinstance(first_result, dict)
    assert unverifiable.run_report.status is RunStatus.FAILED_PARTIAL
    assert first_result["verification_outcome"] == "unknown"
    assert tuple((state / "plans").iterdir()) == plans_before
    assert all(
        session.requested == frozenset({"managed_file.read"})
        for session in sessions[-3:]
    )


def test_session_close_failure_preserves_durable_run_result(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    state = tmp_path / "state"
    files = FakeManagedFiles()
    remote = FakeDevice()

    def open_session(device: object, capabilities: frozenset[str]) -> _Session:
        del device
        close_error = (
            OSError("synthetic transport close failure")
            if "managed_file.write" in capabilities
            else None
        )
        return _Session(files, remote, capabilities, close_error=close_error)

    application = bootstrap(
        BootstrapSettings(
            str(root),
            state_root=str(state),
            session_opener=open_session,
            runtime_values=_Runtime(),
            host_key_fingerprint=lambda device: "SHA256:synthetic-host-key",
        )
    )
    planned = application.execute(PlanCommand(str(root), DEVICE_ID))
    assert isinstance(planned, CanonicalPlanOutcome)
    applied = application.execute(ApplyCommand(str(root), planned.plan_id, ("apply",)))

    assert isinstance(applied, ApplyOutcome)
    assert not applied.cleanup_complete
    assert files.entry(MANAGED_PATH) is not None
    reported = application.execute(ReportCommand(str(root), applied.run_id))
    assert isinstance(reported, ReportOutcome)
    assert reported.run_report.run_id == applied.run_id.value
    chain_files = tuple((state / "runs").rglob("*.json"))
    assert any(b"session_close.transport" in path.read_bytes() for path in chain_files)
