"""Public-seam attachment fake with corruption injection."""

import hashlib

from coreelec_reconciler.domain.execution import AttachmentRef


class FakeAttachments:
    def __init__(self) -> None:
        self._payloads: dict[str, bytes] = {}

    def attach(self, kind: str, codec: str, payload: bytes) -> AttachmentRef:
        digest = "sha256:" + hashlib.sha256(payload).hexdigest()
        self._payloads[digest] = payload
        return AttachmentRef(digest, kind, codec)

    def read_attachment(self, reference: AttachmentRef) -> bytes:
        payload = self._payloads[reference.digest]
        if "sha256:" + hashlib.sha256(payload).hexdigest() != reference.digest:
            raise ValueError("attachment corruption")
        return payload

    def corrupt(self, reference: AttachmentRef) -> None:
        self._payloads[reference.digest] += b"corrupt"
