from dataclasses import dataclass

import pytest

from coreelec_reconciler.domain.execution import NormalizedResourceState, Presence
from coreelec_reconciler.domain.identifiers import DeviceId
from coreelec_reconciler.domain.planning import DesiredRelation
from coreelec_reconciler.execution.run_store import RunStore
from coreelec_reconciler.execution.runtime import FiniteRuntimeValues
from coreelec_reconciler.execution.verification import (
    CanonicalVerificationRuns,
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
        _ReadOnlyExecution("dependent", DesiredRelation.DIVERGENT, calls),
    )
    base = VerificationResource(
        "base",
        "KodiSmartPlaylist",
        ("special://profile/playlists/video/base.xsp",),
        (),
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
