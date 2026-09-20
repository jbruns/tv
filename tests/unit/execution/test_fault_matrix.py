import pytest

from coreelec_reconciler.domain.execution import (
    MutationDisposition,
    NormalizedResourceState,
    Presence,
)
from coreelec_reconciler.execution.managed_file import ManagedFileExecutor
from tests.fakes.run_infrastructure import FakeAttachments
from tests.fakes.runtime import FakeManagedEntry, FakeManagedFiles
from tests.unit.execution.test_managed_file_lifecycle import (
    PATH,
    _marker,
    _prepared,
    _state,
)


@pytest.mark.parametrize(
    "primitive",
    ["stage_write", "atomic_replace", "chmod", "remove", "restore", "cleanup"],
)
@pytest.mark.parametrize(
    ("disposition", "applied"),
    [
        (MutationDisposition.DEFINITELY_NOT_APPLIED, False),
        (MutationDisposition.AMBIGUOUS, False),
        (MutationDisposition.AMBIGUOUS, True),
    ],
)
def test_every_primitive_fault_is_observed_through_lifecycle(
    primitive: str,
    disposition: MutationDisposition,
    applied: bool,
) -> None:
    device = FakeManagedFiles()
    attachments = FakeAttachments()
    before_content: bytes | None = b"before"
    desired_content: bytes | None = b"desired"
    before_mode = 0o644
    desired_mode = 0o644
    if primitive in {"stage_write", "atomic_replace"}:
        if primitive == "stage_write":
            before_content = None
        _inject(device, primitive, disposition, applied)
    elif primitive == "chmod":
        desired_content = before_content
        desired_mode = 0o600
        _inject(device, primitive, disposition, applied)
    elif primitive == "remove":
        desired_content = None
        desired_mode = 0
        _inject(device, primitive, disposition, applied)
    if before_content is not None:
        device.put(PATH, FakeManagedEntry(before_mode, before_content))
    before = (
        _state(before_content, before_mode) if before_content is not None else _absent()
    )
    desired = (
        _state(desired_content, desired_mode)
        if desired_content is not None
        else _absent()
    )
    prepared = _prepared(attachments, before, desired, before_content, desired_content)
    executor = ManagedFileExecutor(device, attachments, lambda intent: None, _marker)

    if primitive == "restore":
        device.put(PATH, FakeManagedEntry(desired_mode, desired_content or b""))
        _inject(device, "restore", disposition, applied)
        trace, verification = executor.rollback(
            prepared,
            resource_id="skin.playlist.new-shows",
            change_id="change-1",
        )
        assert trace is not None
        receipt = trace.receipts[-1]
        assert (verification.observation.state == before) is applied
    elif primitive == "cleanup":
        stage_path = (
            "/storage/.kodi/userdata/playlists/video/"
            f".NewShows.xsp.stage-change.{'b' * 64}.stage"
        )
        device.put(stage_path, FakeManagedEntry(0o600, b"stage"))
        _inject(device, "cleanup", disposition, applied)
        trace = executor.cleanup(
            prepared,
            resource_id="skin.playlist.new-shows",
            change_id="change-1",
            terminal_evidence_ref="sha256:" + "e" * 64,
        )
        receipt = trace.receipts[-1]
        assert (device.entry(stage_path) is None) is applied
    else:
        result = executor.apply(
            prepared,
            resource_id="skin.playlist.new-shows",
            change_id="change-1",
            rollback_approved=True,
        )
        receipt = next(
            item
            for item in result.mutation.receipts
            if item.operation_id.endswith(primitive)
        )
        if primitive in {"stage_write", "atomic_replace"}:
            assert (
                device.entry(PATH) == FakeManagedEntry(0o644, b"desired")
            ) is applied
        elif primitive == "chmod":
            assert (device.entry(PATH) == FakeManagedEntry(0o600, b"before")) is applied
        else:
            assert (device.entry(PATH) is None) is applied
    assert receipt.disposition is disposition


def _absent() -> NormalizedResourceState:
    return NormalizedResourceState(Presence.ABSENT, None, None, None)


def _inject(
    device: FakeManagedFiles,
    primitive: str,
    disposition: MutationDisposition,
    applied: bool,
) -> None:
    if disposition is MutationDisposition.AMBIGUOUS:
        device.lost_ack(primitive, applied=applied)
    else:
        device.fault(primitive, disposition)
