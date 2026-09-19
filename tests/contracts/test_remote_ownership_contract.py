import hashlib
import stat

import pytest

from coreelec_reconciler.adapters.paramiko_managed_file import ParamikoManagedFiles
from coreelec_reconciler.adapters.remote_helpers import (
    FixedRemoteHelper,
    RemoteHelperCode,
    RemoteHelperResult,
)
from coreelec_reconciler.adapters.remote_run_ownership import (
    ParamikoRemoteAuthorityBackend,
)
from coreelec_reconciler.domain.execution import MutationDisposition
from coreelec_reconciler.execution.authority import AuthorityBlocked, AuthorityConflict
from tests.adapters.scripted import Entry, ScriptedSFTP

KEY = "a" * 64


class Helper:
    def __init__(self, sftp: ScriptedSFTP) -> None:
        self.sftp = sftp
        self.next = RemoteHelperCode.APPLIED

    def run(
        self, operation: str, object_path: str, expected: str, staged: str
    ) -> RemoteHelperResult:
        if self.next is not RemoteHelperCode.APPLIED:
            return RemoteHelperResult(self.next)
        if operation == "prepare":
            return RemoteHelperResult(RemoteHelperCode.APPLIED)
        if operation == "cleanup":
            if self.sftp.disconnect_on == "remove":
                self.sftp.entries.pop(object_path, None)
                return RemoteHelperResult(RemoteHelperCode.AMBIGUOUS)
            self.sftp.entries.pop(object_path, None)
            return RemoteHelperResult(RemoteHelperCode.APPLIED)
        marker = object_path + "/marker.json"
        if operation in {"replace", "remove", "quarantine"}:
            current = self.sftp.entries.get(marker)
            if current is None or _digest(current.content) != expected:
                return RemoteHelperResult(RemoteHelperCode.CONFLICT)
        if operation in {"create", "replace"}:
            if operation == "create":
                self.sftp.entries[object_path] = Entry(b"", stat.S_IFDIR | 0o700)
            self.sftp.entries[marker] = self.sftp.entries.pop(staged)
        elif operation == "remove":
            del self.sftp.entries[marker]
            del self.sftp.entries[object_path]
        else:
            quarantine_dir = object_path.removesuffix("/ownership") + "/quarantine"
            quarantine = quarantine_dir + "/receipt.json"
            self.sftp.entries[quarantine_dir] = Entry(b"", stat.S_IFDIR | 0o700)
            self.sftp.entries[quarantine] = self.sftp.entries.pop(staged)
            del self.sftp.entries[marker]
            del self.sftp.entries[object_path]
        return RemoteHelperResult(RemoteHelperCode.APPLIED)


def backend() -> tuple[ParamikoRemoteAuthorityBackend, Helper, ScriptedSFTP]:
    sftp = ScriptedSFTP()
    helper = Helper(sftp)
    value = ParamikoRemoteAuthorityBackend(
        ParamikoManagedFiles(sftp),
        helper,  # type: ignore[arg-type]
    )
    return value, helper, sftp


def test_remote_create_replace_and_reread() -> None:
    value, _, _ = backend()
    first = b'{"generation":1}'
    second = b'{"generation":2}'
    value.create_ownership_if_unowned_and_not_quarantined(KEY, first, _digest(first))
    value.replace_ownership(KEY, _digest(first), second, _digest(second))
    assert value.inspect_ownership(KEY).payload == second


@pytest.mark.parametrize(
    "code", [RemoteHelperCode.UNSUPPORTED, RemoteHelperCode.AMBIGUOUS]
)
def test_unsupported_or_ambiguous_durability_fails_closed(
    code: RemoteHelperCode,
) -> None:
    value, helper, _ = backend()
    helper.next = code
    with pytest.raises(AuthorityBlocked, match="durability"):
        value.create_ownership_if_unowned_and_not_quarantined(
            KEY, b"marker", _digest(b"marker")
        )


def test_marker_compare_race_is_typed_conflict() -> None:
    value, _, _ = backend()
    value.create_ownership_if_unowned_and_not_quarantined(
        KEY, b"marker", _digest(b"marker")
    )
    with pytest.raises(AuthorityConflict):
        value.replace_ownership(KEY, "sha256:" + "0" * 64, b"next", _digest(b"next"))


def test_incomplete_or_symlinked_infrastructure_is_unknown() -> None:
    value, _, sftp = backend()
    ownership = "/storage/.coreelec-reconciler/devices/" + KEY + "/ownership"
    sftp.entries[ownership] = Entry(b"", stat.S_IFDIR | 0o700)
    assert value.inspect_ownership(KEY).kind.value == "unknown"
    sftp.entries[ownership] = Entry(b"", stat.S_IFLNK | 0o777)
    assert value.inspect_ownership(KEY).kind.value == "unknown"


def test_cleanup_is_exact_and_ambiguity_is_retained() -> None:
    value, _, sftp = backend()
    path = "/storage/.coreelec-reconciler/runs/run-key/stage/object"
    sftp.entries[path] = Entry(b"staged")
    sftp.disconnect_on = "remove"
    receipts = value.cleanup_manifest_paths((path,), "cleanup")
    assert receipts[0].disposition is MutationDisposition.AMBIGUOUS
    with pytest.raises(ValueError, match="outside"):
        value.cleanup_manifest_paths(("/storage/managed",), "cleanup")


def test_fixed_helper_uses_only_repository_script_and_typed_status() -> None:
    from coreelec_reconciler.adapters.paramiko_session import CommandOutcome
    from tests.adapters.scripted import ScriptedCommands

    commands = ScriptedCommands([CommandOutcome(b"", b"", 69)])
    helper = FixedRemoteHelper(commands)
    result = helper.run(
        "create",
        "/storage/.coreelec-reconciler/devices/key/ownership",
        "sha256:" + "0" * 64,
        "/storage/.coreelec-reconciler/stage/payload",
    )
    assert result.code is RemoteHelperCode.UNSUPPORTED
    assert commands.calls[0][0].startswith("/bin/sh -s -- create ")
    assert b"remove-plus-rename" not in commands.calls[0][1]


def _digest(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()
