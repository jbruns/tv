from typing import cast

from coreelec_reconciler.domain.configuration import (
    DesiredPresence,
    KodiSmartPlaylistIntent,
)
from coreelec_reconciler.domain.execution import (
    MutationTrace,
    NormalizedResourceState,
    Presence,
)
from coreelec_reconciler.resource_types.descriptor import ManagedFileLifecycle
from coreelec_reconciler.resource_types.kodi_smart_playlist.execution import (
    KodiSmartPlaylistExecution,
    PlaylistChange,
    PreparedPlaylistChange,
    desired_state,
)
from coreelec_reconciler.resource_types.kodi_smart_playlist.intent import (
    parse_intent,
)
from coreelec_reconciler.resource_types.managed_file.observation import (
    ManagedFileObservation,
)
from coreelec_reconciler.resource_types.managed_file.paths import (
    ManagedPath,
    ResolvedManagedAddress,
)
from coreelec_reconciler.resource_types.managed_file.preparation import (
    PreparationBinding,
    PreparedManagedFile,
)
from tests.fakes.run_infrastructure import FakeAttachments
from tests.fakes.runtime import FakeManagedFiles
from tests.unit.planning_support import desired_xml


def test_playlist_execution_renders_deterministic_managed_file_state() -> None:
    intent = _intent()

    state, content = desired_state(intent, DesiredPresence.PRESENT)

    assert state.managed_mode == 0o644
    assert state.content_digest is not None
    assert content is not None
    assert content.startswith(b'<?xml version="1.0" encoding="UTF-8"')


def test_execution_verification_uses_fresh_observation_and_pure_assessment() -> None:
    intent = _intent()
    content = desired_xml().replace(b"\n    ", b"\r\n\t")
    address = ResolvedManagedAddress(
        "special://profile/playlists/video/NewShows.xsp",
        ManagedPath("/storage/.kodi/userdata/playlists/video/NewShows.xsp"),
    )
    observation = ManagedFileObservation(
        address,
        NormalizedResourceState(
            Presence.PRESENT, "regular", "sha256:semantic-equivalent", 0o644
        ),
        content,
    )
    lifecycle = _CapturingLifecycle(observation)
    runtime = KodiSmartPlaylistExecution(
        FakeManagedFiles(),
        FakeAttachments(),
        cast(ManagedFileLifecycle, lifecycle),
        address,
        PreparationBinding(
            "device", "binding", "run", "skin.playlist.new-shows", "change"
        ),
        intent,
        DesiredPresence.PRESENT,
        lambda: "2026-09-19T08:00:00Z",
    )
    change = PlaylistChange(
        "skin.playlist.new-shows",
        "change",
        intent,
        DesiredPresence.PRESENT,
        observation.state,
        True,
    )

    runtime.apply(PreparedPlaylistChange(change, cast(PreparedManagedFile, object())))

    assert lifecycle.semantic_match is True


class _CapturingLifecycle:
    def __init__(self, observation: ManagedFileObservation) -> None:
        self.observation = observation
        self.semantic_match: bool | None = None

    def apply(self, prepared: PreparedManagedFile, **kwargs: object) -> object:
        verify = kwargs["verify"]
        assert callable(verify)
        self.semantic_match = verify(self.observation)
        return object()

    def rollback(self, prepared: PreparedManagedFile, **kwargs: object) -> object:
        return object()

    def cleanup(self, prepared: PreparedManagedFile, **kwargs: object) -> MutationTrace:
        return MutationTrace(())


def _intent() -> KodiSmartPlaylistIntent:
    return parse_intent(
        {
            "playlist": {
                "display_name": "New Shows",
                "id": "playlist.video.new-shows",
                "limit": 50,
                "match": "all",
                "media_type": "tvshows",
                "order": {"by": "dateadded", "direction": "descending"},
                "rules": [
                    {"field": "playcount", "operator": "is", "value": 0},
                ],
            },
            "file": {"mode": "0644"},
        },
        DesiredPresence.PRESENT,
    )
