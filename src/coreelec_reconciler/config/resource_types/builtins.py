"""Closed authored Resource Type parser registry."""

from collections.abc import Callable

from pydantic import BaseModel

from coreelec_reconciler.config.resource_types.kodi_smart_playlist import (
    KodiSmartPlaylistFragmentInput,
)

type AuthoredFragmentParser = Callable[[object], BaseModel]


def authored_fragment_parser(type_code: str) -> AuthoredFragmentParser | None:
    return {
        "KodiSmartPlaylist": KodiSmartPlaylistFragmentInput.model_validate,
    }.get(type_code)
