from pathlib import Path

from coreelec_reconciler.config.device import (
    SecretValue,
    resolve_device_session_parameters,
)
from coreelec_reconciler.config.load import load_configuration
from coreelec_reconciler.domain.configuration import (
    ResolvedDevice,
    SecretReference,
)
from coreelec_reconciler.domain.identifiers import DeviceId

FIXTURE_ROOT = Path(__file__).parents[2] / "fixtures" / "repository"


class Resolver:
    def __init__(self) -> None:
        self.references: list[SecretReference] = []

    def resolve(self, reference: SecretReference) -> SecretValue:
        self.references.append(reference)
        return SecretValue(b"sentinel-secret")


def test_load_retains_complete_secret_free_resolved_device() -> None:
    result = load_configuration(FIXTURE_ROOT, DeviceId("living-room.ugoos-am6b-plus"))

    assert result.diagnostics == ()
    assert result.configuration is not None
    device = result.configuration.device
    assert isinstance(device, ResolvedDevice)
    assert device.id == DeviceId("living-room.ugoos-am6b-plus")
    assert device.endpoint.host == "coreelec-living-room.example.test"
    assert device.endpoint.port == 22
    assert device.ssh_username == "root"
    assert device.host_key_reference == "ssh-host-key.living-room.ugoos-am6b-plus"
    assert device.credential_reference == SecretReference(
        "controller.environment", "coreelec.admin-private-key"
    )
    assert "sentinel-secret" not in repr(device)


def test_secret_is_resolved_only_by_explicit_composition_seam_and_redacted() -> None:
    result = load_configuration(FIXTURE_ROOT, DeviceId("living-room.ugoos-am6b-plus"))
    assert result.configuration is not None
    assert result.configuration.device is not None
    resolver = Resolver()

    parameters = resolve_device_session_parameters(
        result.configuration.device, resolver
    )

    assert resolver.references == [
        SecretReference("controller.environment", "coreelec.admin-private-key")
    ]
    assert parameters.credential.value == b"sentinel-secret"
    assert "sentinel-secret" not in repr(parameters)
