"""Typed Kodi Smart Playlist execution kept inside the Resource Type."""

import hashlib
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
from coreelec_reconciler.execution.managed_file import (
    ManagedFileCapabilities,
    ManagedFileExecutionResult,
    ManagedFileExecutor,
    ManagedFileVerification,
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
)
from coreelec_reconciler.resource_types.managed_file.paths import (
    ResolvedManagedAddress,
)
from coreelec_reconciler.resource_types.managed_file.preparation import (
    AttachmentStore,
    PreparationBinding,
    PreparationObject,
    PreparedManagedFile,
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
        executor: ManagedFileExecutor,
        address: ResolvedManagedAddress,
        binding: PreparationBinding,
        *,
        read_limit: int = 1_048_576,
    ) -> None:
        self._files = files
        self._attachments = attachments
        self._executor = executor
        self._address = address
        self._binding = binding
        self._read_limit = read_limit

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
        return self._executor.apply(
            prepared.managed_file,
            resource_id=prepared.change.resource_id,
            change_id=prepared.change.change_id,
            rollback_approved=prepared.change.rollback_approved,
        )

    def verify(self, prepared: PreparedPlaylistChange) -> ManagedFileVerification:
        return self._executor.verify(prepared.managed_file)

    def rollback(
        self, prepared: PreparedPlaylistChange
    ) -> tuple[MutationTrace | None, ManagedFileVerification]:
        return self._executor.rollback(
            prepared.managed_file,
            resource_id=prepared.change.resource_id,
            change_id=prepared.change.change_id,
        )

    def cleanup(self, prepared: PreparedPlaylistChange) -> MutationTrace:
        return self._executor.cleanup(
            prepared.managed_file,
            resource_id=prepared.change.resource_id,
            change_id=prepared.change.change_id,
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
