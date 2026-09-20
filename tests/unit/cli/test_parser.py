import pytest

from coreelec_reconciler.application.commands import ReconcileCommand, RecoverCommand
from coreelec_reconciler.cli.parser import parse_command
from coreelec_reconciler.domain.identifiers import DeviceId, RunId


def test_provision_is_only_reconcile_syntax_sugar() -> None:
    parsed = parse_command(
        ["--repository-root", "repo", "provision", "device", "--approve", "apply"]
    )

    assert parsed.command == ReconcileCommand("repo", DeviceId("device"), ("apply",))


@pytest.mark.parametrize(
    ("arguments", "action", "approval", "reason"),
    [
        (("inspect",), "inspect", None, None),
        (("resume-verification",), "resume_verification", None, None),
        (("rollback",), "rollback", None, None),
        (("finalize", "--mode", "normal"), "finalize:normal", None, None),
        (
            (
                "finalize",
                "--mode",
                "abandon",
                "--approve",
                "recover.abandon",
                "--reason",
                "Device reimage scheduled",
            ),
            "finalize:abandon",
            "recover.abandon",
            "Device reimage scheduled",
        ),
    ],
)
def test_recovery_commands_are_closed_and_typed(
    arguments: tuple[str, ...],
    action: str,
    approval: str | None,
    reason: str | None,
) -> None:
    parsed = parse_command(["recover", "run", *arguments])

    assert parsed.command == RecoverCommand(".", RunId("run"), action, approval, reason)


@pytest.mark.parametrize(
    "arguments",
    [
        ("recover", "run", "finalize"),
        ("recover", "run", "finalize", "--mode", "abandon"),
        (
            "recover",
            "run",
            "finalize",
            "--mode",
            "abandon",
            "--approve",
            "yes",
            "--reason",
            "reason",
        ),
        (
            "recover",
            "run",
            "finalize",
            "--mode",
            "abandon",
            "--approve",
            "recover.abandon",
            "--reason",
            " ",
        ),
        ("recover", "run", "rollback", "--approve", "recover.abandon"),
        ("recover", "run", "finalize", "--mode", "normal", "--reason", "unused"),
    ],
)
def test_invalid_recovery_authority_is_a_usage_error(
    arguments: tuple[str, ...],
) -> None:
    with pytest.raises(SystemExit) as raised:
        parse_command(arguments)

    assert raised.value.code == 2


def test_quiet_is_explicit_and_noninteractive() -> None:
    parsed = parse_command(["--quiet", "verify", "device"])

    assert parsed.quiet is True
