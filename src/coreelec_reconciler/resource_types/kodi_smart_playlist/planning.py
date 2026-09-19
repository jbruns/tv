"""Pure Kodi Smart Playlist observation assessment."""

import hashlib
import json

from coreelec_reconciler.domain.configuration import (
    DesiredPresence,
    KodiSmartPlaylistIntent,
    ManagementMode,
)
from coreelec_reconciler.domain.planning import (
    DesiredRelation,
    FileKind,
    KodiSmartPlaylistObservation,
    PlaylistAssessment,
    PlaylistSemanticModel,
)
from coreelec_reconciler.resource_types.kodi_smart_playlist.xml import (
    PlaylistXmlError,
    parse_playlist_xml,
)


def desired_model(intent: KodiSmartPlaylistIntent) -> PlaylistSemanticModel:
    playlist = intent.playlist
    if (
        playlist.display_name is None
        or playlist.match is None
        or playlist.limit is None
        or playlist.order is None
    ):
        raise ValueError("present playlist Intent is incomplete")
    return PlaylistSemanticModel(
        media_type=playlist.media_type,
        display_name=playlist.display_name,
        match=playlist.match,
        limit=playlist.limit,
        rules=tuple((rule.field, rule.operator, rule.value) for rule in playlist.rules),
        order=(playlist.order.by, playlist.order.direction),
    )


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


def _digest(value: object) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value)).hexdigest()


def _model_value(model: PlaylistSemanticModel) -> dict[str, object]:
    return {
        "display_name": model.display_name,
        "limit": model.limit,
        "match": model.match,
        "media_type": model.media_type,
        "order": {"by": model.order[0], "direction": model.order[1]},
        "rules": [
            {"field": field, "operator": operator, "value": value}
            for field, operator, value in model.rules
        ],
    }


def _summary(**values: object) -> tuple[tuple[str, object], ...]:
    return tuple(sorted(values.items()))


def assess_playlist(
    intent: KodiSmartPlaylistIntent,
    desired: DesiredPresence,
    management: ManagementMode,
    observation: KodiSmartPlaylistObservation,
) -> PlaylistAssessment:
    before_value: dict[str, object]
    desired_summary: tuple[tuple[str, object], ...]
    desired_value: object
    if desired is DesiredPresence.ABSENT:
        desired_summary = _summary(presence="absent")
        desired_value = {"presence": "absent"}
    else:
        model = desired_model(intent)
        desired_summary = _summary(
            display_name=model.display_name,
            limit=model.limit,
            media_type=model.media_type,
            mode=int(intent.file_mode or "0", 8),
            presence="present",
        )
        desired_value = {
            "mode": intent.file_mode,
            "playlist": _model_value(model),
            "presence": "present",
        }
    desired_digest = _digest(desired_value)

    if observation.kind is FileKind.ABSENT:
        before_value = {"presence": "absent"}
        before_summary = _summary(presence="absent")
        before_digest = _digest(before_value)
        if desired is DesiredPresence.ABSENT:
            return PlaylistAssessment(
                DesiredRelation.SATISFIED,
                management,
                None,
                (),
                (),
                (),
                before_digest,
                desired_digest,
                before_summary,
                desired_summary,
            )
        operation = (
            "smart_playlist.create" if management is ManagementMode.ENFORCE else None
        )
        blockers = (
            ()
            if management is ManagementMode.ENFORCE
            else ("resource.observe-only-divergence",)
        )
        return PlaylistAssessment(
            DesiredRelation.DIVERGENT,
            management,
            operation,
            ("playlist.absent",),
            ("content_mutation",) if operation else (),
            blockers,
            before_digest,
            desired_digest,
            before_summary,
            desired_summary,
        )

    if observation.kind is not FileKind.REGULAR:
        before_value = {"kind": observation.kind.value, "presence": "present"}
        return PlaylistAssessment(
            DesiredRelation.UNVERIFIABLE,
            management,
            None,
            (),
            (),
            (f"resource.unsafe-{observation.kind.value}",),
            _digest(before_value),
            desired_digest,
            _summary(kind=observation.kind.value, presence="present"),
            desired_summary,
        )

    if observation.mode is None or observation.content is None:
        before_value = {
            "presence": "present",
            "readable": False,
        }
        return PlaylistAssessment(
            DesiredRelation.UNVERIFIABLE,
            management,
            None,
            (),
            (),
            ("resource.unreadable",),
            _digest(before_value),
            desired_digest,
            _summary(presence="present", readable=False),
            desired_summary,
        )

    if desired is DesiredPresence.ABSENT:
        before_value = {
            "content_sha256": hashlib.sha256(observation.content).hexdigest(),
            "mode": observation.mode,
            "presence": "present",
        }
        operation = (
            "smart_playlist.remove" if management is ManagementMode.ENFORCE else None
        )
        blockers = (
            ()
            if management is ManagementMode.ENFORCE
            else ("resource.observe-only-divergence",)
        )
        return PlaylistAssessment(
            DesiredRelation.DIVERGENT,
            management,
            operation,
            ("playlist.desired-absent",),
            ("content_mutation", "removal") if operation else (),
            blockers,
            _digest(before_value),
            desired_digest,
            _summary(mode=int(observation.mode, 8), presence="present"),
            desired_summary,
        )

    reasons: list[str] = []
    try:
        current_model = parse_playlist_xml(observation.content)
        semantic_value: object = _model_value(current_model)
        if current_model != desired_model(intent):
            reasons.append("playlist.semantic-drift")
    except PlaylistXmlError:
        current_model = None
        content_digest = hashlib.sha256(observation.content).hexdigest()
        semantic_value = {
            "content_sha256": content_digest,
            "parse": "malformed",
        }
        reasons.append("playlist.malformed-current")
    if observation.mode != intent.file_mode:
        reasons.append("managed-file.mode-drift")
    before_value = {
        "mode": observation.mode,
        "playlist": semantic_value,
        "presence": "present",
    }
    before_summary = _summary(
        mode=int(observation.mode, 8),
        playlist=(
            {"parse_status": "malformed"}
            if current_model is None
            else _model_value(current_model)
        ),
        presence="present",
    )
    if current_model is None:
        before_summary = _summary(
            content_digest="sha256:" + hashlib.sha256(observation.content).hexdigest(),
            mode=int(observation.mode, 8),
            playlist={"parse_status": "malformed"},
            presence="present",
        )
    if not reasons:
        return PlaylistAssessment(
            DesiredRelation.SATISFIED,
            management,
            None,
            (),
            (),
            (),
            _digest(before_value),
            desired_digest,
            before_summary,
            desired_summary,
        )
    operation = (
        "smart_playlist.update" if management is ManagementMode.ENFORCE else None
    )
    blockers = (
        ()
        if management is ManagementMode.ENFORCE
        else ("resource.observe-only-divergence",)
    )
    return PlaylistAssessment(
        DesiredRelation.DIVERGENT,
        management,
        operation,
        tuple(reasons),
        ("content_mutation",) if operation else (),
        blockers,
        _digest(before_value),
        desired_digest,
        before_summary,
        desired_summary,
    )
