import hashlib
import io
import shutil
import stat
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

from coreelec_reconciler.adapters.managed_mutation_helper import (
    _HELPER,
    FixedManagedMutationHelper,
    ManagedMutationCode,
)
from coreelec_reconciler.adapters.paramiko_session import (
    CommandFailureCode,
    CommandOutcome,
)
from coreelec_reconciler.domain.execution import NormalizedResourceState, Presence

BINDING = "sha256:" + "b" * 64
ABSENT = NormalizedResourceState(Presence.ABSENT, None, None, None)
pytestmark = pytest.mark.skipif(
    sys.platform != "linux",
    reason="the production helper requires Linux renameat2",
)


def _state(path: Path) -> NormalizedResourceState:
    content = path.read_bytes()
    return NormalizedResourceState(
        Presence.PRESENT,
        "regular",
        "sha256:" + hashlib.sha256(content).hexdigest(),
        stat.S_IMODE(path.stat().st_mode),
    )


class LocalCommands:
    def __init__(self) -> None:
        self.lose_ack: str | None = None

    def execute(
        self, command: str, *, stdin: bytes = b"", timeout: float = 15.0
    ) -> CommandOutcome:
        del command, timeout
        if self.lose_ack == "before":
            return CommandOutcome(b"", b"", None, CommandFailureCode.DISCONNECTED)
        original_stdin = sys.stdin
        sys.stdin = io.TextIOWrapper(io.BytesIO(stdin))
        try:
            exec(compile(_HELPER, "<managed-mutation-helper>", "exec"), {})
        except SystemExit as error:
            exit_status = error.code if isinstance(error.code, int) else 1
        finally:
            sys.stdin = original_stdin
        if self.lose_ack == "after":
            return CommandOutcome(b"", b"", None, CommandFailureCode.DISCONNECTED)
        return CommandOutcome(b"", b"", exit_status)


@pytest.fixture
def device_root() -> Iterator[Path]:
    root = Path.cwd() / f".ci-test.managed-cas-{uuid.uuid4().hex}"
    root.mkdir(mode=0o700)
    try:
        yield root
    finally:
        shutil.rmtree(root)


def test_server_helper_successful_create_update_mode_remove_restore_cleanup(
    device_root: Path,
) -> None:
    helper = FixedManagedMutationHelper(LocalCommands())
    destination = device_root / "managed"
    staged = device_root / f".managed.stage.{BINDING[7:]}.stage"

    assert helper.supported()
    assert (
        helper.mutate(
            "stage",
            str(staged),
            "stage",
            BINDING,
            ABSENT,
            content=b"new",
            mode=0o600,
        ).code
        is ManagedMutationCode.APPLIED
    )
    assert (
        helper.mutate(
            "replace",
            str(destination),
            "create",
            BINDING,
            ABSENT,
            staged_path=str(staged),
            expected_staged=_state(staged),
        ).code
        is ManagedMutationCode.APPLIED
    )
    staged.write_bytes(b"updated")
    staged.chmod(0o600)
    assert (
        helper.mutate(
            "replace",
            str(destination),
            "update",
            BINDING,
            _state(destination),
            staged_path=str(staged),
            expected_staged=_state(staged),
        ).code
        is ManagedMutationCode.APPLIED
    )
    assert destination.read_bytes() == b"updated"
    before_chmod = _state(destination)
    assert (
        helper.mutate(
            "chmod",
            str(destination),
            "chmod",
            BINDING,
            before_chmod,
            mode=0o640,
        ).code
        is ManagedMutationCode.APPLIED
    )
    assert stat.S_IMODE(destination.stat().st_mode) == 0o640
    assert (
        helper.mutate(
            "restore",
            str(destination),
            "restore",
            BINDING,
            _state(destination),
            content=b"old",
            mode=0o644,
        ).code
        is ManagedMutationCode.APPLIED
    )
    assert destination.read_bytes() == b"old"
    assert (
        helper.mutate(
            "remove",
            str(destination),
            "remove",
            BINDING,
            _state(destination),
        ).code
        is ManagedMutationCode.APPLIED
    )
    assert (
        helper.mutate(
            "cleanup",
            str(staged),
            "cleanup",
            BINDING,
            ABSENT,
        ).code
        is ManagedMutationCode.APPLIED
    )
    assert not destination.exists()


@pytest.mark.parametrize("change", ["digest", "mode", "type", "final-symlink"])
def test_server_helper_rejects_changed_target_without_touching_outside(
    device_root: Path,
    change: str,
) -> None:
    helper = FixedManagedMutationHelper(LocalCommands())
    destination = device_root / "managed"
    outside = device_root / "outside"
    destination.write_bytes(b"old")
    destination.chmod(0o644)
    expected = _state(destination)
    outside.write_bytes(b"outside")
    if change == "digest":
        destination.write_bytes(b"third-party")
    elif change == "mode":
        destination.chmod(0o600)
    elif change == "type":
        destination.unlink()
        destination.mkdir()
    else:
        destination.unlink()
        destination.symlink_to(outside)

    result = helper.mutate(
        "remove",
        str(destination),
        "remove",
        BINDING,
        expected,
    )

    assert result.code in {
        ManagedMutationCode.PRECONDITION_CHANGED,
        ManagedMutationCode.UNSAFE,
    }
    assert outside.read_bytes() == b"outside"
    assert destination.exists()


def test_server_helper_rejects_ancestor_symlink_swap(
    device_root: Path,
) -> None:
    helper = FixedManagedMutationHelper(LocalCommands())
    parent = device_root / "parent"
    original = device_root / "original"
    outside = device_root / "outside"
    parent.mkdir()
    outside.mkdir()
    destination = parent / "managed"
    destination.write_bytes(b"old")
    destination.chmod(0o644)
    expected = _state(destination)
    outside_target = outside / "managed"
    outside_target.write_bytes(b"outside")
    parent.rename(original)
    parent.symlink_to(outside, target_is_directory=True)

    result = helper.mutate(
        "chmod",
        str(destination),
        "chmod",
        BINDING,
        expected,
        mode=0o600,
    )

    assert result.code is ManagedMutationCode.UNSAFE
    assert outside_target.read_bytes() == b"outside"
    assert stat.S_IMODE(outside_target.stat().st_mode) != 0o600
    assert (original / "managed").read_bytes() == b"old"


def test_server_helper_rejects_substituted_stage(device_root: Path) -> None:
    helper = FixedManagedMutationHelper(LocalCommands())
    destination = device_root / "managed"
    staged = device_root / f".managed.stage.{BINDING[7:]}.stage"
    destination.write_bytes(b"old")
    destination.chmod(0o644)
    staged.write_bytes(b"expected")
    staged.chmod(0o600)
    expected_staged = _state(staged)
    staged.write_bytes(b"third-party")

    result = helper.mutate(
        "replace",
        str(destination),
        "replace",
        BINDING,
        _state(destination),
        staged_path=str(staged),
        expected_staged=expected_staged,
    )

    assert result.code is ManagedMutationCode.PRECONDITION_CHANGED
    assert destination.read_bytes() == b"old"
    assert staged.read_bytes() == b"third-party"


@pytest.mark.parametrize("applied", [False, True])
def test_server_helper_lost_ack_is_ambiguous(device_root: Path, applied: bool) -> None:
    commands = LocalCommands()
    commands.lose_ack = "after" if applied else "before"
    helper = FixedManagedMutationHelper(commands)
    destination = device_root / f".managed.stage.{BINDING[7:]}.stage"

    result = helper.mutate(
        "stage",
        str(destination),
        "stage",
        BINDING,
        ABSENT,
        content=b"value",
        mode=0o600,
    )

    assert result.code is ManagedMutationCode.AMBIGUOUS
    assert destination.exists() is applied


def test_server_helper_does_not_interpolate_command_or_path(
    device_root: Path,
) -> None:
    commands = LocalCommands()
    helper = FixedManagedMutationHelper(commands)
    dangerous_parent = device_root / "a;touch injected"
    dangerous_parent.mkdir()
    destination = dangerous_parent / f"$(command).{BINDING[7:]}.stage"

    result = helper.mutate(
        "stage",
        str(destination),
        "change;$(id)",
        BINDING,
        ABSENT,
        content=b"`command`;$(other)",
        mode=0o600,
    )

    assert result.code is ManagedMutationCode.APPLIED
    assert destination.read_bytes() == b"`command`;$(other)"
    assert not (Path.cwd() / "injected").exists()


def test_server_helper_rejects_stage_bound_to_another_run(
    device_root: Path,
) -> None:
    helper = FixedManagedMutationHelper(LocalCommands())
    destination = device_root / f".managed.stage.{BINDING[7:]}.stage"

    result = helper.mutate(
        "stage",
        str(destination),
        "stage",
        "sha256:" + "c" * 64,
        ABSENT,
        content=b"value",
        mode=0o600,
    )

    assert result.code is ManagedMutationCode.PRECONDITION_CHANGED
    assert not destination.exists()
