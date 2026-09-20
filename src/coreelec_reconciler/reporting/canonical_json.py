"""Compatibility exports for canonical JSON presentation callers."""

from coreelec_reconciler.domain.canonical_json import (
    canonical_document_bytes,
    decode_json_object,
)

__all__ = ["canonical_document_bytes", "decode_json_object"]
