"""Repository discovery, authored validation, and fixed Profile composition."""

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from coreelec_reconciler.config.composition import (
    ComposedResource,
    ProfileDocument,
    compose_profiles,
)
from coreelec_reconciler.config.input_models import (
    ArtifactCatalogInput,
    DeviceInventoryInput,
    ProfileInput,
    SecretProviderCatalogInput,
)
from coreelec_reconciler.config.resource_types.builtins import (
    authored_fragment_parser,
)
from coreelec_reconciler.config.yaml_loader import parse_restricted_yaml
from coreelec_reconciler.domain.configuration import (
    Artifact,
    ConfigurationLoadResult,
    DesiredPresence,
    DeviceEndpoint,
    ManagementMode,
    ResolvedConfiguration,
    ResolvedDevice,
    Resource,
    SecretReference,
)
from coreelec_reconciler.domain.diagnostics import Diagnostic
from coreelec_reconciler.domain.identifiers import (
    ArtifactId,
    DeviceId,
    ResourceId,
    SelectorId,
)
from coreelec_reconciler.resource_types.builtins import (
    built_in_resource_registry,
)
from coreelec_reconciler.resource_types.descriptor import IntentValidationError

_ID_PATTERN = re.compile(
    r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+$"
)
_ROOTS = ("inventory", "profiles", "artifacts", "secret-providers")
_SUPPORTED_KINDS = frozenset(
    {
        "DeviceInventory",
        "Profile",
        "ArtifactCatalog",
        "SecretProviderCatalog",
    }
)


@dataclass(frozen=True, slots=True)
class _Document:
    source: str
    model: (
        DeviceInventoryInput
        | ProfileInput
        | ArtifactCatalogInput
        | SecretProviderCatalogInput
    )


def _diagnostic(
    source: str,
    code: str,
    message: str,
    path: tuple[str | int, ...] = (),
    subject_id: str | None = None,
) -> Diagnostic:
    return Diagnostic(
        source=source or "repository",
        line=1,
        column=1,
        path=path,
        code=code,
        message=message,
        subject_id=subject_id,
    )


def _validation_diagnostics(source: str, error: ValidationError) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    for item in error.errors(include_url=False, include_input=False):
        error_type = str(item["type"])
        code = (
            "schema.unknown-field"
            if error_type == "extra_forbidden"
            else "schema.invalid"
        )
        location = tuple(item["loc"])
        if location[-1:] == ("credential",):
            code = "secret.invalid-reference"
        diagnostics.append(
            _diagnostic(
                source,
                code,
                str(item["msg"]),
                location,
            )
        )
    return diagnostics


def _discover(root: Path) -> tuple[list[_Document], list[Diagnostic]]:
    documents: list[_Document] = []
    diagnostics: list[Diagnostic] = []
    for root_name in _ROOTS:
        directory = root / root_name
        if not directory.exists():
            continue
        paths = {*directory.rglob("*.yaml"), *directory.rglob("*.yml")}
        for path in sorted(paths):
            source = path.relative_to(root).as_posix()
            try:
                content = path.read_text(encoding="utf-8")
            except OSError, UnicodeError:
                diagnostics.append(
                    _diagnostic(
                        source,
                        "yaml.read-failed",
                        "The authored document could not be read as UTF-8.",
                    )
                )
                continue
            parsed = parse_restricted_yaml(content, source)
            diagnostics.extend(parsed.diagnostics)
            if parsed.value is None:
                continue
            kind = parsed.value.get("kind")
            if not isinstance(kind, str) or kind not in _SUPPORTED_KINDS:
                diagnostics.append(
                    _diagnostic(
                        source,
                        "schema.unknown-kind",
                        "The document kind is not supported.",
                        ("kind",),
                    )
                )
                continue
            version = parsed.value.get("schema_version")
            if type(version) is not int:
                diagnostics.append(
                    _diagnostic(
                        source,
                        "schema.invalid-version",
                        "schema_version must be an integer.",
                        ("schema_version",),
                    )
                )
            elif version != 1:
                diagnostics.append(
                    _diagnostic(
                        source,
                        "schema.unsupported-version",
                        "schema_version 1 is the only supported version.",
                        ("schema_version",),
                    )
                )
            model: (
                DeviceInventoryInput
                | ProfileInput
                | ArtifactCatalogInput
                | SecretProviderCatalogInput
            )
            try:
                if kind == "DeviceInventory":
                    model = DeviceInventoryInput.model_validate(parsed.value)
                elif kind == "Profile":
                    model = ProfileInput.model_validate(parsed.value)
                elif kind == "ArtifactCatalog":
                    model = ArtifactCatalogInput.model_validate(parsed.value)
                else:
                    model = SecretProviderCatalogInput.model_validate(parsed.value)
            except ValidationError as error:
                diagnostics.extend(_validation_diagnostics(source, error))
                continue
            if model.schema_version != 1:
                continue
            if isinstance(model, ProfileInput):
                fragment_valid = True
                for resource in model.resources:
                    parser = authored_fragment_parser(resource.type)
                    if parser is None:
                        continue
                    try:
                        parser(resource.intent)
                    except ValidationError as error:
                        diagnostics.extend(_validation_diagnostics(source, error))
                        fragment_valid = False
                if not fragment_valid:
                    continue
            documents.append(_Document(source=source, model=model))
    return documents, diagnostics


def _id_diagnostic(source: str, value: str, path: tuple[str | int, ...]) -> Diagnostic:
    return _diagnostic(
        source,
        "id.invalid",
        "Logical IDs must use lowercase dot-separated segments.",
        path,
        value,
    )


def _validate_ids(documents: Iterable[_Document]) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    seen: dict[tuple[str, str], str] = {}

    def register(
        kind: str,
        value: str,
        source: str,
        path: tuple[str | int, ...],
    ) -> None:
        if not _ID_PATTERN.fullmatch(value):
            diagnostics.append(_id_diagnostic(source, value, path))
        key = (kind, value)
        if key in seen:
            diagnostics.append(
                _diagnostic(
                    source,
                    "id.duplicate",
                    f"Duplicate {kind} ID {value}.",
                    path,
                    value,
                )
            )
        else:
            seen[key] = source

    for document in documents:
        model = document.model
        if isinstance(model, DeviceInventoryInput):
            for index, device in enumerate(model.devices):
                register("Device", device.id, document.source, ("devices", index, "id"))
        elif isinstance(model, ProfileInput):
            register("Profile", model.id, document.source, ("id",))
            resource_ids: set[str] = set()
            for index, resource in enumerate(model.resources):
                if resource.id in resource_ids:
                    diagnostics.append(
                        _diagnostic(
                            document.source,
                            "resource.duplicate-id",
                            f"Resource ID {resource.id} appears twice in one Profile.",
                            ("resources", index, "id"),
                            resource.id,
                        )
                    )
                resource_ids.add(resource.id)
                if not _ID_PATTERN.fullmatch(resource.id):
                    diagnostics.append(
                        _id_diagnostic(
                            document.source,
                            resource.id,
                            ("resources", index, "id"),
                        )
                    )
                for selector_index, selector in enumerate(resource.selectors):
                    if not _ID_PATTERN.fullmatch(selector):
                        diagnostics.append(
                            _id_diagnostic(
                                document.source,
                                selector,
                                ("resources", index, "selectors", selector_index),
                            )
                        )
        elif isinstance(model, ArtifactCatalogInput):
            for index, artifact in enumerate(model.artifacts):
                register(
                    "Artifact",
                    artifact.id,
                    document.source,
                    ("artifacts", index, "id"),
                )
        else:
            for index, provider in enumerate(model.providers):
                register(
                    "SecretProvider",
                    provider.id,
                    document.source,
                    ("providers", index, "id"),
                )
    return diagnostics


def _validate_resource_types(
    documents: Iterable[_Document],
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    registry = built_in_resource_registry()
    for document in documents:
        if not isinstance(document.model, ProfileInput):
            continue
        for resource in document.model.resources:
            if registry.descriptor(resource.type) is None:
                diagnostics.append(
                    _diagnostic(
                        document.source,
                        "resource.unknown-type",
                        f"Resource type {resource.type} is not supported.",
                        ("resources", resource.id, "type"),
                        resource.id,
                    )
                )
    return diagnostics


def _domain_resource(
    composed: ComposedResource,
) -> tuple[Resource | None, list[Diagnostic]]:
    value = composed.value
    resource_id = str(value["id"])
    type_code = str(value["type"])
    descriptor = built_in_resource_registry().descriptor(type_code)
    if descriptor is None:
        return None, []
    desired = DesiredPresence(str(value["desired"]))
    intent_value = value["intent"]
    if not isinstance(intent_value, Mapping):
        raise TypeError("Validated Resource Intent was not retained")
    try:
        intent = descriptor.parse_intent(intent_value, desired)
        state_addresses = descriptor.state_addresses(intent)
    except IntentValidationError as error:
        return None, [
            _diagnostic(
                composed.source,
                "schema.invalid",
                error.safe_message,
                error.path,
                resource_id,
            )
        ]
    except ValueError:
        return None, [
            _diagnostic(
                composed.source,
                "resource.unsupported-identity",
                "The Resource identity is not supported.",
                ("resources", resource_id, "intent"),
                resource_id,
            )
        ]
    selectors = value["selectors"]
    requires = value["requires"]
    if not isinstance(selectors, list) or not isinstance(requires, list):
        raise TypeError("Validated Resource lists were not retained")
    return (
        Resource(
            id=ResourceId(resource_id),
            type=type_code,
            management=ManagementMode(str(value["management"])),
            desired=desired,
            selectors=tuple(SelectorId(str(item)) for item in selectors),
            requires=tuple(ResourceId(str(item)) for item in requires),
            intent=intent,
            origins=tuple(sorted(composed.origins.items())),
            state_addresses=state_addresses,
        ),
        [],
    )


def _dependency_order(
    resources: Mapping[str, Resource],
) -> tuple[tuple[ResourceId, ...], list[Diagnostic]]:
    diagnostics: list[Diagnostic] = []
    for resource_id in sorted(resources):
        resource = resources[resource_id]
        source = dict(resource.origins).get("requires", "repository")
        for required in sorted(resource.requires, key=lambda item: item.value):
            if required.value not in resources:
                diagnostics.append(
                    _diagnostic(
                        source,
                        "dependency.unresolved",
                        f"Resource dependency {required.value} is not declared.",
                        (
                            "resources",
                            resource_id,
                            "requires",
                            required.value,
                        ),
                        resource_id,
                    )
                )

    index = 0
    indices: dict[str, int] = {}
    low_links: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    components: list[tuple[str, ...]] = []

    def connect(resource_id: str) -> None:
        nonlocal index
        indices[resource_id] = index
        low_links[resource_id] = index
        index += 1
        stack.append(resource_id)
        on_stack.add(resource_id)
        dependencies = sorted(
            required.value
            for required in resources[resource_id].requires
            if required.value in resources
        )
        for dependency_id in dependencies:
            if dependency_id not in indices:
                connect(dependency_id)
                low_links[resource_id] = min(
                    low_links[resource_id],
                    low_links[dependency_id],
                )
            elif dependency_id in on_stack:
                low_links[resource_id] = min(
                    low_links[resource_id],
                    indices[dependency_id],
                )
        if low_links[resource_id] != indices[resource_id]:
            return
        component: list[str] = []
        while True:
            member = stack.pop()
            on_stack.remove(member)
            component.append(member)
            if member == resource_id:
                break
        components.append(tuple(sorted(component)))

    for resource_id in sorted(resources):
        if resource_id not in indices:
            connect(resource_id)

    for component in sorted(components):
        subject_id = component[0]
        self_cycle = any(
            dependency.value == subject_id
            for dependency in resources[subject_id].requires
        )
        if len(component) > 1 or self_cycle:
            source = dict(resources[subject_id].origins).get(
                "requires",
                "repository",
            )
            diagnostics.append(
                _diagnostic(
                    source,
                    "dependency.cycle",
                    "Resource dependency cycle includes: " + ", ".join(component) + ".",
                    ("resources", subject_id, "requires"),
                    subject_id,
                )
            )

    diagnostics.sort(
        key=lambda item: (
            item.code,
            item.subject_id or "",
            item.path,
            item.message,
        )
    )
    if diagnostics:
        return (), diagnostics

    visited: set[str] = set()
    order: list[ResourceId] = []

    def append_in_dependency_order(resource_id: str) -> None:
        if resource_id in visited:
            return
        visited.add(resource_id)
        for required in sorted(
            resources[resource_id].requires,
            key=lambda item: item.value,
        ):
            append_in_dependency_order(required.value)
        order.append(resources[resource_id].id)

    for resource_id in sorted(resources):
        append_in_dependency_order(resource_id)
    return tuple(order), diagnostics


def _select_resources(
    resources: Mapping[str, Resource],
    selectors: tuple[SelectorId, ...],
) -> tuple[dict[str, Resource], list[Diagnostic]]:
    if not selectors:
        return dict(resources), []
    selected = {
        resource_id
        for resource_id, resource in resources.items()
        if any(selector in resource.selectors for selector in selectors)
    }
    diagnostics: list[Diagnostic] = []
    known_selectors = {
        selector for resource in resources.values() for selector in resource.selectors
    }
    for selector in selectors:
        if selector not in known_selectors:
            diagnostics.append(
                _diagnostic(
                    "",
                    "selector.unresolved",
                    f"Selector {selector.value} does not match a Resource.",
                    ("selection", selector.value),
                    selector.value,
                )
            )
    pending = list(selected)
    while pending:
        resource_id = pending.pop()
        for dependency in resources[resource_id].requires:
            if dependency.value in resources and dependency.value not in selected:
                selected.add(dependency.value)
                pending.append(dependency.value)
    return {key: resources[key] for key in sorted(selected)}, diagnostics


def _ownership_diagnostics(resources: Iterable[Resource]) -> list[Diagnostic]:
    owners: dict[str, str] = {}
    diagnostics: list[Diagnostic] = []
    for resource in resources:
        for address in resource.state_addresses:
            previous = owners.get(address)
            if previous is not None and previous != resource.id.value:
                diagnostics.append(
                    _diagnostic(
                        "",
                        "ownership.conflict",
                        f"State Address {address} has more than one Resource owner.",
                        ("resources", resource.id.value, "state_addresses"),
                        resource.id.value,
                    )
                )
            else:
                owners[address] = resource.id.value
    return diagnostics


def _artifact_values(
    documents: Iterable[_Document],
) -> tuple[tuple[Artifact, ...], list[Diagnostic]]:
    artifacts: dict[str, Artifact] = {}
    diagnostics: list[Diagnostic] = []
    for document in documents:
        if not isinstance(document.model, ArtifactCatalogInput):
            continue
        for artifact_input in document.model.artifacts:
            for digest in (
                artifact_input.origin.sha256,
                artifact_input.distribution.sha256,
            ):
                if not re.fullmatch(r"[0-9a-f]{64}", digest):
                    diagnostics.append(
                        _diagnostic(
                            document.source,
                            "artifact.invalid-digest",
                            "Artifact SHA-256 values must be 64 lowercase "
                            "hex characters.",
                            ("artifacts", artifact_input.id),
                            artifact_input.id,
                        )
                    )
            if (
                artifact_input.distribution.relation == "direct-origin-bytes"
                and artifact_input.origin.sha256 != artifact_input.distribution.sha256
            ):
                diagnostics.append(
                    _diagnostic(
                        document.source,
                        "artifact.digest-conflict",
                        "Direct-origin Artifact digests must match.",
                        ("artifacts", artifact_input.id),
                        artifact_input.id,
                    )
                )
            artifacts[artifact_input.id] = Artifact(
                id=ArtifactId(artifact_input.id),
                kind=artifact_input.kind,
                version=artifact_input.version,
                origin_sha256=artifact_input.origin.sha256,
                distribution_sha256=artifact_input.distribution.sha256,
                platforms=tuple(artifact_input.platforms),
                dependencies=tuple(
                    ArtifactId(dependency.id)
                    for dependency in artifact_input.dependencies
                ),
            )
    for artifact in artifacts.values():
        for dependency in artifact.dependencies:
            if dependency.value not in artifacts:
                diagnostics.append(
                    _diagnostic(
                        "",
                        "reference.artifact-unresolved",
                        f"Artifact dependency {dependency.value} is not declared.",
                        ("artifacts", artifact.id.value, "dependencies"),
                        artifact.id.value,
                    )
                )
    state: dict[str, int] = {}

    def visit(artifact_id: str) -> None:
        if state.get(artifact_id) == 2:
            return
        if state.get(artifact_id) == 1:
            diagnostics.append(
                _diagnostic(
                    "",
                    "artifact.dependency-cycle",
                    "Artifact dependencies must be acyclic.",
                    ("artifacts", artifact_id, "dependencies"),
                    artifact_id,
                )
            )
            return
        state[artifact_id] = 1
        for dependency in artifacts[artifact_id].dependencies:
            if dependency.value in artifacts:
                visit(dependency.value)
        state[artifact_id] = 2

    for artifact_id in sorted(artifacts):
        visit(artifact_id)
    return tuple(artifacts[key] for key in sorted(artifacts)), diagnostics


def load_configuration(
    repository_root: str | Path,
    device_id: DeviceId,
    selectors: tuple[SelectorId, ...] = (),
) -> ConfigurationLoadResult:
    root = Path(repository_root)
    documents, diagnostics = _discover(root)
    diagnostics.extend(_validate_ids(documents))
    diagnostics.extend(_validate_resource_types(documents))
    inventories = [
        document
        for document in documents
        if isinstance(document.model, DeviceInventoryInput)
    ]
    devices = [
        (document, device)
        for document in inventories
        for device in document.model.devices  # type: ignore[union-attr]
        if device.id == device_id.value
    ]
    if not devices:
        diagnostics.append(
            _diagnostic(
                "",
                "reference.device-unresolved",
                f"Device {device_id.value} is not declared.",
                ("device_id",),
                device_id.value,
            )
        )
        return ConfigurationLoadResult(None, tuple(diagnostics))
    inventory_document, device = devices[0]
    profiles_by_id = {
        document.model.id: document
        for document in documents
        if isinstance(document.model, ProfileInput)
    }
    profile_slots = (
        ("platform", device.profiles.platform),
        ("room", device.profiles.room),
        ("device", device.profiles.device),
    )
    selected_profile_ids = tuple(
        profile_id for _, profile_id in profile_slots if profile_id is not None
    )
    selected_profiles: list[_Document] = []
    for expected_layer, profile_id in profile_slots:
        if profile_id is None:
            continue
        profile = profiles_by_id.get(profile_id)
        if profile is None:
            diagnostics.append(
                _diagnostic(
                    inventory_document.source,
                    "reference.profile-unresolved",
                    f"Profile {profile_id} is not declared.",
                    ("devices", device.id, "profiles", expected_layer),
                    profile_id,
                )
            )
            continue
        if not isinstance(profile.model, ProfileInput):
            raise TypeError("Profile index contained a non-Profile document")
        if profile.model.layer != expected_layer:
            diagnostics.append(
                _diagnostic(
                    profile.source,
                    "composition.layer-mismatch",
                    f"Profile {profile_id} is not a {expected_layer} layer.",
                    ("layer",),
                    profile_id,
                )
            )
            continue
        selected_profiles.append(profile)
    provider_keys = {
        provider.id: frozenset(provider.keys)
        for document in documents
        if isinstance(document.model, SecretProviderCatalogInput)
        for provider in document.model.providers
    }
    secret = SecretReference(
        provider=device.ssh.credential.provider,
        key=device.ssh.credential.key,
    )
    if secret.provider not in provider_keys or secret.key not in provider_keys.get(
        secret.provider, frozenset()
    ):
        diagnostics.append(
            _diagnostic(
                inventory_document.source,
                "reference.secret-unresolved",
                "The typed secret reference is not declared by its provider.",
                ("devices", device.id, "ssh", "credential"),
                device.id,
            )
        )
    composition = compose_profiles(
        tuple(
            ProfileDocument(source=document.source, model=document.model)
            for document in selected_profiles
            if isinstance(document.model, ProfileInput)
        )
    )
    diagnostics.extend(composition.diagnostics)
    domain_resources: dict[str, Resource] = {}
    for resource_id, value in composition.resources.items():
        domain_resource, resource_diagnostics = _domain_resource(value)
        diagnostics.extend(resource_diagnostics)
        if domain_resource is not None:
            domain_resources[resource_id] = domain_resource
    diagnostics.extend(_ownership_diagnostics(domain_resources.values()))
    _, graph_diagnostics = _dependency_order(domain_resources)
    diagnostics.extend(graph_diagnostics)
    selected_resources, selection_diagnostics = _select_resources(
        domain_resources, selectors
    )
    diagnostics.extend(selection_diagnostics)
    dependency_order, _ = _dependency_order(selected_resources)
    artifacts, artifact_diagnostics = _artifact_values(documents)
    diagnostics.extend(artifact_diagnostics)
    if diagnostics:
        return ConfigurationLoadResult(None, tuple(diagnostics))
    ordered_resources = tuple(
        selected_resources[resource_id.value] for resource_id in dependency_order
    )
    return ConfigurationLoadResult(
        configuration=ResolvedConfiguration(
            schema_version=1,
            device_id=device_id,
            profile_ids=selected_profile_ids,
            resources=ordered_resources,
            dependency_order=dependency_order,
            artifacts=artifacts,
            secret_references=(secret,),
            device=ResolvedDevice(
                id=device_id,
                endpoint=DeviceEndpoint(
                    host=device.endpoint.host,
                    port=device.endpoint.port,
                ),
                ssh_username=device.ssh.username,
                host_key_reference=device.ssh.host_key.reference,
                credential_reference=secret,
            ),
        ),
        diagnostics=(),
    )
