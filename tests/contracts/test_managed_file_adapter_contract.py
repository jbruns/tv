from collections.abc import Callable
from functools import partial
from typing import Any, cast

import paramiko
import pytest

from coreelec_reconciler.adapters.paramiko_managed_file import ParamikoManagedFiles
from coreelec_reconciler.domain.execution import MutationDisposition
from coreelec_reconciler.transports.interfaces import ReadFailureCode
from tests.adapters.scripted import Entry, ScriptedNoFollowReader, ScriptedSFTP
from tests.fakes.runtime import FakeManagedEntry, FakeManagedFiles

PATH = "/storage/file"
STAGED = "/storage/.file.stage"


def _production() -> tuple[object, Callable[[str], bytes | None]]:
    sftp = ScriptedSFTP()
    adapter = ParamikoManagedFiles(
        cast(paramiko.SFTPClient, sftp), ScriptedNoFollowReader(sftp)
    )

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
    reader = ScriptedNoFollowReader(sftp)
    reader.failure = ReadFailureCode.INCOMPLETE
    result = ParamikoManagedFiles(cast(paramiko.SFTPClient, sftp), reader).read(
        PATH, 100
    )
    assert result.failure is not None
    assert result.failure.code is ReadFailureCode.INCOMPLETE


def test_production_read_never_uses_racy_sftp_open() -> None:
    sftp = ScriptedSFTP()
    sftp.entries[PATH] = Entry(b"before")
    files = ParamikoManagedFiles(sftp)  # type: ignore[arg-type]
    result = files.read(PATH, 100)
    assert result.failure is not None
    assert result.failure.code is ReadFailureCode.UNSAFE
    assert sftp.closed_handles == 0


def test_no_follow_reader_rejects_symlink_swap() -> None:
    import stat

    sftp = ScriptedSFTP()
    sftp.entries[PATH] = Entry(b"before")
    reader = ScriptedNoFollowReader(sftp)
    reader.before_read = lambda: sftp.entries.__setitem__(
        PATH, Entry(b"/private/other", stat.S_IFLNK | 0o777)
    )
    result = ParamikoManagedFiles(cast(paramiko.SFTPClient, sftp), reader).read(
        PATH, 100
    )
    assert result.failure is not None
    assert result.failure.code is ReadFailureCode.UNSAFE


def test_no_follow_reader_enforces_oversize_bound() -> None:
    sftp = ScriptedSFTP()
    sftp.entries[PATH] = Entry(b"oversize")
    result = ParamikoManagedFiles(
        cast(paramiko.SFTPClient, sftp), ScriptedNoFollowReader(sftp)
    ).read(PATH, 3)
    assert result.failure is not None
    assert result.failure.code is ReadFailureCode.TOO_LARGE


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


@pytest.mark.parametrize("adapter_kind", ["fake", "paramiko"])
@pytest.mark.parametrize(
    "primitive",
    ["stage_write", "chmod", "atomic_replace", "remove", "restore", "cleanup"],
)
@pytest.mark.parametrize("applied", [False, True])
def test_all_mutation_ambiguity_twins_share_fake_production_contract(
    adapter_kind: str, primitive: str, applied: bool
) -> None:
    files: Any
    inspect: Callable[[str], Any]
    if adapter_kind == "fake":
        fake = FakeManagedFiles()
        fake.put(PATH, FakeManagedEntry(0o644, b"old"))
        fake.put(STAGED, FakeManagedEntry(0o600, b"new"))
        fake.lost_ack(primitive, applied=applied)
        files = fake
        inspect = partial(_fake_entry, fake)
    else:
        sftp = ScriptedSFTP()
        sftp.entries[PATH] = Entry(b"old")
        sftp.entries[STAGED] = Entry(b"new", 0o600)
        sftp.disconnect_applied = applied
        sftp.disconnect_on = {
            "stage_write": "write" if applied else "open",
            "chmod": "chmod",
            "atomic_replace": "posix_rename",
            "remove": "remove",
            "restore": "posix_rename" if applied else "open",
            "cleanup": "remove",
        }[primitive]
        files = ParamikoManagedFiles(
            cast(paramiko.SFTPClient, sftp), ScriptedNoFollowReader(sftp)
        )
        inspect = partial(_production_entry, sftp)

    receipt = {
        "stage_write": lambda: files.stage_write(
            "/storage/new", b"value", 0o600, "stage"
        ),
        "chmod": lambda: files.chmod(PATH, 0o600, "chmod"),
        "atomic_replace": lambda: files.atomic_replace(STAGED, PATH, "replace"),
        "remove": lambda: files.remove(PATH, "remove"),
        "restore": lambda: files.restore(PATH, b"before", 0o640, "restore"),
        "cleanup": lambda: files.cleanup(PATH, "cleanup"),
    }[primitive]()

    assert receipt.disposition is MutationDisposition.AMBIGUOUS
    if primitive == "stage_write":
        assert (inspect("/storage/new") is not None) is applied
    elif primitive == "chmod":
        entry = inspect(PATH)
        assert entry is not None
        assert entry.mode & 0o777 == (0o600 if applied else 0o644)
    elif primitive == "atomic_replace":
        entry = inspect(PATH)
        assert entry is not None
        assert entry.content == (b"new" if applied else b"old")
        assert (inspect(STAGED) is None) is applied
    elif primitive in {"remove", "cleanup"}:
        assert (inspect(PATH) is None) is applied
    else:
        entry = inspect(PATH)
        assert entry is not None
        assert entry.content == (b"before" if applied else b"old")


def _fake_entry(files: FakeManagedFiles, path: str) -> FakeManagedEntry | None:
    return files.entry(path)


def _production_entry(sftp: ScriptedSFTP, path: str) -> Entry | None:
    return sftp.entries.get(path)
