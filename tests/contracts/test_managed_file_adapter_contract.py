from collections.abc import Callable

import pytest

from coreelec_reconciler.adapters.paramiko_managed_file import ParamikoManagedFiles
from coreelec_reconciler.domain.execution import MutationDisposition
from coreelec_reconciler.transports.interfaces import ReadFailureCode
from tests.adapters.scripted import Entry, ScriptedSFTP
from tests.fakes.runtime import FakeManagedFiles

PATH = "/storage/file"
STAGED = "/storage/.file.stage"


def _production() -> tuple[object, Callable[[str], bytes | None]]:
    sftp = ScriptedSFTP()
    adapter = ParamikoManagedFiles(sftp)  # type: ignore[arg-type]

    def inspect(path: str) -> bytes | None:
        entry = sftp.entries.get(path)
        return None if entry is None else entry.content

    return adapter, inspect


def _fake() -> tuple[object, Callable[[str], bytes | None]]:
    fake = FakeManagedFiles()

    def inspect(path: str) -> bytes | None:
        entry = fake.entry(path)
        return None if entry is None else entry.content

    return fake, inspect


@pytest.mark.parametrize("factory", [_fake, _production], ids=["fake", "paramiko"])
def test_absent_and_existing_atomic_replace_contract(
    factory: Callable[[], tuple[object, Callable[[str], bytes | None]]],
) -> None:
    files, inspect = factory()
    for old in (None, b"old"):
        if old is not None:
            files.stage_write(PATH, old, 0o644, "seed")  # type: ignore[attr-defined]
        files.stage_write(STAGED, b"new", 0o644, "stage")  # type: ignore[attr-defined]
        receipt = files.atomic_replace(STAGED, PATH, "replace")  # type: ignore[attr-defined]
        assert receipt.disposition is MutationDisposition.APPLIED
        assert inspect(PATH) == b"new"
        assert inspect(STAGED) is None
        files.remove(PATH, "reset")  # type: ignore[attr-defined]


def test_incomplete_production_read_is_typed() -> None:
    sftp = ScriptedSFTP()
    sftp.entries[PATH] = Entry(b"complete")
    sftp.incomplete_read = True
    result = ParamikoManagedFiles(sftp).read(PATH, 100)  # type: ignore[arg-type]
    assert result.failure is not None
    assert result.failure.code is ReadFailureCode.INCOMPLETE


@pytest.mark.parametrize(
    "operation",
    ["write", "chmod", "posix_rename", "remove", "restore", "cleanup"],
)
def test_transport_loss_after_mutation_is_ambiguous(operation: str) -> None:
    sftp = ScriptedSFTP()
    sftp.entries[PATH] = Entry(b"old")
    sftp.entries[STAGED] = Entry(b"new")
    sftp.disconnect_on = {
        "restore": "posix_rename",
        "cleanup": "remove",
    }.get(operation, operation)
    files = ParamikoManagedFiles(sftp)  # type: ignore[arg-type]
    receipt = {
        "write": lambda: files.stage_write("/storage/new", b"new", 0o644, "stage"),
        "chmod": lambda: files.chmod(PATH, 0o600, "chmod"),
        "posix_rename": lambda: files.atomic_replace(STAGED, PATH, "replace"),
        "remove": lambda: files.remove(PATH, "remove"),
        "restore": lambda: files.restore(PATH, b"before", 0o644, "restore"),
        "cleanup": lambda: files.cleanup(PATH, "cleanup"),
    }[operation]()
    assert receipt.disposition is MutationDisposition.AMBIGUOUS


@pytest.mark.parametrize("operation", ["chmod", "remove", "cleanup"])
def test_server_rejection_is_definitely_not_applied(operation: str) -> None:
    files = ParamikoManagedFiles(ScriptedSFTP())  # type: ignore[arg-type]
    receipt = {
        "chmod": lambda: files.chmod(PATH, 0o600, "chmod"),
        "remove": lambda: files.remove(PATH, "remove"),
        "cleanup": lambda: files.cleanup(PATH, "cleanup"),
    }[operation]()
    assert receipt.disposition is MutationDisposition.DEFINITELY_NOT_APPLIED


def test_atomic_replace_has_no_rename_or_remove_then_rename_fallback() -> None:
    sftp = ScriptedSFTP()
    sftp.entries[STAGED] = Entry(b"new")
    files = ParamikoManagedFiles(sftp)  # type: ignore[arg-type]
    assert files.atomic_replace(STAGED, PATH, "replace").disposition is (
        MutationDisposition.APPLIED
    )
    assert sftp.posix_calls == [(STAGED, PATH)]
    assert sftp.rename_calls == []
    assert sftp.remove_calls == []


def test_missing_posix_extension_fails_before_mutation() -> None:
    sftp = ScriptedSFTP()
    sftp.posix_rename = None  # type: ignore[assignment]
    files = ParamikoManagedFiles(sftp)  # type: ignore[arg-type]
    receipt = files.atomic_replace(STAGED, PATH, "replace")
    assert receipt.disposition is MutationDisposition.DEFINITELY_NOT_APPLIED


def test_server_without_posix_extension_returns_definitely_not_applied() -> None:
    sftp = ScriptedSFTP()
    sftp.entries[STAGED] = Entry(b"new")
    sftp.unsupported_posix_rename = True
    files = ParamikoManagedFiles(sftp)  # type: ignore[arg-type]
    receipt = files.atomic_replace(STAGED, PATH, "replace")
    assert receipt.disposition is MutationDisposition.DEFINITELY_NOT_APPLIED
    assert sftp.entries[STAGED].content == b"new"
    assert PATH not in sftp.entries
