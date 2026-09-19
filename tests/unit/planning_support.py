import base64
import json
from pathlib import Path

FIXTURE_ROOT = Path(__file__).parents[1] / "fixtures" / "repository"


def desired_xml() -> bytes:
    return (
        b'<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>\n'
        b'<smartplaylist type="tvshows">\n'
        b"    <name>New Shows</name>\n"
        b"    <match>all</match>\n"
        b'    <rule field="playcount" operator="is">0</rule>\n'
        b"    <limit>50</limit>\n"
        b'    <order direction="descending">dateadded</order>\n'
        b"</smartplaylist>\n"
    )


def supplied_document(
    content: bytes | None,
    *,
    kind: str = "regular",
    mode: str | None = "0644",
) -> bytes:
    return json.dumps(
        {
            "kind": "CoreElecSuppliedPlanningInput",
            "observation": {
                "content_base64": (
                    None
                    if content is None
                    else base64.b64encode(content).decode("ascii")
                ),
                "kind": kind,
                "mode": mode,
                "observed_at": "2026-09-19T08:00:00Z",
                "resource_id": "skin.playlist.new-shows",
                "state_address": ("special://profile/playlists/video/NewShows.xsp"),
            },
            "runtime": {
                "artifact_resolution_digest": "sha256:" + "1" * 64,
                "controller_capabilities_digest": "sha256:" + "2" * 64,
                "created_at": "2026-09-19T08:01:00Z",
                "ended_at": "2026-09-19T08:01:01Z",
                "endpoint": {
                    "host": "coreelec-living-room.example.test",
                    "port": 22,
                },
                "expires_at": "2026-09-20T08:01:00Z",
                "plan_id": "0199542a-7800-7000-8000-000000000102",
                "planning_run_id": "0199542a-7800-7000-8000-000000000101",
                "platform_identity_fingerprint": "sha256:" + "3" * 64,
                "ssh_host_key_fingerprint": "SHA256:examplePinnedHostKey",
                "started_at": "2026-09-19T08:00:59Z",
            },
            "schema_version": 1,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
