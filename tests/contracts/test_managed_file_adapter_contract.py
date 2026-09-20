import hashlib
import json
import stat
from collections.abc import Callable
from functools import partial
from typing import Any, cast

import paramiko
import pytest

from coreelec_reconciler.adapters.managed_mutation_helper import (
    FixedManagedMutationHelper,
)
from coreelec_reconciler.adapters.paramiko_managed_file import ParamikoManagedFiles
from coreelec_reconciler.adapters.paramiko_session import CommandOutcome
from coreelec_reconciler.domain.execution import (
    MutationDisposition,
    NormalizedResourceState,
    Presence,
)
from coreelec_reconciler.transports.interfaces import EntryKind, ReadFailureCode
from tests.adapters.scripted import (
    Entry,
    ScriptedCommands,
    ScriptedManagedMutationHelper,
    ScriptedNoFollowReader,
    ScriptedSFTP,
)
from tests.fakes.runtime import FakeManagedEntry, FakeManagedFiles

PATH = "/storage/file"
BINDING = "sha256:" + "a" * 64
STAGED = f"/storage/.file.{BINDING[7:]}.stage"
NEW_STAGE = f"/storage/.new.{BINDING[7:]}.stage"
ABSENT = NormalizedResourceState(Presence.ABSENT, None, None, None)


def _state(
    content: bytes,
    mode: int = 0o644,
    kind: EntryKind = EntryKind.REGULAR,
) -> NormalizedResourceState:
    return NormalizedResourceState(
        Presence.PRESENT,
        kind.value,
        "sha256:" + hashlib.sha256(content).hexdigest(),
        mode,
    )


def _production() -> tuple[
    ParamikoManagedFiles, ScriptedSFTP, ScriptedManagedMutationHelper
]:
    sftp = ScriptedSFTP()
    helper = ScriptedManagedMutationHelper(sftp)
    adapter = ParamikoManagedFiles(
        cast(paramiko.SFTPClient, sftp),
        ScriptedNoFollowReader(sftp),
        helper,
    )
    return adapter, sftp, helper


def _fake() -> tuple[FakeManagedFiles, FakeManagedFiles]:
    fake = FakeManagedFiles()
    return fake, fake


@pytest.mark.parametrize("adapter_kind", ["fake", "paramiko"])
def test_successful_create_update_mode_remove_restore_and_cleanup(
    adapter_kind: str,
) -> None:
    files: Any
    store: Any
    inspect: Callable[[str], Any]
    if adapter_kind == "fake":
        files, store = _fake()
        inspect = store.entry
    else:
        files, store, _ = _production()
        inspect = store.entries.get

    assert (
        files.stage_write(
            STAGED,
            b"new",
            0o640,
            "stage",
            expected=ABSENT,
            binding_digest=BINDING,
        ).disposition
        is MutationDisposition.APPLIED
    )
    assert (
        files.atomic_replace(
            STAGED,
            PATH,
            "create",
            expected_staged=_state(b"new", 0o640),
            expected_destination=ABSENT,
            binding_digest=BINDING,
        ).disposition
        is MutationDisposition.APPLIED
    )
    assert (
        files.stage_write(
            STAGED,
            b"updated",
            0o640,
            "stage-update",
            expected=ABSENT,
            binding_digest=BINDING,
        ).disposition
        is MutationDisposition.APPLIED
    )
    assert (
        files.atomic_replace(
            STAGED,
            PATH,
            "update",
            expected_staged=_state(b"updated", 0o640),
            expected_destination=_state(b"new", 0o640),
            binding_digest=BINDING,
        ).disposition
        is MutationDisposition.APPLIED
    )
    assert (
        files.chmod(
            PATH,
            0o600,
            "chmod",
            expected=_state(b"updated", 0o640),
            binding_digest=BINDING,
        ).disposition
        is MutationDisposition.APPLIED
    )
    assert (
        files.restore(
            PATH,
            b"old",
            0o644,
            "restore",
            expected=_state(b"updated", 0o600),
            binding_digest=BINDING,
        ).disposition
        is MutationDisposition.APPLIED
    )
    restored = inspect(PATH)
    assert restored is not None
    assert restored.content == b"old"
    assert (
        files.remove(
            PATH,
            "remove",
            expected=_state(b"old"),
            binding_digest=BINDING,
        ).disposition
        is MutationDisposition.APPLIED
    )
    assert (
        files.cleanup(
            STAGED,
            "cleanup",
            expected=ABSENT,
            binding_digest=BINDING,
        ).disposition
        is MutationDisposition.APPLIED
    )
    assert inspect(PATH) is None


@pytest.mark.parametrize("adapter_kind", ["fake", "paramiko"])
def test_run_bound_identical_stage_is_idempotent(adapter_kind: str) -> None:
    files: Any
    store: Any
    if adapter_kind == "fake":
        files, store = _fake()
        store.put(STAGED, FakeManagedEntry(0o600, b"value"))
    else:
        files, store, _ = _production()
        store.entries[STAGED] = Entry(b"value", stat.S_IFREG | 0o600)

    receipt = files.stage_write(
        STAGED,
        b"value",
        0o600,
        "stage",
        expected=ABSENT,
        binding_digest=BINDING,
    )

    assert receipt.disposition is MutationDisposition.APPLIED


def test_incomplete_production_read_is_typed() -> None:
    files, sftp, _ = _production()
    sftp.entries[PATH] = Entry(b"complete")
    reader = cast(ScriptedNoFollowReader, files._no_follow_reader)
    reader.failure = ReadFailureCode.INCOMPLETE
    result = files.read(PATH, 100)
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


@pytest.mark.parametrize("adapter_kind", ["fake", "paramiko"])
@pytest.mark.parametrize(
    ("replacement", "expected"),
    [
        (FakeManagedEntry(0o644, b"third-party"), _state(b"old")),
        (
            FakeManagedEntry(0o644, b"old", EntryKind.SYMLINK),
            _state(b"old"),
        ),
        (FakeManagedEntry(0o644, b"changed"), _state(b"old")),
        (
            FakeManagedEntry(0o644, b"old", EntryKind.DIRECTORY),
            _state(b"old"),
        ),
        (FakeManagedEntry(0o600, b"old"), _state(b"old")),
    ],
    ids=["target-replaced", "final-symlink", "digest", "type", "mode"],
)
def test_changed_preimage_is_never_mutated(
    adapter_kind: str,
    replacement: FakeManagedEntry,
    expected: NormalizedResourceState,
) -> None:
    files: Any
    store: Any
    inspect: Callable[[], Any]
    if adapter_kind == "fake":
        files, store = _fake()
        store.put(PATH, FakeManagedEntry(0o644, b"old"))

        def swap() -> None:
            store.put(PATH, replacement)

        files.before_mutation = swap
        inspect = partial(store.entry, PATH)
    else:
        files, store, helper = _production()
        store.entries[PATH] = Entry(b"old")

        def swap() -> None:
            store.entries[PATH] = Entry(
                replacement.content,
                {
                    EntryKind.REGULAR: stat.S_IFREG,
                    EntryKind.SYMLINK: stat.S_IFLNK,
                    EntryKind.DIRECTORY: stat.S_IFDIR,
                    EntryKind.OTHER: stat.S_IFIFO,
                }[replacement.kind]
                | replacement.mode,
            )

        helper.before_mutation = swap
        inspect = partial(store.entries.get, PATH)

    receipt = files.chmod(
        PATH,
        0o600,
        "chmod",
        expected=expected,
        binding_digest=BINDING,
    )
    assert receipt.disposition is MutationDisposition.DEFINITELY_NOT_APPLIED
    current = inspect()
    assert current is not None
    assert current.content == replacement.content


def test_ancestor_symlink_swap_is_unsafe_and_outside_target_is_unchanged() -> None:
    files, sftp, helper = _production()
    outside = "/outside/file"
    sftp.entries[PATH] = Entry(b"old")
    sftp.entries[outside] = Entry(b"outside")
    helper.unsafe_paths.add(PATH)

    receipt = files.remove(
        PATH,
        "remove",
        expected=_state(b"old"),
        binding_digest=BINDING,
    )

    assert receipt.disposition is MutationDisposition.DEFINITELY_NOT_APPLIED
    assert sftp.entries[outside].content == b"outside"
    assert sftp.entries[PATH].content == b"old"


@pytest.mark.parametrize("adapter_kind", ["fake", "paramiko"])
@pytest.mark.parametrize(
    "primitive",
    ["stage_write", "chmod", "atomic_replace", "remove", "restore", "cleanup"],
)
def test_every_primitive_refuses_a_concurrent_preimage_change(
    adapter_kind: str, primitive: str
) -> None:
    files: Any
    store: Any
    changed_entry: Any
    if adapter_kind == "fake":
        files, store = _fake()
        store.put(PATH, FakeManagedEntry(0o644, b"old"))
        store.put(STAGED, FakeManagedEntry(0o600, b"new"))
        changed_entry = FakeManagedEntry(0o644, b"third-party")
        store.before_mutation = lambda: store.put(
            STAGED if primitive == "stage_write" else PATH, changed_entry
        )
        inspect: Callable[[str], Any] = store.entry
    else:
        files, store, helper = _production()
        store.entries[PATH] = Entry(b"old")
        store.entries[STAGED] = Entry(b"new", stat.S_IFREG | 0o600)
        changed_entry = Entry(b"third-party")
        helper.before_mutation = lambda: store.entries.__setitem__(
            STAGED if primitive == "stage_write" else PATH, changed_entry
        )
        inspect = store.entries.get

    receipt = {
        "stage_write": lambda: files.stage_write(
            STAGED,
            b"ours",
            0o600,
            "stage",
            expected=ABSENT,
            binding_digest=BINDING,
        ),
        "chmod": lambda: files.chmod(
            PATH,
            0o600,
            "chmod",
            expected=_state(b"old"),
            binding_digest=BINDING,
        ),
        "atomic_replace": lambda: files.atomic_replace(
            STAGED,
            PATH,
            "replace",
            expected_staged=_state(b"new", 0o600),
            expected_destination=_state(b"old"),
            binding_digest=BINDING,
        ),
        "remove": lambda: files.remove(
            PATH,
            "remove",
            expected=_state(b"old"),
            binding_digest=BINDING,
        ),
        "restore": lambda: files.restore(
            PATH,
            b"before",
            0o640,
            "restore",
            expected=_state(b"old"),
            binding_digest=BINDING,
        ),
        "cleanup": lambda: files.cleanup(
            PATH,
            "cleanup",
            expected=_state(b"old"),
            binding_digest=BINDING,
        ),
    }[primitive]()

    assert receipt.disposition is MutationDisposition.DEFINITELY_NOT_APPLIED
    changed_path = STAGED if primitive == "stage_write" else PATH
    changed = inspect(changed_path)
    assert changed is not None
    assert changed.content == b"third-party"


@pytest.mark.parametrize("adapter_kind", ["fake", "paramiko"])
def test_substituted_stage_cannot_replace_destination(adapter_kind: str) -> None:
    files: Any
    store: Any
    inspect: Callable[[str], Any]
    if adapter_kind == "fake":
        files, store = _fake()
        store.put(PATH, FakeManagedEntry(0o644, b"old"))
        store.put(STAGED, FakeManagedEntry(0o600, b"expected"))
        store.before_mutation = lambda: store.put(
            STAGED, FakeManagedEntry(0o600, b"third-party")
        )
        inspect = store.entry
    else:
        files, store, helper = _production()
        store.entries[PATH] = Entry(b"old")
        store.entries[STAGED] = Entry(b"expected", stat.S_IFREG | 0o600)
        helper.before_mutation = lambda: store.entries.__setitem__(
            STAGED, Entry(b"third-party", stat.S_IFREG | 0o600)
        )
        inspect = store.entries.get

    receipt = files.atomic_replace(
        STAGED,
        PATH,
        "replace",
        expected_staged=_state(b"expected", 0o600),
        expected_destination=_state(b"old"),
        binding_digest=BINDING,
    )
    assert receipt.disposition is MutationDisposition.DEFINITELY_NOT_APPLIED
    destination = inspect(PATH)
    staged = inspect(STAGED)
    assert destination is not None
    assert staged is not None
    assert destination.content == b"old"
    assert staged.content == b"third-party"


@pytest.mark.parametrize("adapter_kind", ["fake", "paramiko"])
@pytest.mark.parametrize(
    "primitive",
    ["stage_write", "chmod", "atomic_replace", "remove", "restore", "cleanup"],
)
@pytest.mark.parametrize("applied", [False, True])
def test_all_mutation_lost_ack_twins_share_fake_production_contract(
    adapter_kind: str, primitive: str, applied: bool
) -> None:
    files: Any
    store: Any
    if adapter_kind == "fake":
        files, store = _fake()
        store.put(PATH, FakeManagedEntry(0o644, b"old"))
        store.put(STAGED, FakeManagedEntry(0o600, b"new"))
        store.lost_ack(primitive, applied=applied)
        inspect: Callable[[str], Any] = store.entry
    else:
        files, store, helper = _production()
        store.entries[PATH] = Entry(b"old")
        store.entries[STAGED] = Entry(b"new", stat.S_IFREG | 0o600)
        helper.lost_ack_operation = {
            "stage_write": "stage",
            "atomic_replace": "replace",
        }.get(primitive, primitive)
        helper.lost_ack_applied = applied
        inspect = store.entries.get

    receipt = {
        "stage_write": lambda: files.stage_write(
            NEW_STAGE,
            b"value",
            0o600,
            "stage",
            expected=ABSENT,
            binding_digest=BINDING,
        ),
        "chmod": lambda: files.chmod(
            PATH,
            0o600,
            "chmod",
            expected=_state(b"old"),
            binding_digest=BINDING,
        ),
        "atomic_replace": lambda: files.atomic_replace(
            STAGED,
            PATH,
            "replace",
            expected_staged=_state(b"new", 0o600),
            expected_destination=_state(b"old"),
            binding_digest=BINDING,
        ),
        "remove": lambda: files.remove(
            PATH,
            "remove",
            expected=_state(b"old"),
            binding_digest=BINDING,
        ),
        "restore": lambda: files.restore(
            PATH,
            b"before",
            0o640,
            "restore",
            expected=_state(b"old"),
            binding_digest=BINDING,
        ),
        "cleanup": lambda: files.cleanup(
            PATH,
            "cleanup",
            expected=_state(b"old"),
            binding_digest=BINDING,
        ),
    }[primitive]()

    assert receipt.disposition is MutationDisposition.AMBIGUOUS
    if primitive == "stage_write":
        assert (inspect(NEW_STAGE) is not None) is applied
    elif primitive == "chmod":
        assert inspect(PATH).mode & 0o777 == (0o600 if applied else 0o644)
    elif primitive == "atomic_replace":
        assert inspect(PATH).content == (b"new" if applied else b"old")
        assert (inspect(STAGED) is None) is applied
    elif primitive in {"remove", "cleanup"}:
        assert (inspect(PATH) is None) is applied
    else:
        assert inspect(PATH).content == (b"before" if applied else b"old")


def test_production_mutations_have_no_direct_sftp_bypass() -> None:
    files, sftp, _ = _production()
    sftp.entries[PATH] = Entry(b"old")
    sftp.entries[STAGED] = Entry(b"new", stat.S_IFREG | 0o600)

    files.atomic_replace(
        STAGED,
        PATH,
        "replace",
        expected_staged=_state(b"new", 0o600),
        expected_destination=_state(b"old"),
        binding_digest=BINDING,
    )
    files.chmod(
        PATH,
        0o640,
        "chmod",
        expected=_state(b"new", 0o600),
        binding_digest=BINDING,
    )
    files.remove(
        PATH,
        "remove",
        expected=_state(b"new", 0o640),
        binding_digest=BINDING,
    )

    assert sftp.posix_calls == []
    assert sftp.rename_calls == []
    assert sftp.remove_calls == []
    assert sftp.closed_handles == 0


def test_fixed_helper_passes_paths_and_content_only_in_encoded_stdin() -> None:
    commands = ScriptedCommands([CommandOutcome(b"", b"", 0)])
    helper = FixedManagedMutationHelper(commands)
    dangerous_path = "/storage/a;touch injected/$(command)/file"
    dangerous_content = b"$(command);`other`\x00value"

    result = helper.mutate(
        "stage",
        dangerous_path,
        "change;$(id)",
        BINDING,
        ABSENT,
        content=dangerous_content,
        mode=0o600,
    )

    assert result.code.value == "applied"
    command, stdin, _ = commands.calls[0]
    assert dangerous_path not in command
    assert dangerous_content not in command.encode()
    request = json.loads(stdin)
    assert request["path"] == dangerous_path
    assert request["content"] != dangerous_content.decode(errors="ignore")
