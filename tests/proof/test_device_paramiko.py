"""Evidence-only opt-in disposable Device transport proof."""

import contextlib
import os
import shlex
import socket
import stat
import time
import uuid
from pathlib import Path

import pytest

from coreelec_reconciler.transports import ParamikoTransport

pytestmark = pytest.mark.device


def _device_enabled() -> bool:
    return os.environ.get("COREELEC_PROOF_DEVICE") == "1"


@pytest.mark.skipif(not _device_enabled(), reason="disposable Device proof is opt-in")
def test_paramiko_device_contract() -> None:
    host = os.environ.get("COREELEC_PROOF_HOST", "ugoos-theater")
    port = int(os.environ.get("COREELEC_PROOF_PORT", "22"))
    identity = Path(
        os.environ.get(
            "COREELEC_PROOF_IDENTITY",
            str(Path.home() / ".ssh" / "coreelec_admin_ed25519"),
        )
    )
    known_hosts = Path(
        os.environ.get(
            "COREELEC_PROOF_KNOWN_HOSTS", str(Path.home() / ".ssh" / "known_hosts")
        )
    )
    run_id = uuid.uuid4().hex
    directory = f"/storage/.cache/coreelec-reconciler-proof-{run_id}"
    upload_path = f"{directory}/upload.bin"
    renamed_path = f"{directory}/renamed.bin"
    ambiguous_source = f"{directory}/ambiguous-source"
    ambiguous_destination = f"{directory}/ambiguous-destination"
    payload = b"coreelec-reconciler-paramiko-proof\n\x00\xff"
    transport = ParamikoTransport.connect(
        hostname=host,
        port=port,
        username="root",
        identity_file=identity,
        known_hosts_file=known_hosts,
        timeout=12,
    )
    created_paths: list[str] = []
    try:
        status, stdout, stderr = transport.execute(
            "printf coreelec-reconciler-proof", timeout=12
        )
        assert (status, stdout, stderr) == (
            0,
            b"coreelec-reconciler-proof",
            b"",
        )

        transport.sftp.mkdir(directory, mode=0o700)
        transport.upload(payload, upload_path)
        created_paths.append(upload_path)
        assert transport.download(upload_path) == payload
        assert transport.stat(upload_path).size == len(payload)
        assert transport.lstat(upload_path).size == len(payload)
        assert stat.S_ISREG(transport.stat(upload_path).mode)

        transport.rename(upload_path, renamed_path)
        created_paths.remove(upload_path)
        created_paths.append(renamed_path)
        assert transport.download(renamed_path) == payload

        _stdin, stdout_stream, _stderr = transport.client.exec_command("sleep 2")
        stdout_stream.channel.settimeout(0.1)
        with pytest.raises(socket.timeout):
            stdout_stream.channel.recv(1)
        stdout_stream.channel.close()

        with transport.sftp.file(ambiguous_source, "wb") as remote:
            remote.write(b"rename-proof")
        created_paths.append(ambiguous_source)
        command = (
            f"mv {shlex.quote(ambiguous_source)} "
            f"{shlex.quote(ambiguous_destination)}; sleep 10"
        )
        _stdin, ambiguous_stdout, _stderr = transport.client.exec_command(command)
        time.sleep(0.5)
        ambiguous_stdout.channel.close()
        created_paths.remove(ambiguous_source)
        created_paths.append(ambiguous_destination)
        assert transport.lstat(ambiguous_destination).size == len(b"rename-proof")
        with pytest.raises(OSError):
            transport.lstat(ambiguous_source)
    finally:
        for path in reversed(created_paths):
            with contextlib.suppress(OSError):
                transport.sftp.remove(path)
        with contextlib.suppress(OSError):
            transport.sftp.rmdir(directory)
        try:
            transport.sftp.lstat(directory)
        except OSError:
            cleanup_verified = True
        else:
            cleanup_verified = False
        transport.close()
        assert cleanup_verified
