import pytest

from coreelec_reconciler.domain.execution import MutationDisposition
from tests.fakes.runtime import FakeManagedFiles


@pytest.mark.parametrize(
    "primitive",
    ["stage_write", "chmod", "atomic_replace", "remove", "restore", "cleanup"],
)
@pytest.mark.parametrize(
    "disposition",
    [
        MutationDisposition.APPLIED,
        MutationDisposition.DEFINITELY_NOT_APPLIED,
        MutationDisposition.AMBIGUOUS,
    ],
)
def test_fake_exposes_every_primitive_disposition(
    primitive: str, disposition: MutationDisposition
) -> None:
    device = FakeManagedFiles()
    device.fault(primitive, disposition)
    observed, _ = device.scripted_outcome(primitive)
    assert observed is disposition


@pytest.mark.parametrize(
    "primitive",
    ["stage_write", "chmod", "atomic_replace", "remove", "restore", "cleanup"],
)
@pytest.mark.parametrize("applied", [False, True])
def test_every_primitive_has_both_lost_ack_twins(primitive: str, applied: bool) -> None:
    device = FakeManagedFiles()
    device.lost_ack(primitive, applied=applied)

    assert device.scripted_outcome(primitive) == (
        MutationDisposition.AMBIGUOUS,
        applied,
    )
