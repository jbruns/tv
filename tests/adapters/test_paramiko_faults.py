from coreelec_reconciler.adapters.paramiko_managed_file import ParamikoManagedFiles
from coreelec_reconciler.domain.execution import MutationDisposition
from coreelec_reconciler.transports.interfaces import ReadFailureCode
from tests.adapters.scripted import (
    Entry,
    ScriptedNoFollowReader,
    ScriptedSFTP,
)


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
    sftp.disconnect_on = "flush"
    receipt = ParamikoManagedFiles(sftp).stage_write(  # type: ignore[arg-type]
        "/storage/stage", b"content", 0o600, "stage"
    )

    assert receipt.disposition is MutationDisposition.AMBIGUOUS
    assert sftp.closed_handles == 1
