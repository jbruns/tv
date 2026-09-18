"""Evidence-only repository-owned synchronous transport protocols and adapter."""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Self

import paramiko


@dataclass(frozen=True, slots=True)
class RemoteMetadata:
    size: int
    mode: int


class CommandTransport(Protocol):
    def execute(self, command: str, *, timeout: float) -> tuple[int, bytes, bytes]: ...


class FileTransport(Protocol):
    def upload(self, content: bytes, remote_path: str) -> None: ...

    def download(self, remote_path: str) -> bytes: ...

    def lstat(self, remote_path: str) -> RemoteMetadata: ...

    def stat(self, remote_path: str) -> RemoteMetadata: ...

    def rename(self, source: str, destination: str) -> None: ...


class ParamikoTransport:
    def __init__(self, client: paramiko.SSHClient, sftp: paramiko.SFTPClient) -> None:
        self._client = client
        self._sftp = sftp

    @classmethod
    def connect(
        cls,
        *,
        hostname: str,
        port: int,
        username: str,
        identity_file: Path,
        known_hosts_file: Path,
        timeout: float,
    ) -> Self:
        client = paramiko.SSHClient()
        client.load_host_keys(str(known_hosts_file))
        client.set_missing_host_key_policy(paramiko.RejectPolicy())
        client.connect(
            hostname=hostname,
            port=port,
            username=username,
            key_filename=str(identity_file),
            look_for_keys=False,
            allow_agent=False,
            timeout=timeout,
            banner_timeout=timeout,
            auth_timeout=timeout,
        )
        return cls(client, client.open_sftp())

    def execute(self, command: str, *, timeout: float) -> tuple[int, bytes, bytes]:
        _stdin, stdout, stderr = self._client.exec_command(command, timeout=timeout)
        channel = stdout.channel
        channel.settimeout(timeout)
        try:
            standard_output = stdout.read()
            standard_error = stderr.read()
            status = channel.recv_exit_status()
            return status, standard_output, standard_error
        finally:
            channel.close()

    def upload(self, content: bytes, remote_path: str) -> None:
        with self._sftp.file(remote_path, "wb") as remote:
            remote.write(content)

    def download(self, remote_path: str) -> bytes:
        with self._sftp.file(remote_path, "rb") as remote:
            return bytes(remote.read())

    @staticmethod
    def _metadata(attributes: paramiko.SFTPAttributes) -> RemoteMetadata:
        if attributes.st_size is None or attributes.st_mode is None:
            raise ValueError("remote metadata was incomplete")
        return RemoteMetadata(size=attributes.st_size, mode=attributes.st_mode)

    def lstat(self, remote_path: str) -> RemoteMetadata:
        return self._metadata(self._sftp.lstat(remote_path))

    def stat(self, remote_path: str) -> RemoteMetadata:
        return self._metadata(self._sftp.stat(remote_path))

    def rename(self, source: str, destination: str) -> None:
        self._sftp.rename(source, destination)

    @property
    def client(self) -> paramiko.SSHClient:
        return self._client

    @property
    def sftp(self) -> paramiko.SFTPClient:
        return self._sftp

    def close(self) -> None:
        self._sftp.close()
        self._client.close()
