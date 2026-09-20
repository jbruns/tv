"""Construction of the immutable built-in Resource Type registry."""

from typing import cast

from coreelec_reconciler.resource_types.descriptor import (
    ErasedResourceExecution,
    ResourceDescriptor,
    ResourceExecutionContext,
)
from coreelec_reconciler.resource_types.kodi_smart_playlist.codecs import (
    decode_intent,
    encode_intent,
)
from coreelec_reconciler.resource_types.kodi_smart_playlist.intent import (
    parse_intent,
)
from coreelec_reconciler.resource_types.kodi_smart_playlist.resource_type import (
    state_addresses,
)
from coreelec_reconciler.resource_types.registry import ResourceRegistry


def built_in_resource_registry() -> ResourceRegistry:
    return ResourceRegistry.create(
        (
            ResourceDescriptor(
                type_code="KodiSmartPlaylist",
                parse_intent=parse_intent,
                state_addresses=state_addresses,
                encode_intent=encode_intent,
                decode_intent=decode_intent,
                execution_factory=_playlist_execution,
                encode_prepared=_encode_playlist_prepared,
                decode_prepared=_decode_playlist_prepared,
            ),
        )
    )


def _playlist_execution(
    context: ResourceExecutionContext,
) -> ErasedResourceExecution:
    from coreelec_reconciler.resource_types.kodi_smart_playlist.execution import (
        execution_factory,
    )

    return execution_factory(context)


def _encode_playlist_prepared(value: object) -> bytes:
    from coreelec_reconciler.resource_types.kodi_smart_playlist.execution import (
        encode_erased_prepared,
    )

    return encode_erased_prepared(value)


def _decode_playlist_prepared(
    content: bytes,
    attachments: object,
) -> object:
    from coreelec_reconciler.resource_types.descriptor import AttachmentStore
    from coreelec_reconciler.resource_types.kodi_smart_playlist.execution import (
        decode_erased_prepared,
    )

    return decode_erased_prepared(content, cast(AttachmentStore, attachments))
