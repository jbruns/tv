import hashlib
import json
import stat
from typing import cast

import paramiko
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
from coreelec_reconciler.domain.execution import (
    MutationDisposition,
    RemoteMarkerPhase,
    RemoteOwnershipIdentity,
    WorkspaceId,
)
from coreelec_reconciler.domain.identifiers import DeviceId, RunId
from coreelec_reconciler.execution.authority import (
    _RemoteAuthority,
)
from coreelec_reconciler.transports.remote_ownership import (
    AuthorityBlocked,
    AuthorityConflict,
    RemoteAuthorityBackend,
)
from tests.adapters.scripted import (
    Entry,
    ScriptedManagedMutationHelper,
    ScriptedNoFollowReader,
    ScriptedSFTP,
)
from tests.fakes.device import FakeDevice

KEY = "a" * 64
WORKSPACE_KEY = "b" * 64


class Helper:
    def __init__(self, sftp: ScriptedSFTP) -> None:
        self.sftp = sftp
        self.next = RemoteHelperCode.APPLIED
        self.apply_on_ambiguous = False
        self.fault_operation: str | None = None
        self.inspection_unknown = False

    def run(
        self, operation: str, object_path: str, expected: str, staged: str
    ) -> RemoteHelperResult:
        result = (
            self.next
            if self.fault_operation is None or self.fault_operation == operation
            else RemoteHelperCode.APPLIED
        )
        if result is not RemoteHelperCode.APPLIED and not (
            result is RemoteHelperCode.AMBIGUOUS and self.apply_on_ambiguous
        ):
            return RemoteHelperResult(self.next)
        if operation == "prepare":
            return RemoteHelperResult(RemoteHelperCode.APPLIED)
        if operation == "inspect_cleanup":
            if self.inspection_unknown:
                return RemoteHelperResult(RemoteHelperCode.FAILED)
            return RemoteHelperResult(
                RemoteHelperCode.CONFLICT
                if object_path in self.sftp.entries
                else RemoteHelperCode.APPLIED
            )
        if operation == "cleanup":
            if self.sftp.disconnect_on == "remove":
                self.sftp.entries.pop(object_path, None)
                return RemoteHelperResult(RemoteHelperCode.AMBIGUOUS)
            self.sftp.entries.pop(object_path, None)
            return RemoteHelperResult(RemoteHelperCode.APPLIED)
        marker = object_path + "/marker.json"
        if operation == "create" and object_path in self.sftp.entries:
            return RemoteHelperResult(RemoteHelperCode.CONFLICT)
        if operation in {"replace", "remove", "quarantine"}:
            current = self.sftp.entries.get(marker)
            if current is None:
                return RemoteHelperResult(RemoteHelperCode.CONFLICT)
            if stat.S_IFMT(current.mode) != stat.S_IFREG:
                return RemoteHelperResult(RemoteHelperCode.UNSAFE)
            if _digest(current.content) != expected:
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
        return RemoteHelperResult(result)


def backend() -> tuple[ParamikoRemoteAuthorityBackend, Helper, ScriptedSFTP]:
    sftp = ScriptedSFTP()
    helper = Helper(sftp)
    value = ParamikoRemoteAuthorityBackend(
        ParamikoManagedFiles(
            cast(paramiko.SFTPClient, sftp),
            ScriptedNoFollowReader(sftp),
            ScriptedManagedMutationHelper(sftp),
        ),
        helper,
        workspace_key=WORKSPACE_KEY,
    )
    return value, helper, sftp


def _authority_backend(kind: str) -> RemoteAuthorityBackend:
    if kind == "fake":
        return FakeDevice()
    return backend()[0]


def _identity() -> RemoteOwnershipIdentity:
    return RemoteOwnershipIdentity(
        DeviceId("device.test"),
        RunId("run.test"),
        WorkspaceId("workspace:test"),
        "plan.test",
        "sha256:plan",
        "sha256:binding",
        "boot.test",
    )


@pytest.mark.parametrize("adapter_kind", ["fake", "paramiko"])
@pytest.mark.parametrize("terminal", ["release", "quarantine"])
def test_shared_ownership_lifecycle_contract(adapter_kind: str, terminal: str) -> None:
    authority = _RemoteAuthority(_authority_backend(adapter_kind))
    owned = authority.acquire_exclusive(
        _identity(), b"token", updated_at="2026-09-19T00:00:00Z"
    )
    if terminal == "release":
        pending = authority.compare_and_update(
            owned,
            b"token",
            RemoteMarkerPhase.ACQUIRED,
            RemoteMarkerPhase.TERMINAL_RELEASE_PENDING,
            "sha256:terminal",
            updated_at="2026-09-19T00:00:01Z",
        )
        receipt = authority.release(pending, b"token", "sha256:terminal")
        assert receipt.disposition is MutationDisposition.APPLIED
    else:
        pending = authority.compare_and_update(
            owned,
            b"token",
            RemoteMarkerPhase.ACQUIRED,
            RemoteMarkerPhase.QUARANTINE_PENDING,
            None,
            updated_at="2026-09-19T00:00:01Z",
        )
        result = authority.quarantine(
            pending,
            b"token",
            "sha256:incident",
            updated_at="2026-09-19T00:00:02Z",
        )
        assert result.incident_receipt_digest == "sha256:incident"


def test_remote_create_replace_and_reread() -> None:
    value, _, _ = backend()
    first = b'{"generation":1}'
    second = b'{"generation":2}'
    value.create_ownership_if_unowned_and_not_quarantined(KEY, first, _digest(first))
    value.replace_ownership(KEY, _digest(first), second, _digest(second))
    assert value.inspect_ownership(KEY).payload == second


@pytest.mark.parametrize(
    ("code", "error"),
    [
        (RemoteHelperCode.UNSUPPORTED, AuthorityBlocked),
        (RemoteHelperCode.AMBIGUOUS, AuthorityConflict),
    ],
)
def test_unsupported_or_ambiguous_durability_fails_closed(
    code: RemoteHelperCode, error: type[Exception]
) -> None:
    value, helper, _ = backend()
    helper.next = code
    helper.fault_operation = "create"
    with pytest.raises(error):
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
    path = f"/storage/.coreelec-reconciler/runs/{WORKSPACE_KEY}/stage/object"
    sftp.entries[path] = Entry(b"staged")
    sftp.disconnect_on = "remove"
    receipts = value.cleanup_manifest_paths((path,), "cleanup")
    assert receipts[0].disposition is MutationDisposition.APPLIED
    with pytest.raises(ValueError, match="outside"):
        value.cleanup_manifest_paths(("/storage/managed",), "cleanup")
    with pytest.raises(ValueError, match="outside"):
        value.cleanup_manifest_paths(
            ("/storage/.coreelec-reconciler/runs/" + "c" * 64 + "/stage/foreign",),
            "cleanup",
        )


@pytest.mark.parametrize(
    ("object_survives", "expected"),
    [
        (False, MutationDisposition.APPLIED),
        (True, MutationDisposition.DEFINITELY_NOT_APPLIED),
    ],
)
def test_cleanup_ambiguity_is_reinspected(
    object_survives: bool, expected: MutationDisposition
) -> None:
    value, helper, sftp = backend()
    path = f"/storage/.coreelec-reconciler/runs/{WORKSPACE_KEY}/stage/object"
    sftp.entries[path] = Entry(b"staged")
    helper.next = RemoteHelperCode.AMBIGUOUS
    helper.fault_operation = "cleanup"
    helper.apply_on_ambiguous = not object_survives
    receipt = value.cleanup_manifest_paths((path,), "cleanup")[0]
    assert receipt.disposition is expected


def test_cleanup_unknown_inspection_retains_ambiguity() -> None:
    value, helper, sftp = backend()
    path = f"/storage/.coreelec-reconciler/runs/{WORKSPACE_KEY}/stage/object"
    sftp.entries[path] = Entry(b"staged")
    helper.next = RemoteHelperCode.AMBIGUOUS
    helper.fault_operation = "cleanup"
    helper.inspection_unknown = True
    receipt = value.cleanup_manifest_paths((path,), "cleanup")[0]
    assert receipt.disposition is MutationDisposition.AMBIGUOUS


def test_same_payload_is_staged_under_distinct_run_roots() -> None:
    sftp = ScriptedSFTP()
    helper = Helper(sftp)
    files = ParamikoManagedFiles(
        cast(paramiko.SFTPClient, sftp),
        ScriptedNoFollowReader(sftp),
        ScriptedManagedMutationHelper(sftp),
    )
    first = ParamikoRemoteAuthorityBackend(files, helper, workspace_key=WORKSPACE_KEY)
    second = ParamikoRemoteAuthorityBackend(
        files,
        helper,
        workspace_key="c" * 64,
    )
    payload = b"same"
    helper.next = RemoteHelperCode.FAILED
    helper.fault_operation = "create"
    with pytest.raises(AuthorityBlocked):
        first.create_ownership_if_unowned_and_not_quarantined(
            KEY, payload, _digest(payload)
        )
    with pytest.raises(AuthorityBlocked):
        second.create_ownership_if_unowned_and_not_quarantined(
            "d" * 64, payload, _digest(payload)
        )
    staged = tuple(path for path in sftp.entries if "/stage/" in path)
    assert len(staged) == 2
    assert any(f"/runs/{WORKSPACE_KEY}/stage/" in path for path in staged)
    assert any(f"/runs/{'c' * 64}/stage/" in path for path in staged)


def test_failed_marker_create_leaves_only_manifest_cleanup_object() -> None:
    value, helper, sftp = backend()
    helper.next = RemoteHelperCode.FAILED
    helper.fault_operation = "create"
    with pytest.raises(AuthorityBlocked):
        value.create_ownership_if_unowned_and_not_quarantined(
            KEY, b"marker", _digest(b"marker")
        )
    staged_paths = tuple(path for path in sftp.entries if "/stage/" in path)
    assert len(staged_paths) == 1
    staged = staged_paths[0]
    assert staged in sftp.entries
    helper.next = RemoteHelperCode.APPLIED
    receipts = value.cleanup_created_objects("cleanup")
    assert receipts[0].disposition is MutationDisposition.APPLIED
    assert staged not in sftp.entries


@pytest.mark.parametrize("applied", [False, True])
def test_create_ambiguity_twin_is_reconciled(applied: bool) -> None:
    value, helper, _ = backend()
    helper.next = RemoteHelperCode.AMBIGUOUS
    helper.fault_operation = "create"
    helper.apply_on_ambiguous = applied
    if applied:
        value.create_ownership_if_unowned_and_not_quarantined(
            KEY, b"marker", _digest(b"marker")
        )
        assert value.inspect_ownership(KEY).payload == b"marker"
    else:
        with pytest.raises(AuthorityConflict):
            value.create_ownership_if_unowned_and_not_quarantined(
                KEY, b"marker", _digest(b"marker")
            )


@pytest.mark.parametrize("applied", [False, True])
def test_replace_ambiguity_twin_is_reconciled(applied: bool) -> None:
    value, helper, _ = backend()
    value.create_ownership_if_unowned_and_not_quarantined(
        KEY, b"first", _digest(b"first")
    )
    helper.next = RemoteHelperCode.AMBIGUOUS
    helper.fault_operation = "replace"
    helper.apply_on_ambiguous = applied
    if applied:
        value.replace_ownership(KEY, _digest(b"first"), b"next", _digest(b"next"))
        assert value.inspect_ownership(KEY).payload == b"next"
    else:
        with pytest.raises(AuthorityBlocked):
            value.replace_ownership(KEY, _digest(b"first"), b"next", _digest(b"next"))


@pytest.mark.parametrize(
    ("applied", "expected"),
    [
        (False, MutationDisposition.DEFINITELY_NOT_APPLIED),
        (True, MutationDisposition.APPLIED),
    ],
)
def test_release_ambiguity_twin_is_reconciled(
    applied: bool, expected: MutationDisposition
) -> None:
    value, helper, _ = backend()
    payload = json.dumps({"manifest_digest": "sha256:terminal"}).encode()
    value.create_ownership_if_unowned_and_not_quarantined(
        KEY, payload, _digest(payload)
    )
    helper.next = RemoteHelperCode.AMBIGUOUS
    helper.fault_operation = "remove"
    helper.apply_on_ambiguous = applied
    receipt = value.remove_ownership(KEY, _digest(payload), "sha256:terminal")
    assert receipt.disposition is expected


@pytest.mark.parametrize("applied", [False, True])
def test_quarantine_ambiguity_twin_is_reconciled(applied: bool) -> None:
    value, helper, _ = backend()
    value.create_ownership_if_unowned_and_not_quarantined(
        KEY, b"first", _digest(b"first")
    )
    helper.next = RemoteHelperCode.AMBIGUOUS
    helper.fault_operation = "quarantine"
    helper.apply_on_ambiguous = applied
    if applied:
        value.convert_to_quarantine(
            KEY, _digest(b"first"), b"incident", _digest(b"incident")
        )
        assert value.inspect_quarantine(KEY).payload == b"incident"
    else:
        with pytest.raises(AuthorityConflict):
            value.convert_to_quarantine(
                KEY, _digest(b"first"), b"incident", _digest(b"incident")
            )


@pytest.mark.parametrize("operation", ["create", "replace", "remove", "quarantine"])
def test_marker_symlink_swap_blocks_every_existing_marker_mutation(
    operation: str,
) -> None:
    value, _, sftp = backend()
    payload = json.dumps({"manifest_digest": "sha256:terminal"}).encode()
    ownership = f"/storage/.coreelec-reconciler/devices/{KEY}/ownership"
    if operation != "create":
        value.create_ownership_if_unowned_and_not_quarantined(
            KEY, payload, _digest(payload)
        )
    marker = f"/storage/.coreelec-reconciler/devices/{KEY}/ownership/marker.json"
    if operation == "create":
        sftp.entries[ownership] = Entry(b"/foreign", stat.S_IFLNK | 0o777)
    else:
        sftp.entries[marker] = Entry(b"/foreign", stat.S_IFLNK | 0o777)
    with pytest.raises((AuthorityBlocked, AuthorityConflict)):
        if operation == "create":
            value.create_ownership_if_unowned_and_not_quarantined(
                KEY, payload, _digest(payload)
            )
        elif operation == "replace":
            value.replace_ownership(KEY, _digest(payload), b"next", _digest(b"next"))
        elif operation == "remove":
            value.remove_ownership(KEY, _digest(payload), "sha256:terminal")
        else:
            value.convert_to_quarantine(
                KEY, _digest(payload), b"incident", _digest(b"incident")
            )


def test_fixed_helper_uses_only_repository_script_and_typed_status() -> None:
    from coreelec_reconciler.adapters.paramiko_session import CommandOutcome
    from tests.adapters.scripted import ScriptedCommands

    commands = ScriptedCommands([CommandOutcome(b"", b"", 69)])
    helper = FixedRemoteHelper(commands)
    result = helper.run(
        "create",
        "/storage/.coreelec-reconciler/devices/key/ownership",
        "sha256:" + "0" * 64,
        f"/storage/.coreelec-reconciler/runs/{WORKSPACE_KEY}/stage/payload",
    )
    assert result.code is RemoteHelperCode.UNSUPPORTED
    assert commands.calls[0][0].startswith("/bin/sh -s -- create ")
    assert b"remove-plus-rename" not in commands.calls[0][1]


def test_fixed_helper_validates_marker_before_every_hash_or_removal() -> None:
    from coreelec_reconciler.adapters.paramiko_session import CommandOutcome
    from tests.adapters.scripted import ScriptedCommands

    commands = ScriptedCommands(
        [CommandOutcome(b"", b"", 66), CommandOutcome(b"", b"", 66)]
    )
    helper = FixedRemoteHelper(commands)
    object_path = f"/storage/.coreelec-reconciler/devices/{KEY}/ownership"
    staged = f"/storage/.coreelec-reconciler/runs/{WORKSPACE_KEY}/stage/payload"
    helper.run("remove", object_path, "sha256:" + "0" * 64, staged)
    script = commands.calls[0][1]
    for operation in (b"replace)", b"remove)", b"quarantine)"):
        start = script.index(operation)
        end = script.find(b";;", start)
        section = script[start:end]
        validation = section.index(b'[ ! -L "$object/marker.json" ]')
        hashing = section.index(b'sha256sum "$object/marker.json"')
        assert validation < hashing


def _digest(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()
