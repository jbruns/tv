"""Argument parsing for the command-line interface."""

import argparse
from collections.abc import Sequence
from dataclasses import dataclass
from importlib.metadata import version
from typing import Literal, assert_never, cast

from coreelec_reconciler.application.commands import (
    ActionCommand,
    ApplyCommand,
    Command,
    DeviceId,
    InventoryCommand,
    ObserveCommand,
    PlanCommand,
    PlanId,
    ReconcileCommand,
    RecoverCommand,
    ReportCommand,
    RunId,
    ValidateCommand,
    VerifyCommand,
)


@dataclass(frozen=True, slots=True)
class ParsedCommand:
    repository_root: str
    command: Command


type CommandName = Literal[
    "validate",
    "inventory",
    "observe",
    "plan",
    "apply",
    "reconcile",
    "provision",
    "verify",
    "recover",
    "report",
    "action",
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="coreelec-reconciler",
        description="Reconcile CoreELEC Device Desired State.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {version('coreelec-reconciler')}",
    )
    parser.add_argument("--repository-root", default=".")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("--device-id")
    validate_parser.add_argument("--observations")
    subparsers.add_parser("inventory")

    for name in ("observe", "plan", "reconcile", "provision", "verify"):
        command_parser = subparsers.add_parser(name)
        command_parser.add_argument("device_id")
        if name == "plan":
            command_parser.add_argument("--observations", required=True)
        if name in {"reconcile", "provision"}:
            command_parser.add_argument(
                "--approve",
                dest="approval_scopes",
                action="append",
                default=[],
            )

    apply_parser = subparsers.add_parser("apply")
    apply_parser.add_argument("plan_id")
    apply_parser.add_argument(
        "--approve",
        dest="approval_scopes",
        action="append",
        default=[],
    )

    recover_parser = subparsers.add_parser("recover")
    recover_parser.add_argument("run_id")
    recover_parser.add_argument("action")

    report_parser = subparsers.add_parser("report")
    report_parser.add_argument("run_id")

    action_parser = subparsers.add_parser("action")
    action_parser.add_argument("action_code")
    return parser


def parse_command(argv: Sequence[str] | None = None) -> ParsedCommand:
    args = build_parser().parse_args(argv)
    repository_root = cast(str, args.repository_root)
    command_name = cast(CommandName, args.command)

    match command_name:
        case "validate":
            device_id = cast(str | None, args.device_id)
            command: Command = ValidateCommand(
                repository_root,
                None if device_id is None else DeviceId(device_id),
                cast(str | None, args.observations),
            )
        case "inventory":
            command = InventoryCommand(repository_root)
        case "observe":
            command = ObserveCommand(
                repository_root,
                DeviceId(cast(str, args.device_id)),
            )
        case "plan":
            command = PlanCommand(
                repository_root,
                DeviceId(cast(str, args.device_id)),
                cast(str, args.observations),
            )
        case "apply":
            command = ApplyCommand(
                repository_root,
                PlanId(cast(str, args.plan_id)),
                tuple(cast(list[str], args.approval_scopes)),
            )
        case "reconcile" | "provision":
            command = ReconcileCommand(
                repository_root,
                DeviceId(cast(str, args.device_id)),
                tuple(cast(list[str], args.approval_scopes)),
            )
        case "verify":
            command = VerifyCommand(
                repository_root,
                DeviceId(cast(str, args.device_id)),
            )
        case "recover":
            command = RecoverCommand(
                repository_root,
                RunId(cast(str, args.run_id)),
                cast(str, args.action),
            )
        case "report":
            command = ReportCommand(
                repository_root,
                RunId(cast(str, args.run_id)),
            )
        case "action":
            command = ActionCommand(repository_root, cast(str, args.action_code))
        case _ as unreachable:
            assert_never(unreachable)

    return ParsedCommand(repository_root=repository_root, command=command)
