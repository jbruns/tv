"""Typed Kodi Smart Playlist execution kept inside the Resource Type."""

import base64
import hashlib
from collections.abc import Callable
from dataclasses import dataclass

from coreelec_reconciler.domain.configuration import (
    DesiredPresence,
    KodiSmartPlaylistIntent,
    ManagementMode,
)
from coreelec_reconciler.domain.execution import (
    MutationTrace,
    NormalizedResourceState,
    Presence,
)
from coreelec_reconciler.domain.planning import (
    FileKind,
    KodiSmartPlaylistObservation,
    PlaylistAssessment,
)
from coreelec_reconciler.reporting.canonical_json import (
    canonical_document_bytes,
    decode_json_object,
)
from coreelec_reconciler.resource_types.descriptor import (
    AttachmentStore,
    ErasedResourceExecution,
    ErasedResourceExecutionAdapter,
    ManagedFileCapabilities,
    ManagedFileExecutionResult,
    ManagedFileLifecycle,
    ResourceExecutionContext,
)
from coreelec_reconciler.resource_types.kodi_smart_playlist.codecs import (
    decode_intent,
    encode_intent,
)
from coreelec_reconciler.resource_types.kodi_smart_playlist.planning import (
    assess_playlist,
    desired_model,
)
from coreelec_reconciler.resource_types.kodi_smart_playlist.xml import (
    render_playlist_xml,
)
from coreelec_reconciler.resource_types.managed_file.observation import (
    ManagedFileObservation,
    observe_managed_file,
)
from coreelec_reconciler.resource_types.managed_file.paths import (
    ResolvedManagedAddress,
)
from coreelec_reconciler.resource_types.managed_file.preparation import (
    PreparationBinding,
    PreparationError,
    PreparationObject,
    PreparedManagedFile,
    decode_prepared_managed_file,
    prepare_managed_file,
)


@dataclass(frozen=True, slots=True)
class PlaylistChange:
    resource_id: str
    change_id: str
    intent: KodiSmartPlaylistIntent
    desired_presence: DesiredPresence
    expected_before: NormalizedResourceState
    rollback_approved: bool


@dataclass(frozen=True, slots=True)
class PreparedPlaylistChange:
    change: PlaylistChange
    managed_file: PreparedManagedFile


def execution_factory(context: ResourceExecutionContext) -> ErasedResourceExecution:
    resource = context.resource
    if not isinstance(resource.intent, KodiSmartPlaylistIntent):
        raise TypeError("KodiSmartPlaylist execution requires playlist Intent")
    runtime = KodiSmartPlaylistExecution(
        context.files,
        context.attachments,
        context.lifecycle,
        context.address,
        context.binding,
        resource.intent,
        resource.desired,
        context.observed_at,
    )
    return ErasedResourceExecutionAdapter(
        ManagedFileObservation,
        PlaylistChange,
        PreparedPlaylistChange,
        runtime.observe,
        runtime.assess,
        runtime.prepare,
        runtime.apply,
        runtime.rollback,
        runtime.cleanup,
    )


def encode_prepared_playlist_change(prepared: PreparedPlaylistChange) -> bytes:
    """Encode restart-safe typed preparation without controller-local state."""
    return canonical_document_bytes(
        {
            "change": {
                "change_id": prepared.change.change_id,
                "desired_presence": prepared.change.desired_presence.value,
                "intent": dict(encode_intent(prepared.change.intent)),
                "resource_id": prepared.change.resource_id,
                "rollback_approved": prepared.change.rollback_approved,
            },
            "kind": "KodiSmartPlaylistPreparation",
            "managed_file_manifest_base64": base64.b64encode(
                prepared.managed_file.manifest_bytes
            ).decode("ascii"),
            "managed_file_manifest_digest": prepared.managed_file.manifest_digest,
            "schema_version": 1,
        }
    )


def decode_prepared_playlist_change(
    content: bytes,
    attachments: AttachmentStore,
) -> PreparedPlaylistChange:
    try:
        value = decode_json_object(content)
        if set(value) != {
            "change",
            "kind",
            "managed_file_manifest_base64",
            "managed_file_manifest_digest",
            "schema_version",
        }:
            raise ValueError("unknown or missing playlist preparation fields")
        if (
            value["kind"] != "KodiSmartPlaylistPreparation"
            or value["schema_version"] != 1
        ):
            raise ValueError("unsupported playlist preparation")
        encoded_manifest = value["managed_file_manifest_base64"]
        if not isinstance(encoded_manifest, str):
            raise ValueError("managed-file manifest must be base64 text")
        manifest = base64.b64decode(encoded_manifest, validate=True)
        digest = "sha256:" + hashlib.sha256(manifest).hexdigest()
        if digest != value["managed_file_manifest_digest"]:
            raise ValueError("managed-file manifest digest mismatch")
        managed = decode_prepared_managed_file(manifest, attachments)
        change_value = value["change"]
        if not isinstance(change_value, dict) or set(change_value) != {
            "change_id",
            "desired_presence",
            "intent",
            "resource_id",
            "rollback_approved",
        }:
            raise ValueError("playlist Change is malformed")
        intent_value = change_value["intent"]
        if not isinstance(intent_value, dict):
            raise ValueError("playlist Intent is malformed")
        rollback = change_value["rollback_approved"]
        if type(rollback) is not bool:
            raise ValueError("rollback approval must be boolean")
        change = PlaylistChange(
            _required_text(change_value["resource_id"]),
            _required_text(change_value["change_id"]),
            decode_intent(intent_value),
            DesiredPresence(_required_text(change_value["desired_presence"])),
            managed.before,
            rollback,
        )
        manifest_value = decode_json_object(manifest)
        if (
            manifest_value.get("resource_id") != change.resource_id
            or manifest_value.get("change_id") != change.change_id
        ):
            raise ValueError("playlist Change does not bind to managed-file evidence")
        return PreparedPlaylistChange(change, managed)
    except (KeyError, TypeError, ValueError) as error:
        raise PreparationError("playlist preparation evidence is invalid") from error


def encode_erased_prepared(value: object) -> bytes:
    if not isinstance(value, PreparedPlaylistChange):
        raise TypeError("prepared Resource type does not match descriptor")
    return encode_prepared_playlist_change(value)


def decode_erased_prepared(
    content: bytes,
    attachments: AttachmentStore,
) -> object:
    return decode_prepared_playlist_change(content, attachments)


def desired_state(
    intent: KodiSmartPlaylistIntent, presence: DesiredPresence
) -> tuple[NormalizedResourceState, bytes | None]:
    if presence is DesiredPresence.ABSENT:
        return NormalizedResourceState(Presence.ABSENT, None, None, None), None
    content = render_playlist_xml(desired_model(intent))
    return (
        NormalizedResourceState(
            Presence.PRESENT,
            "regular",
            "sha256:" + hashlib.sha256(content).hexdigest(),
            int(intent.file_mode or "0644", 8),
        ),
        content,
    )


def planning_observation(
    resource_id: str,
    observed_at: str,
    observation: ManagedFileObservation,
) -> KodiSmartPlaylistObservation:
    if observation.state.presence is Presence.ABSENT:
        kind = FileKind.ABSENT
    elif observation.state.entry_kind == "regular":
        kind = FileKind.REGULAR
    else:
        try:
            kind = FileKind(observation.state.entry_kind or "other")
        except ValueError:
            kind = FileKind.OTHER
    return KodiSmartPlaylistObservation(
        resource_id,
        observation.address.logical_address,
        observed_at,
        kind,
        (
            f"{observation.state.managed_mode:04o}"
            if observation.state.managed_mode is not None
            else None
        ),
        observation.content,
    )


def assess(
    change: PlaylistChange,
    observed_at: str,
    observation: ManagedFileObservation,
) -> PlaylistAssessment:
    return assess_playlist(
        change.intent,
        change.desired_presence,
        ManagementMode.ENFORCE,
        planning_observation(change.resource_id, observed_at, observation),
    )


class KodiSmartPlaylistExecution:
    def __init__(
        self,
        files: ManagedFileCapabilities,
        attachments: AttachmentStore,
        lifecycle: ManagedFileLifecycle,
        address: ResolvedManagedAddress,
        binding: PreparationBinding,
        intent: KodiSmartPlaylistIntent,
        desired_presence: DesiredPresence,
        observed_at: Callable[[], str],
        *,
        read_limit: int = 1_048_576,
    ) -> None:
        self._files = files
        self._attachments = attachments
        self._lifecycle = lifecycle
        self._address = address
        self._binding = binding
        self._intent = intent
        self._desired_presence = desired_presence
        self._observed_at = observed_at
        self._read_limit = read_limit

    def observe(self) -> ManagedFileObservation:
        return observe_managed_file(
            self._files, self._address, read_limit=self._read_limit
        )

    def assess(self, observation: ManagedFileObservation) -> PlaylistAssessment:
        return assess(
            PlaylistChange(
                self._binding.resource_id,
                self._binding.change_id,
                self._intent,
                self._desired_presence,
                observation.state,
                False,
            ),
            self._observed_at(),
            observation,
        )

    def prepare(self, change: PlaylistChange) -> PreparedPlaylistChange:
        desired, content = desired_state(change.intent, change.desired_presence)
        prepared = prepare_managed_file(
            reader=self._files,
            attachments=self._attachments,
            address=self._address,
            binding=self._binding,
            expected_before=change.expected_before,
            desired=desired,
            desired_content=content,
            allowed_intermediates=_intermediates(change.expected_before, desired),
            staged_object=PreparationObject(
                "stage-" + change.change_id,
                desired.content_digest or "sha256:absent",
            ),
            cleanup_object=PreparationObject(
                "cleanup-" + change.change_id,
                "sha256:" + hashlib.sha256(b"cleanup").hexdigest(),
            ),
            read_limit=self._read_limit,
        )
        return PreparedPlaylistChange(change, prepared)

    def apply(self, prepared: PreparedPlaylistChange) -> ManagedFileExecutionResult:
        return self._lifecycle.apply(
            prepared.managed_file,
            resource_id=prepared.change.resource_id,
            change_id=prepared.change.change_id,
            rollback_approved=prepared.change.rollback_approved,
            verify=lambda observation: _assessment_match(self.assess(observation)),
        )

    def rollback(self, prepared: PreparedPlaylistChange) -> object:
        return self._lifecycle.rollback(
            prepared.managed_file,
            resource_id=prepared.change.resource_id,
            change_id=prepared.change.change_id,
        )

    def cleanup(
        self, prepared: PreparedPlaylistChange, terminal_evidence_ref: str
    ) -> MutationTrace:
        return self._lifecycle.cleanup(
            prepared.managed_file,
            resource_id=prepared.change.resource_id,
            change_id=prepared.change.change_id,
            terminal_evidence_ref=terminal_evidence_ref,
        )


def _intermediates(
    before: NormalizedResourceState, desired: NormalizedResourceState
) -> tuple[NormalizedResourceState, ...]:
    if (
        before.presence is Presence.PRESENT
        and desired.presence is Presence.PRESENT
        and before.content_digest != desired.content_digest
        and before.managed_mode != desired.managed_mode
    ):
        return (
            NormalizedResourceState(
                Presence.PRESENT,
                "regular",
                desired.content_digest,
                before.managed_mode,
            ),
        )
    return ()


def _assessment_match(assessment: PlaylistAssessment) -> bool | None:
    if assessment.relation.value == "satisfied":
        return True
    if assessment.relation.value == "unverifiable":
        return None
    return False


def _required_text(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("expected non-empty text")
    return value
