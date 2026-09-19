"""Strict authored fragments for KodiSmartPlaylist."""

from typing import Literal

from pydantic import BaseModel, ConfigDict


class _InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class PlaylistRuleFragmentInput(_InputModel):
    field: Literal["playcount"]
    operator: Literal["is"]
    value: Literal[0]


class PlaylistOrderFragmentInput(_InputModel):
    by: Literal["dateadded"] | None = None
    direction: Literal["descending"] | None = None


class PlaylistFragmentInput(_InputModel):
    id: Literal["playlist.video.new-shows"] | None = None
    media_type: Literal["tvshows"] | None = None
    display_name: Literal["New Shows"] | None = None
    match: Literal["all"] | None = None
    limit: Literal[40, 50] | None = None
    rules: list[PlaylistRuleFragmentInput] | None = None
    order: PlaylistOrderFragmentInput | None = None


class FileFragmentInput(_InputModel):
    mode: Literal["0644"] | None = None


class KodiSmartPlaylistFragmentInput(_InputModel):
    playlist: PlaylistFragmentInput | None = None
    file: FileFragmentInput | None = None
