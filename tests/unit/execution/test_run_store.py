import hashlib
import json
import os
import shutil
from pathlib import Path

import pytest

from coreelec_reconciler.domain.execution import (
    AppendIntent,
    AuthorityPhase,
    DeviceIndexIntent,
    DeviceLease,
    RevisionLease,
    RunStatus,
    SealIntent,
    WorkspaceId,
)
from coreelec_reconciler.domain.identifiers import DeviceId, RunId
from coreelec_reconciler.execution.local_durability import (
    DurabilityError,
    DurabilityOperation,
    ScriptedFault,
    ScriptedLocalDurability,
)
from coreelec_reconciler.execution.run_store import (
    CompareConflict,
    CorruptRunStore,
    LeaseUnavailable,
    RunStore,
    RunStoreError,
)
from coreelec_reconciler.reporting.canonical_json import canonical_document_bytes
from coreelec_reconciler.reporting.execution_documents import (
    build_execution_run_report,
)
from tests.unit.execution.test_execution_documents import (
    RUN_ID,
    run_value,
)


def store(
    tmp_path: Path,
    durability: ScriptedLocalDurability | None = None,
) -> RunStore:
    return RunStore(tmp_path / "store", durability)


def create(
    run_store: RunStore,
) -> tuple[DeviceLease, RevisionLease, WorkspaceId]:
    device_id = DeviceId("living-room.ugoos-am6b-plus")
    run_id = RunId(RUN_ID)
    device_lease = run_store.acquire_device(device_id)
    report = build_execution_run_report(run_value())
    revision_lease, workspace_id = run_store.create_run(
        device_lease,
        run_id,
        device_id,
        b"ownership-token",
        "sha256:" + hashlib.sha256(b"ownership-token").hexdigest(),
        report.canonical_bytes,
    )
    return device_lease, revision_lease, workspace_id


def test_run_store_persists_verified_chain_token_attachment_and_index(
    tmp_path: Path,
) -> None:
    run_store = store(tmp_path)
    device_lease, revision_lease, workspace_id = create(run_store)
    chain = run_store.load_chain(RunId(RUN_ID))
    assert chain.head.revision == 1
    assert not chain.terminal
    assert run_store.load_ownership_token(revision_lease) == b"ownership-token"

    reference = run_store.attach(
        revision_lease,
        "managed-file-before-state",
        "managed-file-v1",
        b"exact before bytes",
    )
    assert run_store.read_attachment(revision_lease, reference).payload == (
        b"exact before bytes"
    )
    active = run_store.find_active_by_device(device_lease.device_id)
    assert [item.workspace_id for item in active] == [workspace_id]
    assert all(
        stat & 0o077 == 0
        for stat in (
            os.stat(tmp_path / "store").st_mode,
            os.stat(tmp_path / "store" / "runs").st_mode,
        )
    )


def test_compare_append_seal_and_index_ordering(tmp_path: Path) -> None:
    run_store = store(tmp_path)
    device_lease, revision_lease, _ = create(run_store)
    first = run_store.load_chain(RunId(RUN_ID)).head
    terminal_report = build_execution_run_report(
        run_value(
            RunStatus.FAILED_PARTIAL,
            revision=2,
            previous=first.digest,
        )
    )
    terminal = run_store.compare_and_append(
        revision_lease,
        1,
        first.digest,
        terminal_report.canonical_bytes,
        AppendIntent(
            RunStatus.FAILED_PARTIAL,
            True,
            DeviceIndexIntent.ADD_OR_RETAIN_ACTIVE,
            AuthorityPhase.RELEASE_PENDING,
        ),
    )
    assert run_store.find_active_by_device(device_lease.device_id)
    run_store.finalize_and_seal(
        revision_lease,
        SealIntent(terminal.revision, True),
    )
    assert run_store.find_active_by_device(device_lease.device_id) == ()
    with pytest.raises(CompareConflict):
        run_store.compare_and_append(
            revision_lease,
            2,
            terminal.digest,
            terminal.payload,
            AppendIntent(
                RunStatus.FAILED_PARTIAL,
                True,
                DeviceIndexIntent.NO_CHANGE,
            ),
        )


def test_acknowledgement_loss_reconciles_matching_append_once(
    tmp_path: Path,
) -> None:
    durability = ScriptedLocalDurability(
        (ScriptedFault(DurabilityOperation.ACKNOWLEDGE, 11, True),)
    )
    run_store = store(tmp_path, durability)
    _, revision_lease, _ = create(run_store)
    first = run_store.load_chain(RunId(RUN_ID)).head
    next_report = build_execution_run_report(
        run_value(
            RunStatus.EXECUTING,
            revision=2,
            previous=first.digest,
        )
    )
    appended = run_store.compare_and_append(
        revision_lease,
        1,
        first.digest,
        next_report.canonical_bytes,
        AppendIntent(
            RunStatus.EXECUTING,
            False,
            DeviceIndexIntent.ADD_OR_RETAIN_ACTIVE,
            AuthorityPhase.REMOTE_OWNED,
        ),
    )
    assert appended.payload == next_report.canonical_bytes
    assert len(run_store.load_chain(RunId(RUN_ID)).revisions) == 2


def test_lost_revision_publication_ack_completes_head_state_and_index(
    tmp_path: Path,
) -> None:
    durability = ScriptedLocalDurability(
        (ScriptedFault(DurabilityOperation.ACKNOWLEDGE, 7, True),)
    )
    run_store = store(tmp_path, durability)
    device_lease, revision_lease, _ = create(run_store)
    first = run_store.load_chain(RunId(RUN_ID)).head
    next_report = build_execution_run_report(
        run_value(
            RunStatus.EXECUTING,
            revision=2,
            previous=first.digest,
        )
    )

    appended = run_store.compare_and_append(
        revision_lease,
        1,
        first.digest,
        next_report.canonical_bytes,
        AppendIntent(
            RunStatus.EXECUTING,
            False,
            DeviceIndexIntent.ADD_OR_RETAIN_ACTIVE,
            AuthorityPhase.REMOTE_OWNED,
        ),
    )

    chain = run_store.load_chain(RunId(RUN_ID))
    active = run_store.find_active_by_device(device_lease.device_id)
    assert appended == chain.head
    assert chain.head.revision == 2
    assert active[0].revision == 2
    assert active[0].revision_digest == appended.digest
    assert active[0].status is RunStatus.EXECUTING
    assert active[0].authority_phase is AuthorityPhase.REMOTE_OWNED


def test_durability_failure_fails_closed_without_device_work(tmp_path: Path) -> None:
    run_store = store(
        tmp_path,
        ScriptedLocalDurability((ScriptedFault(DurabilityOperation.FULL_SYNC_FILE),)),
    )
    device_id = DeviceId("living-room.ugoos-am6b-plus")
    lease = run_store.acquire_device(device_id)
    report = build_execution_run_report(run_value())
    with pytest.raises(DurabilityError):
        run_store.create_run(
            lease,
            RunId(RUN_ID),
            device_id,
            b"ownership-token",
            "sha256:" + hashlib.sha256(b"ownership-token").hexdigest(),
            report.canonical_bytes,
        )


def test_initial_revision_must_bind_private_token_and_opaque_workspace(
    tmp_path: Path,
) -> None:
    run_store = store(tmp_path)
    device_id = DeviceId("living-room.ugoos-am6b-plus")
    lease = run_store.acquire_device(device_id)
    wrong_token = build_execution_run_report(run_value()).canonical_bytes
    with pytest.raises(RunStoreError, match="ownership token"):
        run_store.create_run(
            lease,
            RunId(RUN_ID),
            device_id,
            b"different-token",
            "sha256:" + hashlib.sha256(b"different-token").hexdigest(),
            wrong_token,
        )


def test_workspace_identity_persists_and_enforces_all_immutable_bindings(
    tmp_path: Path,
) -> None:
    run_store = store(tmp_path)
    _, revision_lease, workspace_id = create(run_store)
    workspace = (
        tmp_path
        / "store"
        / "runs"
        / hashlib.sha256(workspace_id.value.encode()).hexdigest()
    )
    identity = json.loads((workspace / "identity.json").read_bytes())
    assert identity == {
        "binding_digest": "sha256:" + "a" * 64,
        "boot_id": "boot.opaque",
        "created_at": "2026-09-19T08:00:00Z",
        "device_id": "living-room.ugoos-am6b-plus",
        "kind": "CoreElecReconcilerRunReport",
        "originating_planning_run_id": ("019950f8-4c00-7000-8000-000000000201"),
        "ownership_token_digest": (
            "sha256:202b6cddfe21dac0427445df8c1756ec0a9bbc10f3b74cd4c693ebef3e63ae48"
        ),
        "plan_full_digest": "sha256:" + "b" * 64,
        "plan_id": "019950f8-4c00-7000-8000-000000000101",
        "producer": {"name": "coreelec-reconciler", "version": "0.1.0"},
        "run_id": RUN_ID,
        "schema_version": 1,
        "workspace_id": workspace_id.value,
    }

    first = run_store.load_chain(RunId(RUN_ID)).head
    drifted = run_value(
        RunStatus.EXECUTING,
        revision=2,
        previous=first.digest,
    )
    drifted["device_id"] = "bedroom.different-device"
    report = build_execution_run_report(drifted)
    with pytest.raises(RunStoreError, match="immutable"):
        run_store.compare_and_append(
            revision_lease,
            1,
            first.digest,
            report.canonical_bytes,
            AppendIntent(
                RunStatus.EXECUTING,
                False,
                DeviceIndexIntent.ADD_OR_RETAIN_ACTIVE,
                AuthorityPhase.REMOTE_OWNED,
            ),
        )


def test_load_chain_rejects_immutable_binding_drift_on_disk(
    tmp_path: Path,
) -> None:
    run_store = store(tmp_path)
    _, _, workspace_id = create(run_store)
    workspace = (
        tmp_path
        / "store"
        / "runs"
        / hashlib.sha256(workspace_id.value.encode()).hexdigest()
    )
    revision_path = workspace / "revisions" / "00000001.json"
    value = json.loads(revision_path.read_bytes())
    value["device_id"] = "bedroom.different-device"
    value.pop("current_digest")
    value["current_digest"] = (
        "sha256:" + hashlib.sha256(canonical_document_bytes(value)).hexdigest()
    )
    revision_path.write_bytes(canonical_document_bytes(value))
    (workspace / "head.json").write_bytes(
        canonical_document_bytes({"digest": value["current_digest"], "revision": 1})
    )

    with pytest.raises(CorruptRunStore, match="immutable"):
        run_store.load_chain(RunId(RUN_ID))


def test_secret_and_attachment_reads_reject_symlink_components(
    tmp_path: Path,
) -> None:
    run_store = store(tmp_path)
    _, revision_lease, workspace_id = create(run_store)
    workspace = (
        tmp_path
        / "store"
        / "runs"
        / hashlib.sha256(workspace_id.value.encode()).hexdigest()
    )
    token_path = workspace / "ownership-token.bin"
    token_copy = tmp_path / "copied-token"
    token_copy.write_bytes(token_path.read_bytes())
    token_path.unlink()
    token_path.symlink_to(token_copy)
    with pytest.raises(CorruptRunStore):
        run_store.load_ownership_token(revision_lease)

    token_path.unlink()
    token_path.write_bytes(b"ownership-token")
    reference = run_store.attach(revision_lease, "before", "v1", b"bytes")
    attachments = workspace / "attachments"
    moved = tmp_path / "moved-attachments"
    shutil.move(attachments, moved)
    attachments.symlink_to(moved, target_is_directory=True)
    with pytest.raises(CorruptRunStore):
        run_store.read_attachment(revision_lease, reference)


def test_revision_and_attachment_metadata_reads_reject_final_symlinks(
    tmp_path: Path,
) -> None:
    run_store = store(tmp_path)
    _, revision_lease, workspace_id = create(run_store)
    workspace = (
        tmp_path
        / "store"
        / "runs"
        / hashlib.sha256(workspace_id.value.encode()).hexdigest()
    )
    revision = workspace / "revisions" / "00000001.json"
    revision_copy = tmp_path / "copied-revision"
    revision_copy.write_bytes(revision.read_bytes())
    revision.unlink()
    revision.symlink_to(revision_copy)
    with pytest.raises(CorruptRunStore):
        run_store.load_chain(RunId(RUN_ID))

    revision.unlink()
    revision.write_bytes(revision_copy.read_bytes())
    reference = run_store.attach(revision_lease, "before", "v1", b"bytes")
    metadata = (
        workspace / "attachments" / f"{reference.digest.removeprefix('sha256:')}.json"
    )
    metadata_copy = tmp_path / "copied-metadata"
    metadata_copy.write_bytes(metadata.read_bytes())
    metadata.unlink()
    metadata.symlink_to(metadata_copy)
    with pytest.raises(CorruptRunStore):
        run_store.read_attachment(revision_lease, reference)


def test_leases_are_distinct_and_exclusive(tmp_path: Path) -> None:
    first = store(tmp_path)
    second = RunStore(tmp_path / "store")
    device_id = DeviceId("living-room.ugoos-am6b-plus")
    lease = first.acquire_device(device_id)
    with pytest.raises(LeaseUnavailable):
        second.acquire_device(device_id)
    first.release_device(lease)
    second_lease = second.acquire_device(device_id)
    second.release_device(second_lease)


def test_corruption_and_index_disagreement_fail_closed(tmp_path: Path) -> None:
    run_store = store(tmp_path)
    device_lease, revision_lease, workspace_id = create(run_store)
    index = next((tmp_path / "store" / "device-index").iterdir())
    index.write_bytes(b"{}")
    with pytest.raises(CorruptRunStore):
        run_store.find_active_by_device(device_lease.device_id)
    rebuilt = run_store.rebuild_active_device_index()
    assert rebuilt[0].workspace_id == workspace_id

    attachment = run_store.attach(revision_lease, "before", "v1", b"bytes")
    attachment_path = (
        tmp_path
        / "store"
        / "runs"
        / hashlib.sha256(workspace_id.value.encode()).hexdigest()
        / "attachments"
        / attachment.digest.removeprefix("sha256:")
    )
    attachment_path.write_bytes(b"corrupt")
    with pytest.raises(CorruptRunStore):
        run_store.read_attachment(revision_lease, attachment)
