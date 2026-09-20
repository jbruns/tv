import hashlib
from copy import deepcopy
from pathlib import Path
from typing import cast

import pytest

from coreelec_reconciler.domain.canonical_json import (
    canonical_document_bytes,
    decode_json_object,
)
from coreelec_reconciler.domain.execution import (
    DeviceLease,
    SessionCloseDisposition,
    SessionCloseFailureCategory,
    SessionCloseIntent,
    decode_session_close_record,
)
from coreelec_reconciler.domain.identifiers import DeviceId, RunId
from coreelec_reconciler.domain.observation import (
    ObservationAppendIntent,
    ObservationRunStatus,
)
from coreelec_reconciler.execution.local_durability import PosixLocalDurability
from coreelec_reconciler.execution.run_store import (
    CompareConflict,
    CorruptRunStore,
    RunStore,
    RunStoreError,
)
from coreelec_reconciler.persistence.execution_documents import (
    check_session_close_invariants,
)
from coreelec_reconciler.persistence.observation_documents import (
    build_observation_run,
    check_observation_chain_invariants,
    check_observation_run_invariants,
    decode_observation_run,
    verify_observation_revision_chain,
)
from coreelec_reconciler.resource_types.kodi_smart_playlist.observation_codecs import (
    OBSERVATION_PAYLOAD_KIND,
    OBSERVATION_PAYLOAD_VERSION,
    OBSERVATION_POLICY_DIGEST,
)

RUN_ID = "019950f8-4c00-7000-8000-000000000901"
OTHER_RUN_ID = "019950f8-4c00-7000-8000-000000000902"
DEVICE_ID = "living-room.ugoos-am6b-plus"
WORKSPACE_ID = f"workspace:{RUN_ID}"
SHA_A = "sha256:" + "a" * 64
SHA_B = "sha256:" + "b" * 64
SHA_C = "sha256:" + "c" * 64
SHA_D = "sha256:" + "d" * 64
SHA_E = "sha256:" + "e" * 64
RAW = b"<smartplaylist/>"
RAW_DIGEST = "sha256:" + hashlib.sha256(RAW).hexdigest()


def scope_value() -> dict[str, object]:
    codec = {
        "kind": OBSERVATION_PAYLOAD_KIND,
        "policy_digest": OBSERVATION_POLICY_DIGEST,
        "schema_version": OBSERVATION_PAYLOAD_VERSION,
    }
    return {
        "artifact_set_digest": SHA_A,
        "capability_digest": SHA_B,
        "configuration_digest": SHA_C,
        "profile_digest": SHA_D,
        "resources": [
            {
                "observation_codec": codec,
                "requires": [],
                "resource_id": "skin.playlist.alpha",
                "resource_type": "KodiSmartPlaylist",
                "state_addresses": [
                    "special://profile/playlists/video/Alpha.xsp",
                ],
            },
            {
                "observation_codec": codec,
                "requires": ["skin.playlist.alpha"],
                "resource_id": "skin.playlist.beta",
                "resource_type": "KodiSmartPlaylist",
                "state_addresses": [
                    "special://profile/playlists/video/Beta.xsp",
                ],
            },
        ],
        "selector_digest": SHA_E,
    }


def regular_payload() -> dict[str, object]:
    return {
        "availability": "available",
        "content_digest": RAW_DIGEST,
        "entry_type": "regular",
        "failure_code": None,
        "mode": 0o644,
        "presence": "present",
        "readability": "readable",
        "safety": "safe",
    }


def unavailable_payload() -> dict[str, object]:
    return {
        "availability": "unavailable",
        "content_digest": None,
        "entry_type": "unknown",
        "failure_code": "transport.timeout",
        "mode": None,
        "presence": "unknown",
        "readability": "unknown",
        "safety": "unknown",
    }


def unknown_payload() -> dict[str, object]:
    value = unavailable_payload()
    value["availability"] = "unknown"
    value["failure_code"] = "transport.result_unknown"
    return value


def unsafe_payload() -> dict[str, object]:
    return {
        "availability": "available",
        "content_digest": None,
        "entry_type": "symlink",
        "failure_code": None,
        "mode": None,
        "presence": "present",
        "readability": "not_applicable",
        "safety": "unsafe",
    }


def absent_payload() -> dict[str, object]:
    return {
        "availability": "available",
        "content_digest": None,
        "entry_type": None,
        "failure_code": None,
        "mode": None,
        "presence": "absent",
        "readability": "not_applicable",
        "safety": "safe",
    }


def unreadable_payload() -> dict[str, object]:
    return {
        "availability": "available",
        "content_digest": None,
        "entry_type": "regular",
        "failure_code": "resource.unreadable",
        "mode": 0o600,
        "presence": "present",
        "readability": "unreadable",
        "safety": "safe",
    }


def checkpoint(
    index: int,
    *,
    payload: dict[str, object] | None = None,
    disposition: str = "observed",
) -> dict[str, object]:
    resource_id = ("skin.playlist.alpha", "skin.playlist.beta")[index]
    address = (
        "special://profile/playlists/video/Alpha.xsp",
        "special://profile/playlists/video/Beta.xsp",
    )[index]
    actual_payload = payload or regular_payload()
    return {
        "disposition": disposition,
        "evidence": {
            "payload": actual_payload,
            "payload_kind": OBSERVATION_PAYLOAD_KIND,
            "payload_schema_version": OBSERVATION_PAYLOAD_VERSION,
        },
        "observed_at": f"2026-09-20T06:00:0{index + 1}Z",
        "observer": {"code": "managed-file-observer", "version": 1},
        "raw_attachments": (
            [
                {
                    "codec": "raw-bytes-v1",
                    "digest": RAW_DIGEST,
                    "kind": "raw-observation",
                }
            ]
            if actual_payload["content_digest"] is not None
            else []
        ),
        "resource_id": resource_id,
        "resource_type": "KodiSmartPlaylist",
        "sequence": index + 1,
        "state_addresses": [address],
    }


def run_value(
    revision: int,
    status: str,
    checkpoints: list[dict[str, object]],
    *,
    previous: str | None = None,
    run_id: str = RUN_ID,
    workspace_id: str = WORKSPACE_ID,
    scope: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "checkpoints": checkpoints,
        "completed_resource_ids": [str(item["resource_id"]) for item in checkpoints],
        "device_id": DEVICE_ID,
        "ended_at": (
            "2026-09-20T06:01:00Z"
            if status in {"observed", "observed_partial"}
            else None
        ),
        "kind": "CoreElecReconcilerObservationRun",
        "previous_revision_digest": previous,
        "producer": {"name": "coreelec-reconciler", "version": "0.1.0"},
        "revision": revision,
        "run_id": run_id,
        "schema_version": 1,
        "scope": scope or scope_value(),
        "started_at": "2026-09-20T06:00:00Z",
        "status": status,
        "workspace_id": workspace_id,
    }


def lifecycle(*, partial: bool = True) -> tuple[bytes, ...]:
    ready = build_observation_run(run_value(1, "ready", []))
    observing = build_observation_run(
        run_value(2, "observing", [], previous=ready.current_digest)
    )
    first = build_observation_run(
        run_value(
            3,
            "observing",
            [checkpoint(0)],
            previous=observing.current_digest,
        )
    )
    second_checkpoint = (
        checkpoint(1, payload=unavailable_payload(), disposition="unavailable")
        if partial
        else checkpoint(1)
    )
    terminal = build_observation_run(
        run_value(
            4,
            "observed_partial" if partial else "observed",
            [checkpoint(0), second_checkpoint],
            previous=first.current_digest,
        )
    )
    return tuple(item.canonical_bytes for item in (ready, observing, first, terminal))


def create_store(tmp_path: Path) -> tuple[RunStore, DeviceLease]:
    store = RunStore(tmp_path / "store", FastTestDurability())
    lease = store.acquire_device(DeviceId(DEVICE_ID))
    return store, lease


class FastTestDurability(PosixLocalDurability):
    def full_sync_file(self, object_id: str) -> None:
        del object_id

    def sync_directory(self, directory_id: str) -> None:
        del directory_id

    def acknowledge(self, operation_id: str) -> None:
        del operation_id


def test_observation_document_round_trip_golden_and_independent_oracle() -> None:
    revisions = lifecycle()
    decoded = verify_observation_revision_chain(revisions)
    terminal = decoded[-1]

    assert terminal.status is ObservationRunStatus.OBSERVED_PARTIAL
    assert tuple(item.resource_id for item in terminal.scope.resources) == (
        "skin.playlist.alpha",
        "skin.playlist.beta",
    )
    assert terminal.scope.resources[1].requires == ("skin.playlist.alpha",)
    assert check_observation_chain_invariants(revisions) == ()
    complete = verify_observation_revision_chain(lifecycle(partial=False))[-1]
    assert complete.status is ObservationRunStatus.OBSERVED
    fixture_directory = Path(__file__).parents[2] / "fixtures" / "canonical"
    ready_fixture = fixture_directory / "observation-run-ready-v1.json"
    partial_fixture = fixture_directory / "observation-run-partial-v1.json"
    assert ready_fixture.read_bytes() == revisions[0]
    assert partial_fixture.read_bytes() == terminal.canonical_bytes
    assert decode_observation_run(ready_fixture.read_bytes()).status is (
        ObservationRunStatus.READY
    )
    assert decode_observation_run(partial_fixture.read_bytes()) == terminal


def test_observation_document_rejects_closed_schema_and_scope_mutations() -> None:
    base = run_value(1, "ready", [])
    mutations: list[tuple[str, object]] = [
        ("plan_id", "019950f8-4c00-7000-8000-000000000999"),
        ("approvals", []),
    ]
    for field, invalid in mutations:
        candidate = dict(base)
        candidate[field] = invalid
        with pytest.raises(ValueError):
            build_observation_run(candidate)

    candidates: list[dict[str, object]] = []
    for case in range(7):
        candidate = deepcopy(base)
        scope = cast(dict[str, object], candidate["scope"])
        resources = cast(list[dict[str, object]], scope["resources"])
        if case == 0:
            codec = cast(dict[str, object], resources[0]["observation_codec"])
            codec["schema_version"] = 999
        elif case == 1:
            resources[1]["requires"] = ["missing.resource"]
        elif case == 2:
            resources[0]["requires"] = ["skin.playlist.alpha"]
        elif case == 3:
            resources[1]["requires"] = []
            resources.reverse()
        elif case == 4:
            resources[0]["state_addresses"] = ["../../etc/passwd"]
        elif case == 5:
            resources[0]["resource_type"] = "InventedResource"
        else:
            resources[1]["resource_id"] = "skin.playlist.alpha"
        candidates.append(candidate)
    for candidate in candidates:
        with pytest.raises((TypeError, ValueError)):
            build_observation_run(candidate)


def test_observation_payload_rejects_unknown_tampered_and_contradictory_states() -> (
    None
):
    invalid_payloads = []
    unknown = regular_payload()
    unknown["invented"] = True
    invalid_payloads.append(unknown)
    contradictory = regular_payload()
    contradictory["availability"] = "unavailable"
    invalid_payloads.append(contradictory)
    unsafe_with_content = unsafe_payload()
    unsafe_with_content["content_digest"] = RAW_DIGEST
    invalid_payloads.append(unsafe_with_content)
    malformed_failure = unavailable_payload()
    malformed_failure["failure_code"] = "../secret"
    invalid_payloads.append(malformed_failure)
    for payload in invalid_payloads:
        with pytest.raises(ValueError):
            build_observation_run(
                run_value(
                    2,
                    "observing",
                    [checkpoint(0, payload=payload)],
                    previous=SHA_A,
                )
            )
    for field, invalid in (
        ("payload_kind", "InventedObservation"),
        ("payload_schema_version", 999),
    ):
        invalid_checkpoint = checkpoint(0)
        evidence = cast(dict[str, object], invalid_checkpoint["evidence"])
        evidence[field] = invalid
        with pytest.raises(ValueError):
            build_observation_run(
                run_value(
                    2,
                    "observing",
                    [invalid_checkpoint],
                    previous=SHA_A,
                )
            )
    extra_field_checkpoint = checkpoint(0)
    extra_field_checkpoint["invented"] = True
    with pytest.raises(ValueError):
        build_observation_run(
            run_value(
                2,
                "observing",
                [extra_field_checkpoint],
                previous=SHA_A,
            )
        )
    duplicate_attachment = checkpoint(0)
    attachments = cast(
        list[dict[str, object]],
        duplicate_attachment["raw_attachments"],
    )
    attachments.append(dict(attachments[0]))
    with pytest.raises(ValueError, match="duplicate"):
        build_observation_run(
            run_value(
                2,
                "observing",
                [duplicate_attachment],
                previous=SHA_A,
            )
        )

    valid_unsafe = build_observation_run(
        run_value(
            2,
            "observing",
            [checkpoint(0, payload=unsafe_payload())],
            previous=SHA_A,
        )
    )
    assert check_observation_run_invariants(valid_unsafe.canonical_bytes) == ()
    valid_unknown = build_observation_run(
        run_value(
            2,
            "observing",
            [checkpoint(0, payload=unknown_payload(), disposition="unknown")],
            previous=SHA_A,
        )
    )
    assert check_observation_run_invariants(valid_unknown.canonical_bytes) == ()
    for payload in (absent_payload(), unreadable_payload()):
        valid = build_observation_run(
            run_value(
                2,
                "observing",
                [checkpoint(0, payload=payload)],
                previous=SHA_A,
            )
        )
        assert check_observation_run_invariants(valid.canonical_bytes) == ()
    malformed = decode_json_object(valid_unknown.canonical_bytes)
    malformed_checkpoints = cast(list[dict[str, object]], malformed["checkpoints"])
    malformed_evidence = cast(
        dict[str, object],
        malformed_checkpoints[0]["evidence"],
    )
    malformed_payload = cast(dict[str, object], malformed_evidence["payload"])
    malformed_payload["availability"] = []
    without_digest = {
        key: item for key, item in malformed.items() if key != "current_digest"
    }
    malformed["current_digest"] = (
        "sha256:" + hashlib.sha256(canonical_document_bytes(without_digest)).hexdigest()
    )
    assert check_observation_run_invariants(canonical_document_bytes(malformed))


def test_observation_chain_rejects_invalid_history() -> None:
    revisions = list(lifecycle())
    first = decode_observation_run(revisions[2])
    rewritten = build_observation_run(
        run_value(
            3,
            "observing",
            [checkpoint(0, payload=unsafe_payload())],
            previous=decode_observation_run(revisions[1]).current_digest,
        )
    )
    rewritten_successor = build_observation_run(
        run_value(
            4,
            "observed_partial",
            [
                checkpoint(0),
                checkpoint(
                    1,
                    payload=unavailable_payload(),
                    disposition="unavailable",
                ),
            ],
            previous=rewritten.current_digest,
        )
    )
    changed_scope = scope_value()
    changed_scope["selector_digest"] = SHA_A
    changed = build_observation_run(
        run_value(
            3,
            "observing",
            [checkpoint(0)],
            previous=decode_observation_run(revisions[1]).current_digest,
            scope=changed_scope,
        )
    )
    successor = build_observation_run(
        run_value(
            5,
            "observed_partial",
            [
                checkpoint(0),
                checkpoint(1, payload=unavailable_payload(), disposition="unavailable"),
            ],
            previous=decode_observation_run(revisions[3]).current_digest,
        )
    )
    candidates = (
        (revisions[0], revisions[2]),
        (
            revisions[0],
            revisions[1],
            rewritten.canonical_bytes,
            rewritten_successor.canonical_bytes,
        ),
        (revisions[0], revisions[1], changed.canonical_bytes),
        (*revisions, successor.canonical_bytes),
    )
    for candidate in candidates:
        with pytest.raises(ValueError):
            verify_observation_revision_chain(candidate)
        assert check_observation_chain_invariants(candidate)
    tampered = decode_json_object(revisions[2])
    tampered["status"] = "observed"
    tampered_bytes = canonical_document_bytes(tampered)
    with pytest.raises(ValueError, match="digest"):
        decode_observation_run(tampered_bytes)
    assert check_observation_run_invariants(tampered_bytes)
    out_of_order = run_value(
        2,
        "observing",
        [checkpoint(1)],
        previous=decode_observation_run(revisions[0]).current_digest,
    )
    with pytest.raises(ValueError, match="checkpoint"):
        build_observation_run(out_of_order)
    assert first.checkpoints[0].payload == regular_payload()


def test_run_store_observation_restart_boundaries_and_terminal_session_close(
    tmp_path: Path,
) -> None:
    revisions = lifecycle()
    store, device_lease = create_store(tmp_path)
    initial = decode_observation_run(revisions[0])
    run_lease, _ = store.create_observation_run(
        device_lease,
        RunId(RUN_ID),
        DeviceId(DEVICE_ID),
        revisions[0],
    )
    attachment = store.attach(
        run_lease,
        "raw-observation",
        "raw-bytes-v1",
        RAW,
    )
    assert attachment.digest == RAW_DIGEST
    store.release_run(run_lease)
    for stop_after in range(1, len(revisions) + 1):
        reopened = RunStore(tmp_path / "store", FastTestDurability())
        loaded = reopened.load_observation_run(RunId(RUN_ID))
        workspace = next((tmp_path / "store" / "runs").iterdir())
        assert not (workspace / "ownership-token.bin").exists()
        assert loaded.revision == stop_after
        assert (
            loaded.checkpoints
            == decode_observation_run(revisions[stop_after - 1]).checkpoints
        )
        assert reopened.find_active_by_device(DeviceId(DEVICE_ID)) == ()
        reacquired = reopened.acquire_run(RunId(RUN_ID))
        if stop_after == 1:
            with pytest.raises(RunStoreError, match="terminal"):
                reopened.record_session_close(reacquired, close_intent())
        if stop_after < len(revisions):
            next_run = decode_observation_run(revisions[stop_after])
            reopened.compare_and_append_observation(
                reacquired,
                loaded.revision,
                loaded.current_digest,
                revisions[stop_after],
                ObservationAppendIntent(
                    next_run.status,
                    next_run.status
                    in {
                        ObservationRunStatus.OBSERVED,
                        ObservationRunStatus.OBSERVED_PARTIAL,
                    },
                ),
            )
            reopened.release_run(reacquired)
            continue
        record = reopened.record_session_close(reacquired, close_intent())
        assert record.schema_version == 2
        assert record.run_kind == "CoreElecReconcilerObservationRun"
        assert record.authority_state == "not_applicable"
        assert record.seal_digest is None
        assert check_session_close_invariants(record.canonical_bytes) == ()
        invalid_close = decode_json_object(record.canonical_bytes)
        invalid_close["run_kind"] = "CoreElecReconcilerRunReport"
        close_without_digest = {
            key: item for key, item in invalid_close.items() if key != "current_digest"
        }
        invalid_close["current_digest"] = (
            "sha256:"
            + hashlib.sha256(canonical_document_bytes(close_without_digest)).hexdigest()
        )
        invalid_close_bytes = canonical_document_bytes(invalid_close)
        with pytest.raises(ValueError, match="version 2"):
            decode_session_close_record(invalid_close_bytes)
        assert check_session_close_invariants(invalid_close_bytes)
        assert (
            reopened.inspect_session_close(
                RunId(RUN_ID),
                record.session_id,
            ).record
            == record
        )
        assert initial.scope == loaded.scope
        attachment_path = workspace / "attachments" / RAW_DIGEST.removeprefix("sha256:")
        attachment_path.unlink()
        with pytest.raises(CorruptRunStore):
            reopened.load_observation_run(RunId(RUN_ID))


def test_run_store_rejects_cross_run_and_post_terminal_observation_appends(
    tmp_path: Path,
) -> None:
    revisions = lifecycle()
    store, device_lease = create_store(tmp_path)
    lease, _ = store.create_observation_run(
        device_lease,
        RunId(RUN_ID),
        DeviceId(DEVICE_ID),
        revisions[0],
    )
    store.attach(lease, "raw-observation", "raw-bytes-v1", RAW)
    cross_run = build_observation_run(
        run_value(
            2,
            "observing",
            [],
            previous=decode_observation_run(revisions[0]).current_digest,
            run_id=OTHER_RUN_ID,
            workspace_id=f"workspace:{OTHER_RUN_ID}",
        )
    )
    with pytest.raises(RunStoreError):
        store.compare_and_append_observation(
            lease,
            1,
            decode_observation_run(revisions[0]).current_digest,
            cross_run.canonical_bytes,
            ObservationAppendIntent(ObservationRunStatus.OBSERVING, False),
        )
    with pytest.raises(CompareConflict, match="head changed"):
        store.compare_and_append_observation(
            lease,
            1,
            SHA_A,
            revisions[1],
            ObservationAppendIntent(ObservationRunStatus.OBSERVING, False),
        )
    for payload in revisions[1:]:
        current = store.load_chain(RunId(RUN_ID)).head
        next_run = decode_observation_run(payload)
        store.compare_and_append_observation(
            lease,
            current.revision,
            current.digest,
            payload,
            ObservationAppendIntent(
                next_run.status,
                next_run.status
                in {
                    ObservationRunStatus.OBSERVED,
                    ObservationRunStatus.OBSERVED_PARTIAL,
                },
            ),
        )
    with pytest.raises(CompareConflict, match=r"head changed|immutable"):
        store.compare_and_append_observation(
            lease,
            4,
            decode_observation_run(revisions[3]).current_digest,
            revisions[3],
            ObservationAppendIntent(ObservationRunStatus.OBSERVED_PARTIAL, True),
        )


def close_intent() -> SessionCloseIntent:
    return SessionCloseIntent(
        record_id="019950f8-4c00-7000-8000-000000000903",
        session_id="session.019950f8-4c00-7000-8000-000000000904",
        observed_at="2026-09-20T06:02:00Z",
        disposition=SessionCloseDisposition.UNKNOWN,
        failure_category=SessionCloseFailureCategory.TRANSPORT,
        failure_code="transport.close_unknown",
    )
