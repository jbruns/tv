"""Construction of the immutable built-in Resource Type registry."""

from collections.abc import Mapping
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
from coreelec_reconciler.resource_types.kodi_smart_playlist.observation_codecs import (
    OBSERVATION_PAYLOAD_KIND,
    OBSERVATION_PAYLOAD_VERSION,
    OBSERVATION_POLICY_DIGEST,
    check_observation_addresses,
    check_observation_run_payload,
    decode_observation_run_payload,
    encode_observation_run_payload,
    validate_observation_addresses,
)
from coreelec_reconciler.resource_types.kodi_smart_playlist.planning_codecs import (
    decode_plan_evidence,
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
                decode_plan_evidence=decode_plan_evidence,
                execution_factory=_playlist_execution,
                encode_prepared=_encode_playlist_prepared,
                decode_prepared=_decode_playlist_prepared,
                decode_planned_change=_decode_playlist_planned_change,
                observation_payload_kind=OBSERVATION_PAYLOAD_KIND,
                observation_payload_version=OBSERVATION_PAYLOAD_VERSION,
                observation_policy_digest=OBSERVATION_POLICY_DIGEST,
                encode_observation_evidence=encode_observation_run_payload,
                decode_observation_evidence=decode_observation_run_payload,
                check_observation_evidence=check_observation_run_payload,
                validate_observation_addresses=validate_observation_addresses,
                check_observation_addresses=check_observation_addresses,
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


def _decode_playlist_planned_change(
    value: Mapping[str, object],
    context: ResourceExecutionContext,
    rollback_approved: bool,
) -> object:
    from coreelec_reconciler.resource_types.kodi_smart_playlist.execution import (
        decode_planned_change,
    )

    return decode_planned_change(value, context, rollback_approved)
