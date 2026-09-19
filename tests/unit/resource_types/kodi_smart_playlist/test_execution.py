from coreelec_reconciler.domain.configuration import DesiredPresence
from coreelec_reconciler.resource_types.kodi_smart_playlist.execution import (
    desired_state,
)
from coreelec_reconciler.resource_types.kodi_smart_playlist.intent import (
    parse_intent,
)


def test_playlist_execution_renders_deterministic_managed_file_state() -> None:
    intent = parse_intent(
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

    state, content = desired_state(intent, DesiredPresence.PRESENT)

    assert state.managed_mode == 0o644
    assert state.content_digest is not None
    assert content is not None
    assert content.startswith(b'<?xml version="1.0" encoding="UTF-8"')
