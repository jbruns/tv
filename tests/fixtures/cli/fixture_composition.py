import logging
import os
import sys

from coreelec_reconciler.application.commands import (
    ApplyCommand,
    ObserveCommand,
    ReconcileCommand,
    RecoverCommand,
    ReportCommand,
    VerifyCommand,
)
from coreelec_reconciler.application.outcomes import (
    ApplyOutcome,
    ApprovalResolution,
    ObservationOutcome,
    PlanOutcome,
    ReconcileOutcome,
    RecoverOutcome,
    RecoveryInspectionOutcome,
    ReportOutcome,
    ValidationOutcome,
    VerifyOutcome,
)
from coreelec_reconciler.application.reconciler import (
    ApplicationDependencies,
    ApplicationReconciler,
)
from coreelec_reconciler.bootstrap import BootstrapSettings
from coreelec_reconciler.domain.execution import (
    AllowedRecoveryAction,
    FinalizeMode,
    RecoveryActionCode,
    RunStatus,
)
from coreelec_reconciler.domain.identifiers import PlanId, RunId
from coreelec_reconciler.domain.planning import (
    CanonicalPlan,
    CanonicalRunReport,
    PlanDisposition,
)


def _report(run_id: str, status: RunStatus) -> CanonicalRunReport:
    content = (
        f'{{"kind":"CoreElecReconcilerRunReport","run_id":"{run_id}",'
        f'"status":"{status.value}"}}'
    ).encode()
    return CanonicalRunReport(content, run_id, "sha256:digest", 7, status)


PLAN = CanonicalPlan(
    b'{"kind":"CoreElecReconcilerPlan","plan_id":"plan-85"}',
    "plan-85",
    "sha256:full",
    "sha256:semantic",
    PlanDisposition.ACTIONABLE,
)


class _Workflows:
    def observe(self, command: ObserveCommand) -> ObservationOutcome:
        return ObservationOutcome(_report("observe-85", RunStatus.NOOP))

    def apply(self, command: ApplyCommand) -> ApplyOutcome:
        return ApplyOutcome(_report("apply-85", _scenario_status()), True)

    def reconcile(self, command: ReconcileCommand) -> ReconcileOutcome:
        if not command.approval_scopes:
            return ReconcileOutcome(
                _report("planning-85", RunStatus.AWAITING_APPROVAL),
                PLAN,
                None,
                None,
                ApprovalResolution(
                    ("apply", "impact.restart"),
                    (),
                    ("apply", "impact.restart"),
                ),
            )
        status = _scenario_status()
        cleanup_complete = os.environ.get("CLI_SCENARIO") != "cleanup-unresolved"
        return ReconcileOutcome(
            _report("planning-85", RunStatus.AWAITING_APPROVAL),
            PLAN,
            _report("execution-85", status),
            cleanup_complete,
            ApprovalResolution(
                ("apply",),
                ("apply",),
                (),
            ),
        )

    def verify(self, command: VerifyCommand) -> VerifyOutcome:
        print(os.environ.get("CLI_SECRET_SENTINEL", "bootstrap-noise"))
        logging.warning("logging-noise")
        print("progress: observed caf\u00e9 Resource", file=sys.stderr)
        if os.environ.get("CLI_SCENARIO") == "defect":
            raise RuntimeError("secret-never-render /private/controller/path")
        return VerifyOutcome(_report("verify-85", _scenario_status()))

    def recover(
        self, command: RecoverCommand
    ) -> RecoverOutcome | RecoveryInspectionOutcome:
        if command.action == "inspect":
            return RecoveryInspectionOutcome(
                _report("execution-85", RunStatus.FAILED_RECOVERY_REQUIRED),
                (
                    AllowedRecoveryAction(
                        RecoveryActionCode.INSPECT,
                        None,
                        True,
                        "inspect",
                        False,
                        False,
                    ),
                    AllowedRecoveryAction(
                        RecoveryActionCode.RESUME_VERIFICATION,
                        None,
                        True,
                        "resume",
                        False,
                        False,
                    ),
                    AllowedRecoveryAction(
                        RecoveryActionCode.ROLLBACK,
                        None,
                        False,
                        "unsafe",
                        False,
                        False,
                    ),
                    AllowedRecoveryAction(
                        RecoveryActionCode.FINALIZE,
                        FinalizeMode.ABANDON,
                        True,
                        "abandon",
                        True,
                        True,
                    ),
                ),
                False,
            )
        status = (
            RunStatus.FAILED_RECOVERY_REQUIRED
            if command.action == "finalize:abandon"
            else _scenario_status()
        )
        return RecoverOutcome(_report("execution-85", status), True)

    def report(self, command: ReportCommand) -> ReportOutcome:
        return ReportOutcome(_report(command.run_id.value, _scenario_status()))


def _scenario_status() -> RunStatus:
    return {
        "known-failure": RunStatus.FAILED_PARTIAL,
        "recovery-required": RunStatus.FAILED_RECOVERY_REQUIRED,
        "rollback": RunStatus.FAILED_ROLLED_BACK,
    }.get(os.environ.get("CLI_SCENARIO", ""), RunStatus.CONVERGED)


def application_factory(settings: BootstrapSettings) -> ApplicationReconciler:
    return ApplicationReconciler(
        dependencies=ApplicationDependencies(
            _Workflows(),
            lambda command: ValidationOutcome(True, (), 0, "", (), ()),
            lambda command: PlanOutcome(
                RunId("planning-85"),
                PlanId("plan-85"),
                "actionable",
                PLAN,
                _report("planning-85", RunStatus.AWAITING_APPROVAL),
            ),
        )
    )
