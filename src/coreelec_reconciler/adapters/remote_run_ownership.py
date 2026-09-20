"""Paramiko backend for durable remote ownership and exact cleanup."""

import hashlib
import json
import posixpath

from coreelec_reconciler.domain.execution import (
    MutationDisposition,
    MutationReceipt,
)
from coreelec_reconciler.execution.authority import (
    AuthorityBlocked,
    AuthorityConflict,
    RemoteAuthorityBackend,
    RemoteObject,
    RemoteObjectKind,
)
from coreelec_reconciler.transports.interfaces import EntryKind, FileMetadata

from .paramiko_managed_file import ParamikoManagedFiles
from .remote_helpers import (
    REMOTE_ROOT,
    RemoteHelper,
    RemoteHelperCode,
    staged_infrastructure_path,
)


class ParamikoRemoteAuthorityBackend(RemoteAuthorityBackend):
    def __init__(
        self,
        files: ParamikoManagedFiles,
        helper: RemoteHelper,
        *,
        workspace_key: str,
    ) -> None:
        _validate_key(workspace_key)
        self._files = files
        self._helper = helper
        self._workspace_key = workspace_key
        self._created_manifest_paths: list[str] = []

    def inspect_ownership(self, device_key: str) -> RemoteObject:
        return self._inspect_container(
            self._ownership_path(device_key), self._marker_path(device_key)
        )

    def inspect_quarantine(self, device_key: str) -> RemoteObject:
        receipt = self._quarantine_path(device_key)
        return self._inspect_container(posixpath.dirname(receipt), receipt)

    def create_ownership_if_unowned_and_not_quarantined(
        self, device_key: str, payload: bytes, expected_digest: str
    ) -> None:
        if self.inspect_quarantine(device_key).kind is not RemoteObjectKind.ABSENT:
            raise AuthorityConflict("remote quarantine blocks acquisition")
        object_path = self._ownership_path(device_key)
        staged = self._stage(payload, expected_digest)
        self._reconcile_marker_write(
            self._helper.run("create", object_path, expected_digest, staged).code,
            self._marker_path(device_key),
            expected_digest,
        )
        self._verify(self._marker_path(device_key), expected_digest)

    def replace_ownership(
        self,
        device_key: str,
        expected_digest: str,
        payload: bytes,
        next_digest: str,
    ) -> None:
        object_path = self._ownership_path(device_key)
        staged = self._stage(payload, next_digest)
        self._reconcile_marker_write(
            self._helper.run("replace", object_path, expected_digest, staged).code,
            self._marker_path(device_key),
            next_digest,
        )
        self._verify(self._marker_path(device_key), next_digest)

    def remove_ownership(
        self,
        device_key: str,
        expected_digest: str,
        terminal_receipt_digest: str,
    ) -> MutationReceipt:
        marker = self.inspect_ownership(device_key)
        if marker.payload is None or _digest(marker.payload) != expected_digest:
            raise AuthorityConflict("ownership compare failed")
        try:
            value = json.loads(marker.payload)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise AuthorityConflict("ownership marker is malformed") from error
        if value.get("manifest_digest") != terminal_receipt_digest:
            raise AuthorityConflict("terminal evidence compare failed")
        code = self._helper.run(
            "remove",
            self._ownership_path(device_key),
            expected_digest,
            self._marker_path(device_key),
        ).code
        if code in {RemoteHelperCode.APPLIED, RemoteHelperCode.AMBIGUOUS}:
            observed = self.inspect_ownership(device_key)
            if observed.kind is RemoteObjectKind.ABSENT:
                return MutationReceipt(
                    "remote-ownership-release", MutationDisposition.APPLIED
                )
            if (
                observed.payload is not None
                and _digest(observed.payload) == expected_digest
            ):
                return MutationReceipt(
                    "remote-ownership-release",
                    MutationDisposition.DEFINITELY_NOT_APPLIED,
                )
            return MutationReceipt(
                "remote-ownership-release", MutationDisposition.AMBIGUOUS
            )
        if code in {RemoteHelperCode.CONFLICT, RemoteHelperCode.FAILED}:
            return MutationReceipt(
                "remote-ownership-release",
                MutationDisposition.DEFINITELY_NOT_APPLIED,
            )
        return MutationReceipt(
            "remote-ownership-release", MutationDisposition.AMBIGUOUS
        )

    def convert_to_quarantine(
        self,
        device_key: str,
        expected_digest: str,
        payload: bytes,
        next_digest: str,
    ) -> None:
        object_path = self._ownership_path(device_key)
        staged = self._stage(payload, next_digest)
        code = self._helper.run("quarantine", object_path, expected_digest, staged).code
        if code is RemoteHelperCode.AMBIGUOUS:
            quarantine = self.inspect_quarantine(device_key)
            ownership = self.inspect_ownership(device_key)
            if (
                quarantine.payload is not None
                and _digest(quarantine.payload) == next_digest
                and ownership.kind is RemoteObjectKind.ABSENT
            ):
                code = RemoteHelperCode.APPLIED
            elif (
                ownership.payload is not None
                and _digest(ownership.payload) == expected_digest
            ):
                code = RemoteHelperCode.CONFLICT
        self._require(code)
        self._verify(self._quarantine_path(device_key), next_digest)
        if self.inspect_ownership(device_key).kind is not RemoteObjectKind.ABSENT:
            raise AuthorityBlocked("remote quarantine conversion was not proven")

    def cleanup_manifest_paths(
        self, paths: tuple[str, ...], operation_id: str
    ) -> tuple[MutationReceipt, ...]:
        receipts = []
        for index, path in enumerate(paths):
            run_root = posixpath.join(REMOTE_ROOT, "runs", self._workspace_key)
            if not path.startswith(run_root + "/"):
                raise ValueError("cleanup path is outside the Run manifest root")
            code = self._helper.run("cleanup", path, "-", path).code
            if code is RemoteHelperCode.AMBIGUOUS:
                inspected = self._helper.run("inspect_cleanup", path, "-", path).code
                code = (
                    inspected
                    if inspected
                    in {RemoteHelperCode.APPLIED, RemoteHelperCode.CONFLICT}
                    else RemoteHelperCode.AMBIGUOUS
                )
            disposition = {
                RemoteHelperCode.APPLIED: MutationDisposition.APPLIED,
                RemoteHelperCode.CONFLICT: (MutationDisposition.DEFINITELY_NOT_APPLIED),
                RemoteHelperCode.FAILED: MutationDisposition.DEFINITELY_NOT_APPLIED,
                RemoteHelperCode.UNSAFE: MutationDisposition.AMBIGUOUS,
                RemoteHelperCode.UNSUPPORTED: MutationDisposition.AMBIGUOUS,
                RemoteHelperCode.AMBIGUOUS: MutationDisposition.AMBIGUOUS,
            }[code]
            receipts.append(MutationReceipt(f"{operation_id}.{index}", disposition))
        return tuple(receipts)

    def cleanup_created_objects(self, operation_id: str) -> tuple[MutationReceipt, ...]:
        return self.cleanup_manifest_paths(
            tuple(self._created_manifest_paths), operation_id
        )

    def _inspect(self, path: str) -> RemoteObject:
        metadata = self._files.lstat(path)
        if metadata.failure is not None:
            if metadata.failure.code.value == "not_found":
                return RemoteObject(RemoteObjectKind.ABSENT)
            return RemoteObject(RemoteObjectKind.UNKNOWN)
        assert isinstance(metadata.value, FileMetadata)
        if metadata.value.kind is not EntryKind.REGULAR:
            return RemoteObject(
                {
                    EntryKind.DIRECTORY: RemoteObjectKind.DIRECTORY,
                    EntryKind.SYMLINK: RemoteObjectKind.SYMLINK,
                }.get(metadata.value.kind, RemoteObjectKind.OTHER)
            )
        read = self._files.read(path, 65_536)
        if not isinstance(read.value, bytes):
            return RemoteObject(RemoteObjectKind.UNKNOWN)
        return RemoteObject(RemoteObjectKind.REGULAR, read.value)

    def _inspect_container(self, directory: str, leaf: str) -> RemoteObject:
        container = self._files.lstat(directory)
        if container.failure is not None:
            if container.failure.code.value == "not_found":
                return RemoteObject(RemoteObjectKind.ABSENT)
            return RemoteObject(RemoteObjectKind.UNKNOWN)
        if (
            not isinstance(container.value, FileMetadata)
            or container.value.kind is not EntryKind.DIRECTORY
        ):
            return RemoteObject(RemoteObjectKind.UNKNOWN)
        value = self._inspect(leaf)
        if value.kind is RemoteObjectKind.ABSENT:
            return RemoteObject(RemoteObjectKind.UNKNOWN)
        return value

    def _stage(self, payload: bytes, digest: str) -> str:
        path = staged_infrastructure_path(self._workspace_key, payload)
        if path not in self._created_manifest_paths:
            self._created_manifest_paths.append(path)
        self._require(self._helper.run("prepare", path, digest, path).code)
        receipt = self._files.stage_write(path, payload, 0o600, "remote-stage")
        if receipt.disposition is MutationDisposition.DEFINITELY_NOT_APPLIED:
            existing = self._inspect(path)
            if existing.payload is not None and _digest(existing.payload) == digest:
                return path
        if receipt.disposition is not MutationDisposition.APPLIED:
            raise AuthorityBlocked("remote durability staging failed")
        self._verify(path, digest)
        return path

    def _verify(self, path: str, expected_digest: str) -> None:
        value = self._inspect(path)
        if value.payload is None or _digest(value.payload) != expected_digest:
            raise AuthorityBlocked("remote durability reread failed")

    @staticmethod
    def _require(code: RemoteHelperCode) -> None:
        if code is RemoteHelperCode.CONFLICT:
            raise AuthorityConflict("remote ownership compare failed")
        if code is RemoteHelperCode.UNSAFE:
            raise AuthorityBlocked("remote Run Infrastructure is unsafe")
        if code is not RemoteHelperCode.APPLIED:
            raise AuthorityBlocked("remote ownership durability was not proven")

    def _reconcile_marker_write(
        self, code: RemoteHelperCode, marker_path: str, next_digest: str
    ) -> None:
        if code is RemoteHelperCode.AMBIGUOUS:
            observed = self._inspect(marker_path)
            if (
                observed.payload is not None
                and _digest(observed.payload) == next_digest
            ):
                code = RemoteHelperCode.APPLIED
            elif observed.kind is RemoteObjectKind.ABSENT:
                code = RemoteHelperCode.CONFLICT
        self._require(code)

    @staticmethod
    def _ownership_path(device_key: str) -> str:
        _validate_key(device_key)
        return posixpath.join(REMOTE_ROOT, "devices", device_key, "ownership")

    @classmethod
    def _marker_path(cls, device_key: str) -> str:
        return posixpath.join(cls._ownership_path(device_key), "marker.json")

    @staticmethod
    def _quarantine_path(device_key: str) -> str:
        _validate_key(device_key)
        return posixpath.join(
            REMOTE_ROOT, "devices", device_key, "quarantine", "receipt.json"
        )


def _validate_key(value: str) -> None:
    if len(value) != 64 or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise ValueError("opaque Device key is invalid")


def _digest(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()
