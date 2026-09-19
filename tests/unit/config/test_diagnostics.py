from pathlib import Path

import pytest

from coreelec_reconciler.config.load import load_configuration
from coreelec_reconciler.config.yaml_loader import parse_restricted_yaml
from coreelec_reconciler.domain.identifiers import DeviceId, SelectorId


def _write(root: Path, relative: str, content: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


@pytest.mark.parametrize(
    ("yaml_text", "code"),
    [
        ("kind: Profile\nkind: Profile\nschema_version: 1\n", "yaml.duplicate-key"),
        (
            "kind: Profile\nschema_version: 1\n---\nkind: Profile\n",
            "yaml.multiple-documents",
        ),
        (
            "kind: Profile\nschema_version: 1\nid: &id room.one\n",
            "yaml.unsafe-anchor",
        ),
        (
            "kind: Profile\nschema_version: 1\nid: !thing room.one\n",
            "yaml.unsafe-tag",
        ),
        (
            "kind: Profile\nschema_version: 1\nbase: &base {id: room.one}\n"
            "copy: {<<: *base}\n",
            "yaml.unsafe-anchor",
        ),
        ("kind: Profile\nschema_version: 1\n1: value\n", "yaml.non-string-key"),
    ],
)
def test_restricted_yaml_rejects_unsafe_forms(
    tmp_path: Path, yaml_text: str, code: str
) -> None:
    _write(tmp_path, "profiles/unsafe.yaml", yaml_text)

    result = load_configuration(tmp_path, DeviceId("device.missing"))

    assert code in {diagnostic.code for diagnostic in result.diagnostics}
    diagnostic = next(item for item in result.diagnostics if item.code == code)
    assert diagnostic.source.endswith("profiles/unsafe.yaml")
    assert diagnostic.line >= 1
    assert diagnostic.column >= 1


def test_unknown_invalid_and_unresolved_inputs_have_stable_diagnostics(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path,
        "profiles/platform.yaml",
        """kind: Profile
schema_version: 99
id: platform.valid
layer: platform
resoruces: []
""",
    )
    _write(
        tmp_path,
        "inventory/devices.yaml",
        """kind: DeviceInventory
schema_version: 1
devices:
  - id: living-room.device
    endpoint: {host: example.test, port: 22}
    ssh:
      username: root
      host_key: {policy: pinned, reference: host-key.device}
      credential:
        type: secret
        provider: controller.environment
        key: missing-key
    profiles: {platform: platform.missing}
""",
    )
    _write(
        tmp_path,
        "secret-providers/providers.yaml",
        """kind: SecretProviderCatalog
schema_version: 1
providers:
  - id: controller.environment
    type: environment
    keys: {}
""",
    )

    result = load_configuration(tmp_path, DeviceId("living-room.device"))

    assert {diagnostic.code for diagnostic in result.diagnostics} >= {
        "schema.unsupported-version",
        "schema.unknown-field",
        "reference.profile-unresolved",
        "reference.secret-unresolved",
    }
    assert all(
        "missing-key" not in diagnostic.message for diagnostic in result.diagnostics
    )


def test_timestamp_like_scalar_remains_a_string() -> None:
    parsed = parse_restricted_yaml(
        "kind: Example\nschema_version: 1\nvalue: 2026-09-18\n",
        "profiles/example.yaml",
    )

    assert parsed.diagnostics == ()
    assert parsed.value is not None
    assert parsed.value["value"] == "2026-09-18"
    assert type(parsed.value["value"]) is str


def test_duplicate_resource_id_and_scalar_coercion_fail(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "profiles/platform.yaml",
        """kind: Profile
schema_version: 1
id: platform.one
layer: platform
resources:
  - &not-used
    id: skin.playlist.one
    type: KodiSmartPlaylist
    management: enforce
    desired: present
    selectors: []
    requires: []
    intent: {}
""",
    )
    anchored = load_configuration(tmp_path, DeviceId("device.missing"))
    assert "yaml.unsafe-anchor" in {
        diagnostic.code for diagnostic in anchored.diagnostics
    }

    _write(
        tmp_path,
        "profiles/platform.yaml",
        """kind: Profile
schema_version: 1
id: platform.one
layer: platform
resources:
  - id: skin.playlist.one
    type: KodiSmartPlaylist
    management: enforce
    desired: present
    selectors: []
    requires: []
    intent: {}
  - id: skin.playlist.one
    type: KodiSmartPlaylist
    management: enforce
    desired: present
    selectors: []
    requires: []
    intent: {}
""",
    )
    _write(
        tmp_path,
        "inventory/devices.yaml",
        """kind: DeviceInventory
schema_version: 1
devices:
  - id: device.one
    endpoint: {host: example.test, port: "22"}
    ssh:
      username: root
      host_key: {policy: pinned, reference: host-key.device}
      credential: literal-secret
    profiles: {platform: platform.one}
""",
    )
    result = load_configuration(tmp_path, DeviceId("device.one"))
    assert {diagnostic.code for diagnostic in result.diagnostics} >= {
        "resource.duplicate-id",
        "schema.invalid",
        "secret.invalid-reference",
    }


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("limit: 50", 'limit: "bad"'),
        ("display_name: New Shows", "display_name: Unapproved"),
        ("limit: 50", "limit: -1"),
        ("value: 0", "value: arbitrary"),
    ],
)
def test_invalid_layer_value_is_not_repaired_by_later_override(
    tmp_path: Path,
    old: str,
    new: str,
) -> None:
    fixture = Path(__file__).parents[2] / "fixtures" / "repository"
    for source in fixture.rglob("*.yaml"):
        _write(tmp_path, str(source.relative_to(fixture)), source.read_text())
    platform = tmp_path / "profiles/platform/coreelec-21-amlogic-ng.yaml"
    platform.write_text(
        platform.read_text().replace(old, new, 1),
        encoding="utf-8",
    )

    result = load_configuration(
        tmp_path,
        DeviceId("living-room.ugoos-am6b-plus"),
    )

    assert result.configuration is None
    assert "schema.invalid" in {diagnostic.code for diagnostic in result.diagnostics}


@pytest.mark.parametrize(
    ("old", "new"),
    [
        (
            "order:\n          by: dateadded\n          direction: descending",
            "order:\n          by: dateadded",
        ),
        ('file:\n        mode: "0644"', "file: {}"),
    ],
)
def test_incomplete_composed_playlist_returns_diagnostic(
    tmp_path: Path,
    old: str,
    new: str,
) -> None:
    fixture = Path(__file__).parents[2] / "fixtures" / "repository"
    for source in fixture.rglob("*.yaml"):
        _write(tmp_path, str(source.relative_to(fixture)), source.read_text())
    platform = tmp_path / "profiles/platform/coreelec-21-amlogic-ng.yaml"
    platform.write_text(
        platform.read_text().replace(old, new),
        encoding="utf-8",
    )

    result = load_configuration(
        tmp_path,
        DeviceId("living-room.ugoos-am6b-plus"),
    )

    assert result.configuration is None
    assert "schema.invalid" in {diagnostic.code for diagnostic in result.diagnostics}


def test_unknown_resource_type_in_unselected_profile_fails(tmp_path: Path) -> None:
    fixture = Path(__file__).parents[2] / "fixtures" / "repository"
    for source in fixture.rglob("*.yaml"):
        _write(tmp_path, str(source.relative_to(fixture)), source.read_text())
    _write(
        tmp_path,
        "profiles/room/unused.yaml",
        """kind: Profile
schema_version: 1
id: room.unused
layer: room
resources:
  - id: resource.unknown
    type: MadeUpType
    management: enforce
    desired: present
    selectors: []
    requires: []
    intent: {}
""",
    )

    result = load_configuration(
        tmp_path,
        DeviceId("living-room.ugoos-am6b-plus"),
    )

    assert result.configuration is None
    assert "resource.unknown-type" in {
        diagnostic.code for diagnostic in result.diagnostics
    }


def test_artifact_dependencies_are_rejected_until_resolution_is_implemented(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path,
        "artifacts/catalog.yaml",
        """kind: ArtifactCatalog
schema_version: 1
artifacts:
  - id: artifact.kodi.example
    kind: kodi-addon
    version: 1.0.0
    origin:
      adapter: github-release-asset
      project: example/project
      tag: v1.0.0
      commit: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
      release_id: 1
      asset_id: 2
      retrieval_url: https://example.test/example.zip
      mutable: false
      sha256: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
    distribution:
      relation: direct-origin-bytes
      owner: upstream
      release_id: 1
      asset_id: 2
      asset: example-1.0.0.zip
      immutable_release: true
      sha256: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
    release: {channel: stable}
    platforms: [coreelec-21-amlogic-ng]
    dependencies:
      - id: artifact.kodi.dependency
        minimum_version: 1.0.0
""",
    )

    result = load_configuration(tmp_path, DeviceId("device.missing"))

    assert result.configuration is None
    assert "schema.invalid" in {diagnostic.code for diagnostic in result.diagnostics}


def test_duplicates_conflicts_and_graph_failures_are_aggregated(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path,
        "inventory/devices.yaml",
        """kind: DeviceInventory
schema_version: 1
devices:
  - id: room.device
    endpoint: {host: example.test, port: 22}
    ssh:
      username: root
      host_key: {policy: pinned, reference: host-key.device}
      credential: {type: secret, provider: controller.environment, key: ssh-key}
    profiles: {platform: platform.one}
""",
    )
    _write(
        tmp_path,
        "secret-providers/providers.yaml",
        """kind: SecretProviderCatalog
schema_version: 1
providers:
  - id: controller.environment
    type: environment
    keys: {ssh-key: {variable: SSH_KEY}}
""",
    )
    _write(
        tmp_path,
        "profiles/platform.yaml",
        """kind: Profile
schema_version: 1
id: platform.one
layer: platform
resources:
  - id: skin.playlist.one
    type: KodiSmartPlaylist
    management: enforce
    desired: present
    selectors: [selector.skin]
    requires: [skin.playlist.two, skin.playlist.missing]
    intent: &intent
      playlist:
        id: playlist.video.new-shows
        media_type: tvshows
        display_name: New Shows
        match: all
        limit: 50
        rules: [{field: playcount, operator: is, value: 0}]
        order: {by: dateadded, direction: descending}
      file: {mode: "0644"}
  - id: skin.playlist.two
    type: KodiSmartPlaylist
    management: observe-only
    desired: absent
    selectors: [selector.other]
    requires: [skin.playlist.one]
    intent:
      playlist: {id: playlist.video.new-shows, media_type: tvshows}
  - id: skin.playlist.two
    type: KodiSmartPlaylist
    management: enforce
    desired: present
    selectors: []
    requires: []
    intent: *intent
""",
    )

    result = load_configuration(tmp_path, DeviceId("room.device"))

    codes = {diagnostic.code for diagnostic in result.diagnostics}
    assert "yaml.unsafe-anchor" in codes


def test_type_conflict_dependency_cycle_ownership_and_selector_fail_closed(
    tmp_path: Path,
) -> None:
    fixture = Path(__file__).parents[2] / "fixtures" / "repository"
    for source in fixture.rglob("*.yaml"):
        _write(tmp_path, str(source.relative_to(fixture)), source.read_text())
    platform = tmp_path / "profiles/platform/coreelec-21-amlogic-ng.yaml"
    platform.write_text(
        platform.read_text().replace(
            "    requires: []",
            "    requires: [skin.playlist.other, skin.playlist.missing]",
            1,
        )
        + """
  - id: skin.playlist.other
    type: KodiSmartPlaylist
    management: observe-only
    desired: absent
    selectors: [selector.other]
    requires: [skin.playlist.new-shows]
    intent:
      playlist: {id: playlist.video.new-shows, media_type: tvshows}
""",
        encoding="utf-8",
    )
    device = tmp_path / "profiles/device/living-room-ugoos.yaml"
    device.write_text(
        device.read_text().replace(
            "    requires: []",
            "    requires: [skin.playlist.other, skin.playlist.missing]",
        )
        + """
  - id: resource.unknown
    type: UnknownResourceType
    management: enforce
    desired: present
    selectors: []
    requires: []
    intent: {}
""",
        encoding="utf-8",
    )
    room = tmp_path / "profiles/room/living-room.yaml"
    room.write_text(
        room.read_text().replace(
            "type: KodiSmartPlaylist", "type: UnknownResourceType"
        ),
        encoding="utf-8",
    )

    result = load_configuration(
        tmp_path,
        DeviceId("living-room.ugoos-am6b-plus"),
        (SelectorId("selector.missing"),),
    )

    assert {diagnostic.code for diagnostic in result.diagnostics} >= {
        "resource.unknown-type",
        "composition.type-conflict",
        "ownership.conflict",
        "dependency.unresolved",
        "dependency.cycle",
        "selector.unresolved",
    }


def _write_dependency_repository(root: Path, order: tuple[str, ...]) -> None:
    _write(
        root,
        "inventory/devices.yaml",
        """kind: DeviceInventory
schema_version: 1
devices:
  - id: device.dependencies
    endpoint: {host: example.test, port: 22}
    ssh:
      username: root
      host_key: {policy: pinned, reference: host-key.dependencies}
      credential: {type: secret, provider: controller.environment, key: ssh.key}
    profiles: {platform: platform.dependencies}
""",
    )
    _write(
        root,
        "secret-providers/providers.yaml",
        """kind: SecretProviderCatalog
schema_version: 1
providers:
  - id: controller.environment
    type: environment
    keys: {ssh.key: {variable: SSH_KEY}}
""",
    )
    dependencies = {
        "skin.playlist.a": "skin.playlist.b",
        "skin.playlist.b": "skin.playlist.c",
        "skin.playlist.c": "skin.playlist.a",
        "skin.playlist.d": "skin.playlist.missing",
    }
    resources = "\n".join(
        f"""  - id: {resource_id}
    type: KodiSmartPlaylist
    management: enforce
    desired: absent
    selectors: []
    requires: [{dependencies[resource_id]}]
    intent:
      playlist: {{id: playlist.video.new-shows, media_type: tvshows}}"""
        for resource_id in order
    )
    _write(
        root,
        "profiles/platform.yaml",
        f"""kind: Profile
schema_version: 1
id: platform.dependencies
layer: platform
resources:
{resources}
""",
    )


def test_dependency_failures_have_provenance_and_deterministic_cycle_output(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    _write_dependency_repository(
        first,
        (
            "skin.playlist.a",
            "skin.playlist.b",
            "skin.playlist.c",
            "skin.playlist.d",
        ),
    )
    _write_dependency_repository(
        second,
        (
            "skin.playlist.d",
            "skin.playlist.c",
            "skin.playlist.a",
            "skin.playlist.b",
        ),
    )

    first_result = load_configuration(first, DeviceId("device.dependencies"))
    second_result = load_configuration(second, DeviceId("device.dependencies"))
    first_dependencies = tuple(
        (
            diagnostic.code,
            diagnostic.source,
            diagnostic.path,
            diagnostic.subject_id,
            diagnostic.message,
        )
        for diagnostic in first_result.diagnostics
        if diagnostic.code.startswith("dependency.")
    )
    second_dependencies = tuple(
        (
            diagnostic.code,
            diagnostic.source,
            diagnostic.path,
            diagnostic.subject_id,
            diagnostic.message,
        )
        for diagnostic in second_result.diagnostics
        if diagnostic.code.startswith("dependency.")
    )

    assert first_result.configuration is None
    assert second_result.configuration is None
    assert first_dependencies == second_dependencies
    assert first_dependencies == (
        (
            "dependency.cycle",
            "profiles/platform.yaml",
            ("resources", "skin.playlist.a", "requires"),
            "skin.playlist.a",
            "Resource dependency cycle includes: skin.playlist.a, "
            "skin.playlist.b, skin.playlist.c.",
        ),
        (
            "dependency.unresolved",
            "profiles/platform.yaml",
            ("resources", "skin.playlist.d", "requires", "skin.playlist.missing"),
            "skin.playlist.d",
            "Resource dependency skin.playlist.missing is not declared.",
        ),
    )
