"""Pure Kodi Smart Playlist resolution owned by its Resource Type."""

from coreelec_reconciler.domain.configuration import KodiSmartPlaylistIntent


def state_addresses(intent: KodiSmartPlaylistIntent) -> tuple[str, ...]:
    if (
        intent.playlist.id != "playlist.video.new-shows"
        or intent.playlist.media_type != "tvshows"
    ):
        raise ValueError("unsupported Kodi Smart Playlist identity")
    return ("special://profile/playlists/video/NewShows.xsp",)
