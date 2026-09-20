from dataclasses import dataclass
from pathlib import Path

import pytest

from coreelec_reconciler.domain.canonical_json import canonical_document_bytes
from coreelec_reconciler.domain.execution import (
    AppendIntent,
    NormalizedResourceState,
    Presence,
    RevisionLease,
    StoredRevision,
)
from coreelec_reconciler.domain.identifiers import DeviceId, RunId
from coreelec_reconciler.domain.planning import DesiredRelation
from coreelec_reconciler.execution.run_store import RunStore
from coreelec_reconciler.execution.runtime import FiniteRuntimeValues
from coreelec_reconciler.execution.verification import (
    CanonicalVerificationBinding,
    CanonicalVerificationRuns,
    ResourceVerification,
    VerificationRelation,
    VerificationRequest,
    VerificationResource,
)
from coreelec_reconciler.resource_types.builtins import built_in_resource_registry
from coreelec_reconciler.resource_types.managed_file.observation import (
    ManagedFileObservation,
)
from coreelec_reconciler.resource_types.managed_file.paths import (
    ManagedPath,
    ResolvedManagedAddress,
)


@dataclass(frozen=True)
class _Assessment:
    relation: DesiredRelation


class _ReadOnlyExecution:
    def __init__(
        self,
        resource_id: str,
        relation: DesiredRelation,
        calls: list[str],
    ) -> None:
        self._resource_id = resource_id
        self._relation = relation
        self._calls = calls
        address = f"special://profile/playlists/video/{resource_id}.xsp"
        self._observation = ManagedFileObservation(
            ResolvedManagedAddress(address, ManagedPath(f"/device/{resource_id}.xsp")),
            NormalizedResourceState(Presence.ABSENT, None, None, None),
            None,
        )

    def observe(self) -> object:
        self._calls.append(f"observe:{self._resource_id}")
        return self._observation

    def assess(self, observation: object) -> object:
        assert observation is self._observation
        self._calls.append(f"assess:{self._resource_id}")
        return _Assessment(self._relation)

    def prepare(self, change: object) -> object:
        raise AssertionError("verification requested preparation")

    def apply(self, prepared: object) -> object:
        raise AssertionError("verification requested mutation")

    def rollback(self, prepared: object) -> object:
        raise AssertionError("verification requested rollback")

    def cleanup(self, prepared: object, terminal_evidence_ref: str) -> object:
        raise AssertionError("verification requested cleanup")


class _InterruptedExecution(_ReadOnlyExecution):
    def observe(self) -> object:
        self._calls.append(f"observe:{self._resource_id}")
        raise RuntimeError("interrupted")


class _InterruptAfterAppendStore(RunStore):
    def __init__(self, root: Path, boundary: int) -> None:
        super().__init__(root, resource_registry=built_in_resource_registry())
        self._boundary = boundary
        self._append_count = 0

    def compare_and_append(
        self,
        lease: RevisionLease,
        expected_revision: int,
        expected_digest: str,
        payload: bytes,
        intent: AppendIntent,
    ) -> StoredRevision:
        result = super().compare_and_append(
            lease,
            expected_revision,
            expected_digest,
            payload,
            intent,
        )
        self._append_count += 1
        if self._append_count == self._boundary:
            raise RuntimeError("interrupted after durable append")
        return result


def _runtime() -> FiniteRuntimeValues:
    return FiniteRuntimeValues(
        uuid7_values=(
            "019950f8-4c00-7000-8000-000000000601",
            "019950f8-4c00-7000-8000-000000000201",
            "019950f8-4c00-7000-8000-000000000101",
        ),
        utc_instants=(
            "2026-09-20T05:00:00Z",
            "2026-09-20T05:00:01Z",
            "2026-09-20T05:00:02Z",
            "2026-09-20T05:00:03Z",
            "2026-09-20T05:00:04Z",
            "2026-09-20T05:00:05Z",
            "2026-09-20T05:00:06Z",
            "2026-09-20T05:00:07Z",
        ),
        ownership_tokens=(b"read-only-verification-token",),
    )


def _binding(resource_id: str) -> CanonicalVerificationBinding:
    desired = canonical_document_bytes(
        {
            "kind": "KodiSmartPlaylistDesiredState",
            "resource_id": resource_id,
            "schema_version": 1,
        }
    )
    policy = canonical_document_bytes(
        {
            "assessor": "KodiSmartPlaylist",
            "schema_version": 1,
        }
    )
    return CanonicalVerificationBinding.create(
        desired_state_codec="application/vnd.coreelec.kodi-smart-playlist-state+json;v=1",
        desired_state=desired,
        verification_policy_codec=(
            "application/vnd.coreelec.kodi-smart-playlist-verification+json;v=1"
        ),
        verification_policy=policy,
    )


def test_verification_is_dependency_ordered_canonical_and_restartable(
    tmp_path: object,
) -> None:
    from pathlib import Path

    calls: list[str] = []
    registry = built_in_resource_registry()
    store = RunStore(Path(str(tmp_path)) / "runs", resource_registry=registry)
    verification = CanonicalVerificationRuns(store, registry, _runtime())
    dependent = VerificationResource(
        "dependent",
        "KodiSmartPlaylist",
        ("special://profile/playlists/video/dependent.xsp",),
        ("base",),
        _binding("dependent"),
        _ReadOnlyExecution("dependent", DesiredRelation.DIVERGENT, calls),
    )
    base = VerificationResource(
        "base",
        "KodiSmartPlaylist",
        ("special://profile/playlists/video/base.xsp",),
        (),
        _binding("base"),
        _ReadOnlyExecution("base", DesiredRelation.SATISFIED, calls),
    )

    result = verification.verify(
        VerificationRequest(
            DeviceId("device.test"),
            (dependent, base),
            "sha256:" + "1" * 64,
            "boot",
        )
    )

    assert result.relation is VerificationRelation.DIVERGENT
    assert result.run_report.status.value == "failed_partial"
    assert calls == [
        "observe:base",
        "assess:base",
        "observe:dependent",
        "assess:dependent",
    ]
    assert store.find_active_by_device(DeviceId("device.test")) == ()
    assert verification.report(result.run_id) == result
    assert verification.restart(result.run_id, (dependent, base)) == result


def test_verification_reports_unverifiable_and_rejects_missing_dependencies(
    tmp_path: object,
) -> None:
    from pathlib import Path

    calls: list[str] = []
    registry = built_in_resource_registry()
    verification = CanonicalVerificationRuns(
        RunStore(Path(str(tmp_path)) / "runs", resource_registry=registry),
        registry,
        _runtime(),
    )
    resource = VerificationResource(
        "dependent",
        "KodiSmartPlaylist",
        ("special://profile/playlists/video/dependent.xsp",),
        ("missing",),
        _binding("dependent"),
        _ReadOnlyExecution("dependent", DesiredRelation.UNVERIFIABLE, calls),
    )

    with pytest.raises(ValueError, match="omits a Resource dependency"):
        verification.verify(
            VerificationRequest(
                DeviceId("device.test"),
                (resource,),
                "sha256:" + "1" * 64,
                "boot",
            )
        )

    standalone = VerificationResource(
        "resource",
        "KodiSmartPlaylist",
        ("special://profile/playlists/video/resource.xsp",),
        (),
        _binding("resource"),
        _ReadOnlyExecution("resource", DesiredRelation.UNVERIFIABLE, calls),
    )
    result = verification.verify(
        VerificationRequest(
            DeviceId("device.test"),
            (standalone,),
            "sha256:" + "1" * 64,
            "boot",
        )
    )
    assert result.relation is VerificationRelation.UNVERIFIABLE


def test_restart_continues_after_durable_resource_checkpoint_without_reobservation(
    tmp_path: object,
) -> None:
    from pathlib import Path

    calls: list[str] = []
    registry = built_in_resource_registry()
    store = RunStore(Path(str(tmp_path)) / "runs", resource_registry=registry)
    verification = CanonicalVerificationRuns(store, registry, _runtime())
    base = VerificationResource(
        "base",
        "KodiSmartPlaylist",
        ("special://profile/playlists/video/base.xsp",),
        (),
        _binding("base"),
        _ReadOnlyExecution("base", DesiredRelation.SATISFIED, calls),
    )
    dependent = VerificationResource(
        "dependent",
        "KodiSmartPlaylist",
        ("special://profile/playlists/video/dependent.xsp",),
        ("base",),
        _binding("dependent"),
        _InterruptedExecution("dependent", DesiredRelation.DIVERGENT, calls),
    )

    with pytest.raises(RuntimeError, match="interrupted"):
        verification.verify(
            VerificationRequest(
                DeviceId("device.test"),
                (dependent, base),
                "sha256:" + "1" * 64,
                "boot",
            )
        )

    run_id = RunId("019950f8-4c00-7000-8000-000000000601")
    assert verification.report(run_id).resources == (
        ResourceVerification("base", VerificationRelation.CONVERGED),
        ResourceVerification("dependent", VerificationRelation.UNVERIFIABLE),
    )

    resumed_calls: list[str] = []
    resumed = verification.restart(
        run_id,
        (
            VerificationResource(
                "dependent",
                "KodiSmartPlaylist",
                ("special://profile/playlists/video/dependent.xsp",),
                ("base",),
                _binding("dependent"),
                _ReadOnlyExecution(
                    "dependent", DesiredRelation.DIVERGENT, resumed_calls
                ),
            ),
            VerificationResource(
                "base",
                "KodiSmartPlaylist",
                ("special://profile/playlists/video/base.xsp",),
                (),
                _binding("base"),
                _InterruptedExecution("base", DesiredRelation.SATISFIED, resumed_calls),
            ),
        ),
    )

    assert resumed.relation is VerificationRelation.DIVERGENT
    assert calls == ["observe:base", "assess:base", "observe:dependent"]
    assert resumed_calls == ["observe:dependent", "assess:dependent"]


@pytest.mark.parametrize("boundary", range(1, 5))
def test_restart_is_idempotent_after_every_durable_verification_boundary(
    tmp_path: Path,
    boundary: int,
) -> None:
    calls: list[str] = []
    registry = built_in_resource_registry()
    store = _InterruptAfterAppendStore(tmp_path / "runs", boundary)
    resources = (
        VerificationResource(
            "dependent",
            "KodiSmartPlaylist",
            ("special://profile/playlists/video/dependent.xsp",),
            ("base",),
            _binding("dependent"),
            _ReadOnlyExecution("dependent", DesiredRelation.DIVERGENT, calls),
        ),
        VerificationResource(
            "base",
            "KodiSmartPlaylist",
            ("special://profile/playlists/video/base.xsp",),
            (),
            _binding("base"),
            _ReadOnlyExecution("base", DesiredRelation.SATISFIED, calls),
        ),
    )

    with pytest.raises(RuntimeError, match="interrupted after durable append"):
        CanonicalVerificationRuns(store, registry, _runtime()).verify(
            VerificationRequest(
                DeviceId("device.test"),
                resources,
                "sha256:" + "1" * 64,
                "boot",
            )
        )

    resumed = CanonicalVerificationRuns(
        store,
        registry,
        FiniteRuntimeValues(
            utc_instants=(
                "2026-09-20T05:01:00Z",
                "2026-09-20T05:01:03Z",
                "2026-09-20T05:01:04Z",
                "2026-09-20T05:01:08Z",
                "2026-09-20T05:01:09Z",
                "2026-09-20T05:01:15Z",
                "2026-09-20T05:01:16Z",
            ),
        ),
    ).restart(
        RunId("019950f8-4c00-7000-8000-000000000601"),
        resources,
    )

    assert resumed.relation is VerificationRelation.DIVERGENT
    assert calls == [
        "observe:base",
        "assess:base",
        "observe:dependent",
        "assess:dependent",
    ]


def test_restart_rejects_changed_desired_state_or_assessor_policy(
    tmp_path: Path,
) -> None:
    calls: list[str] = []
    registry = built_in_resource_registry()
    store = RunStore(tmp_path / "runs", resource_registry=registry)
    resource = VerificationResource(
        "resource",
        "KodiSmartPlaylist",
        ("special://profile/playlists/video/resource.xsp",),
        (),
        _binding("resource"),
        _InterruptedExecution("resource", DesiredRelation.SATISFIED, calls),
    )
    verification = CanonicalVerificationRuns(store, registry, _runtime())
    with pytest.raises(RuntimeError, match="interrupted"):
        verification.verify(
            VerificationRequest(
                DeviceId("device.test"),
                (resource,),
                "sha256:" + "1" * 64,
                "boot",
            )
        )

    changed = CanonicalVerificationBinding.create(
        desired_state_codec=resource.binding.desired_state_codec,
        desired_state=canonical_document_bytes(
            {"kind": "changed", "resource_id": "resource", "schema_version": 1}
        ),
        verification_policy_codec=resource.binding.verification_policy_codec,
        verification_policy=canonical_document_bytes(
            {"assessor": "changed", "schema_version": 1}
        ),
    )
    with pytest.raises(ValueError, match="scope binding changed"):
        verification.restart(
            RunId("019950f8-4c00-7000-8000-000000000601"),
            (
                VerificationResource(
                    resource.resource_id,
                    resource.resource_type,
                    resource.state_addresses,
                    resource.requires,
                    changed,
                    _ReadOnlyExecution("resource", DesiredRelation.SATISFIED, calls),
                ),
            ),
        )
    assert calls == ["observe:resource"]
