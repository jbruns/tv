from coreelec_reconciler.adapters.paramiko_managed_file import ParamikoManagedFiles
from coreelec_reconciler.domain.execution import (
    MutationDisposition,
    NormalizedResourceState,
    Presence,
)
from coreelec_reconciler.transports.interfaces import ReadFailureCode
from tests.adapters.scripted import (
    Entry,
    ScriptedManagedMutationHelper,
    ScriptedNoFollowReader,
    ScriptedSFTP,
)

ABSENT = NormalizedResourceState(Presence.ABSENT, None, None, None)
BINDING = "sha256:" + "a" * 64


def test_read_disconnect_is_typed_without_transport_detail() -> None:
    sftp = ScriptedSFTP()
    sftp.entries["/storage/file"] = Entry(b"content")
    reader = ScriptedNoFollowReader(sftp)
    reader.failure = ReadFailureCode.TRANSPORT
    result = ParamikoManagedFiles(sftp, reader).read(  # type: ignore[arg-type]
        "/storage/file", 100
    )

    assert result.failure is not None
    assert result.failure.code is ReadFailureCode.TRANSPORT
    assert "credential" not in result.failure.safe_message
    assert "private" not in result.failure.safe_message


def test_stage_disconnect_closes_handle_and_reports_ambiguity() -> None:
    sftp = ScriptedSFTP()
    helper = ScriptedManagedMutationHelper(sftp)
    helper.lost_ack_operation = "stage"
    helper.lost_ack_applied = True
    receipt = ParamikoManagedFiles(
        sftp,  # type: ignore[arg-type]
        mutation_helper=helper,
    ).stage_write(
        f"/storage/.stage.{BINDING[7:]}.stage",
        b"content",
        0o600,
        "stage",
        expected=ABSENT,
        binding_digest=BINDING,
    )

    assert receipt.disposition is MutationDisposition.AMBIGUOUS
    assert sftp.closed_handles == 0
