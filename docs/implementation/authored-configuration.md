# Authored configuration implementation

The production authored-configuration boundary implements the accepted
[authored configuration schema contract](../research/2026-09-18-authored-configuration-schema.md)
for the M2 `skin.playlist.new-shows` slice.

## Public boundary

Call:

```python
load_configuration(repository_root, device_id, selectors=())
```

The loader discovers YAML only below `inventory/`, `profiles/`, `artifacts/`,
and `secret-providers/`. It returns `ConfigurationLoadResult`, containing
either a frozen `ResolvedConfiguration` or stable diagnostics. PyYAML and
Pydantic are confined to `coreelec_reconciler.config`; every returned value is
a frozen standard-library dataclass, enum, tuple, string, or integer.

The canonical codec is:

```python
encode_resolved_configuration(configuration)
decode_resolved_configuration(content)
```

It emits UTF-8 JSON with lexicographically sorted object keys, no insignificant
whitespace, and no trailing newline. Decode rejects duplicate fields, unknown
top-level fields, unsupported versions, and noncanonical bytes.

## Implemented authored forms

- `DeviceInventory` version 1 with endpoint, pinned host-key reference, typed
  SSH secret reference, and platform/optional room/optional Device Profile IDs.
- `Profile` version 1 with the common Resource envelope and the accepted
  `KodiSmartPlaylist` Intent needed by `skin.playlist.new-shows`.
- `SecretProviderCatalog` version 1 with the environment provider and declared
  logical keys. Values are never read or returned.
- `ArtifactCatalog` version 1, including the empty catalog used by this slice
  and the dependency-free, stable, direct-origin GitHub release-asset subset
  of the accepted Artifact form. No dependency selection, download, build,
  attestation, or prerelease handling is performed.

The fixed composition order is platform, optional room, then optional Device.
Resources merge by stable ID. The Resource Type cannot change. The typed
`intent` mapping merges recursively; scalar values replace and list values
replace. Field origins retain repository-relative source names.

Selectors choose Resources by typed selector ID and add the complete upstream
Resource dependency closure. Dependencies are validated globally before
selection and emitted in deterministic dependency order. Exclusive logical
State Address ownership is checked across every composed Resource regardless
of management mode or desired presence.

## Restrictions

The YAML boundary accepts one mapping document and rejects duplicate keys,
multiple documents, anchors, aliases, merge keys, tags, and non-string mapping
keys. Timestamp-looking scalars stay strings. Pydantic strict mode rejects
unknown fields and scalar coercion.

The implemented Resource Type set is closed to `KodiSmartPlaylist`. It derives
only the accepted logical State Address:

```text
special://profile/playlists/video/NewShows.xsp
```

No command, transport, Effect, Device path, observed state, plugin hook, or
RuntimeValues behavior is authored or implemented here.

## Stable diagnostics

The v1 inventory is:

- `yaml.read-failed`
- `yaml.syntax`
- `yaml.multiple-documents`
- `yaml.document-not-mapping`
- `yaml.duplicate-key`
- `yaml.unsafe-anchor`
- `yaml.unsafe-alias`
- `yaml.unsafe-tag`
- `yaml.merge-key`
- `yaml.non-string-key`
- `schema.unknown-kind`
- `schema.invalid-version`
- `schema.unsupported-version`
- `schema.unknown-field`
- `schema.invalid`
- `id.invalid`
- `id.duplicate`
- `resource.duplicate-id`
- `resource.unknown-type`
- `composition.type-conflict`
- `composition.layer-mismatch`
- `reference.device-unresolved`
- `reference.profile-unresolved`
- `reference.secret-unresolved`
- `reference.artifact-unresolved`
- `secret.invalid-reference`
- `selector.unresolved`
- `dependency.unresolved`
- `dependency.cycle`
- `ownership.conflict`
- `artifact.invalid-digest`
- `artifact.digest-conflict`
- `artifact.dependency-cycle`

Each diagnostic has a source, one-based line and column, structured field
path, stable code, safe message, and optional logical subject ID. Diagnostics
may name an opaque provider/key reference but never contain a resolved secret
value.
