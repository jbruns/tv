"""Construction of the immutable built-in Resource Type registry."""

from coreelec_reconciler.resource_types.descriptor import ResourceDescriptor
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
            ),
        )
    )
