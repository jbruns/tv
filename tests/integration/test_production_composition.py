from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

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


@dataclass
class _Session:
    files: FakeManagedFiles
    remote: FakeDevice
    requested: frozenset[str]
    closed: bool = False

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

    applied = application.execute(ApplyCommand(str(root), planned.plan_id, ("apply",)))
    assert isinstance(applied, ApplyOutcome)
    assert applied.cleanup_complete
    assert files.entry(MANAGED_PATH) is not None
    reported = application.execute(ReportCommand(str(root), applied.run_id))
    assert isinstance(reported, ReportOutcome)
    assert reported.run_report.current_digest == applied.run_report.current_digest

    verified = application.execute(VerifyCommand(str(root), DEVICE_ID))
    assert isinstance(verified, VerifyOutcome)

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
