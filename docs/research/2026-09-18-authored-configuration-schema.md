# Authored configuration schema contract

Date: 2026-09-18

Ticket: [Prototype the Profile, inventory, and Artifact schemas](https://github.com/jbruns/tv/issues/38)

Interactive evidence: [Throwaway authored-schema prototype](../../prototypes/coreelec-reconciler-schema-prototype.html)

Status: **Accepted contract-level decision**

## 1. Decision

The Reconciler accepts four separate, restricted, explicitly versioned authored
document kinds:

- `DeviceInventory`
- `Profile`
- `ArtifactCatalog`
- `SecretProviderCatalog`

The conventional repository roots are `inventory/`, `profiles/`, `artifacts/`,
and `secret-providers/`. Filenames and subdirectories exist only for human
organization. Every cross-document reference uses a declared logical ID, never
a path or filename. Duplicate IDs in or across files of the relevant kind fail
validation.

This record resolves the authored contract. Exact Pydantic class names, Python
module/file names, and the production parser implementation remain
implementation details. The linked interactive prototype remains throwaway
evidence and is not production code.

## 2. Restricted, versioned YAML boundary

Every file contains exactly one YAML document with:

```yaml
kind: DeviceInventory
schema_version: 1
```

`kind` selects a closed schema and `schema_version` is an explicit integer.
Each kind has a finite set of supported versions. Unknown kinds, unknown
fields, non-integer versions, and unsupported versions fail rather than being
ignored.

Schema migration is a separate, deterministic operation whose reviewed output
is committed like any other authored change. Loading never silently rewrites,
upgrades, or reinterprets an older document.

The accepted YAML subset permits ordinary mappings, sequences, and scalars and
rejects:

- multiple YAML documents in one file;
- duplicate mapping keys;
- anchors, aliases, and merge keys;
- custom tags;
- non-string mapping keys.

Timestamp-looking values remain strings unless a field's schema explicitly
parses them. This prevents the YAML loader from silently changing authored
types.

Validation occurs before any Device transport is constructed. It aggregates
independent diagnostics where possible. Each diagnostic contains:

- source file;
- line and column when available;
- document, Resource, or Artifact ID when known;
- field path;
- stable diagnostic code;
- human-readable message.

A syntax failure blocks semantic checks only for the unusable document. Other
parseable documents continue through independent validation so one run can
report multiple actionable errors. Invalid IDs/types, unknown fields/types or
kinds, unsupported versions, unresolved references, graph failures, ownership
collisions, and policy violations all fail.

## 3. Logical identities

Device, Profile, Resource, Artifact, secret, and selector IDs use stable
lowercase dot-separated segments, with hyphens allowed inside a segment:

```text
living-room.ugoos-am6b-plus
platform.coreelec-21.amlogic-ng
room.living-room
skin.playlist.new-shows
artifact.kodi.skin.arctic-fuse
secret.kodi.web-password
selector.skin
```

An ID is never derived from a repository path, hostname, display label,
network endpoint, or software version. Those values can change without
changing logical identity.

## 4. Device inventory

Inventory binds one durable Device identity to connection and composition
inputs. It contains:

- a durable Device ID;
- endpoint;
- SSH host-key policy and reference;
- non-secret SSH username;
- exactly one platform Profile;
- optionally one room Profile;
- optionally one Device Profile;
- typed credential references.

Inventory contains no Desired State, Resources, or Artifact versions.

`inventory/living-room/ugoos.yaml`:

```yaml
kind: DeviceInventory
schema_version: 1

devices:
  - id: living-room.ugoos-am6b-plus
    endpoint:
      host: coreelec-living-room.example.test
      port: 22
    ssh:
      username: root
      host_key:
        policy: pinned
        reference: ssh-host-key.living-room.ugoos-am6b-plus
      credential:
        type: secret
        provider: controller.environment
        key: coreelec.admin-private-key
    profiles:
      platform: platform.coreelec-21.amlogic-ng
      room: room.living-room
      device: device.living-room.ugoos-am6b-plus
```

The host-key reference identifies trusted controller-side material; it is not a
secret value or Device Desired State. Implementations may support additional
closed credential types later, but may not infer credentials from ambient
environment variables.

## 5. Profiles and fixed composition

Profiles have one explicit layer: `platform`, `room`, or `device`. A Device is
composed only in the inventory-declared order:

```text
platform Profile -> optional room Profile -> optional Device Profile
```

Profiles cannot import or inherit other Profiles. There is no arbitrary
precedence graph.

Resources merge by stable Resource ID. Within a Resource:

- schema-controlled mappings merge recursively;
- scalars replace;
- lists replace;
- Resource `type` is immutable across layers;
- field-level provenance is retained.

After every merge, ownership and all other global invariants are revalidated.
Omitting a Resource or field means unmanaged/no claim; omission is never an
implicit request for absence.

### 5.1 Platform Profile

`profiles/platform/coreelec-21-amlogic-ng.yaml`:

```yaml
kind: Profile
schema_version: 1

id: platform.coreelec-21.amlogic-ng
layer: platform

resources:
  - id: skin.playlist.new-shows
    type: KodiSmartPlaylist
    management: enforce
    desired: present
    selectors:
      - selector.baseline
      - selector.skin
    requires: []
    intent:
      playlist:
        id: playlist.video.new-shows
        media_type: tvshows
        display_name: New Shows
        match: all
        limit: 50
        rules:
          - field: playcount
            operator: is
            value: 0
        order:
          by: dateadded
          direction: descending
      file:
        mode: "0644"

  - id: kodi.web-interface
    type: KodiWebInterfaceSettings
    management: enforce
    desired: present
    selectors:
      - selector.baseline
      - selector.services
    requires: []
    intent:
      enabled: true
      username: kodi
      password:
        type: secret
        provider: controller.environment
        key: kodi.web-password
```

The accepted representative `KodiSmartPlaylist` is exactly
`skin.playlist.new-shows`: `management: enforce`, `desired: present`, selectors
`selector.baseline` and `selector.skin`, no dependencies and no Effect recipe.
Its Intent names the logical video playlist, `tvshows`, display name
`New Shows`, match `all`, limit `50`, rule `playcount is 0`, order
`dateadded descending`, and mode `0644`.

The `KodiSmartPlaylist` Resource Type deterministically derives XML and owns the
whole-file State Address:

```text
special://profile/playlists/video/NewShows.xsp
```

That path is derived representation, not authored Profile data.

### 5.2 Room Profile

`profiles/room/living-room.yaml`:

```yaml
kind: Profile
schema_version: 1

id: room.living-room
layer: room

resources:
  - id: kodi.room-output
    type: KodiRoomOutput
    management: enforce
    desired: present
    selectors:
      - selector.room
    requires: []
    intent:
      display:
        preference: living-room-tv
      audio:
        preference: living-room-avr
        passthrough: true

  - id: skin.playlist.new-shows
    type: KodiSmartPlaylist
    management: enforce
    desired: present
    selectors:
      - selector.baseline
      - selector.skin
      - selector.room
    requires: []
    intent:
      playlist:
        limit: 40
```

The room layer replaces `limit` and the selector list while retaining the other
schema-controlled mapping fields from the platform layer.

### 5.3 Device Profile

`profiles/device/living-room-ugoos.yaml`:

```yaml
kind: Profile
schema_version: 1

id: device.living-room.ugoos-am6b-plus
layer: device

resources:
  - id: skin.playlist.new-shows
    type: KodiSmartPlaylist
    management: enforce
    desired: present
    selectors:
      - selector.baseline
      - selector.skin
      - selector.room
    requires: []
    intent:
      playlist:
        limit: 50

  - id: weather.home-assistant
    type: KodiWeatherSettings
    management: observe-only
    desired: present
    selectors:
      - selector.services
    requires:
      - kodi.web-interface
    when:
      all:
        - fact: inventory.room
          equals: room.living-room
        - capability: kodi.addon.weather.ha
          equals: available
    intent:
      endpoint: https://home-assistant.example.test
      token:
        type: secret
        provider: controller.environment
        key: weather.home-assistant-token
```

The Device layer restores the playlist limit to `50`. It does not copy the
complete Resource merely to override one nested scalar.

### 5.4 Composition result and field origins

For `living-room.ugoos-am6b-plus`, the playlist resolves to:

```yaml
resource:
  id: skin.playlist.new-shows
  type: KodiSmartPlaylist
  management: enforce
  desired: present
  selectors:
    - selector.baseline
    - selector.skin
    - selector.room
  requires: []
  intent:
    playlist:
      id: playlist.video.new-shows
      media_type: tvshows
      display_name: New Shows
      match: all
      limit: 50
      rules:
        - field: playcount
          operator: is
          value: 0
      order:
        by: dateadded
        direction: descending
    file:
      mode: "0644"

origins:
  type: profiles/platform/coreelec-21-amlogic-ng.yaml
  management: profiles/device/living-room-ugoos.yaml
  desired: profiles/device/living-room-ugoos.yaml
  selectors: profiles/device/living-room-ugoos.yaml
  requires: profiles/device/living-room-ugoos.yaml
  intent.playlist.id: profiles/platform/coreelec-21-amlogic-ng.yaml
  intent.playlist.media_type: profiles/platform/coreelec-21-amlogic-ng.yaml
  intent.playlist.display_name: profiles/platform/coreelec-21-amlogic-ng.yaml
  intent.playlist.match: profiles/platform/coreelec-21-amlogic-ng.yaml
  intent.playlist.limit: profiles/device/living-room-ugoos.yaml
  intent.playlist.rules: profiles/platform/coreelec-21-amlogic-ng.yaml
  intent.playlist.order: profiles/platform/coreelec-21-amlogic-ng.yaml
  intent.file.mode: profiles/platform/coreelec-21-amlogic-ng.yaml
```

The origin map is evidence for review, diagnostics, and Plans. It does not
change precedence.

## 6. Common Resource contract

Every Resource uses this envelope:

```yaml
id: resource.logical-id
type: ClosedResourceType
management: enforce  # enforce | observe-only
desired: present     # present | absent
selectors: []
requires: []
intent: {}
```

Type-specific policy exists only under typed `intent`. Authored Profiles do not
contain:

- Effects or Effect recipes;
- transport or command recipes;
- verification recipes;
- resolved Device paths;
- serialized Device representation;
- observed state.

Authored Intent is domain policy. A Resource Type derives Device paths,
serialization, commands, and verification representation from that Intent and
observed platform capabilities.

`management` controls mutation:

- `enforce` may plan mutation and then independently verify;
- `observe-only` never mutates but still independently verifies its declared
  Desired State.

`desired` controls whether the owned state must be present or absent. Omission
means unmanaged.

### 6.1 Conditional applicability

An optional `when` is a constrained predicate over a closed, typed vocabulary
of inventory facts and observed capabilities. It is not a general expression
language. Templates, shell, environment interpolation, function calls, and
arbitrary property access are forbidden.

If `when` is false, the Resource is not applicable and makes no ownership claim;
it is unmanaged, not implicitly absent. If a required fact or capability is
unknown or unavailable, evaluation fails explicitly rather than treating the
condition as false.

### 6.2 Explicit absence

Absence uses the same Resource ID and type:

```yaml
id: skin.playlist.new-shows
type: KodiSmartPlaylist
management: enforce
desired: absent
selectors:
  - selector.baseline
  - selector.skin
requires: []
intent:
  playlist:
    id: playlist.video.new-shows
    media_type: tvshows
```

Type-specific identity Intent must remain sufficient to calculate and own the
State Address. The absent schema rejects present-only fields such as display
name, rules, order, limit, and file mode. Absence can therefore remove only the
specific state that the Resource Type derives from valid identity Intent; it
is never arbitrary path deletion.

## 7. Ownership, selectors, and dependencies

Exclusive State Address ownership is validated after composition and after
selector/dependency expansion for every combination of:

- `desired: present` and `desired: absent`;
- `management: enforce` and `management: observe-only`.

Partial-document Resources own the smallest semantic field the format can
honestly address. Whole-file Resources own the complete document. Two selected
Resources claiming the same address fail before transport, regardless of layer,
management mode, or desired presence.

Selectors first choose Resources by tags. Selection then adds:

1. complete transitive Resource dependency closure; and
2. complete shared-document ownership closure.

Familiar selectors such as baseline, skin, services, or room do not define
ownership or transaction boundaries.

`requires` contains stable Resource IDs. The Resource graph must resolve, be
acyclic, and be applied in dependency order. An edge means the dependency's
Desired State must independently verify before the dependent can proceed.

### 7.1 Q9 correction: dependency satisfaction

The prototype discussion initially contained a contradiction about which
Resource states could satisfy a dependency. The accepted rule is:

> Any `present` or `absent`, `enforce` or `observe-only` Resource may satisfy a
> dependency edge when its declared Desired State independently verifies.

Management controls mutation, not dependency satisfaction. An observe-only
Resource can therefore satisfy an edge without being mutated, and a verified
absence can be a legitimate prerequisite. Command success, attempted mutation,
or mere graph presence cannot satisfy an edge.

## 8. Secret providers and references

A typed secret reference contains a provider ID plus a logical key. Provider
configuration lives outside Profiles.

`secret-providers/controller-environment.yaml`:

```yaml
kind: SecretProviderCatalog
schema_version: 1

providers:
  - id: controller.environment
    type: environment
    keys:
      coreelec.admin-private-key:
        variable: COREELEC_ADMIN_PRIVATE_KEY_FILE
      kodi.web-password:
        variable: KODI_WEB_PASSWORD
      weather.home-assistant-token:
        variable: WEATHER_HA_TOKEN
```

The first implementation may support only the environment provider. Environment
variable names are provider configuration, never Profile Intent.

Provider and logical-key existence are validated before transport where
possible. The actual value is resolved only at the consuming apply operation,
not during Profile composition or planning. Secret values are forbidden from:

- resolved Profiles;
- Plans;
- Run reports;
- logs;
- caches.

Diagnostics and evidence may identify the provider and logical key but never
the resolved value.

## 9. Artifact catalog

An Artifact entry contains:

- stable logical Artifact ID;
- kind;
- upstream identity;
- exact version;
- immutable, digest-pinned source;
- final SHA-256;
- platform constraints;
- Artifact dependency IDs.

Profiles reference only the Artifact ID. `latest`, version ranges, and ad hoc
Profile digests are forbidden.

Initial source schemes are:

- immutable HTTPS;
- repository-relative payload or build inputs.

Every source is digest-pinned. Mutable absolute local paths, SSH/SCP sources,
and Device-side downloads are forbidden.

`artifacts/kodi-addons.yaml`:

```yaml
kind: ArtifactCatalog
schema_version: 1

artifacts:
  - id: artifact.kodi.weather.ha
    kind: kodi-addon
    upstream:
      project: weather.ha
      version: 2.0.4
    release:
      channel: stable
    source:
      scheme: https
      url: https://example.test/releases/weather.ha-2.0.4.zip
      sha256: 1a11111111111111111111111111111111111111111111111111111111111111
    final_sha256: 1a11111111111111111111111111111111111111111111111111111111111111
    platforms:
      - coreelec-21-amlogic-ng
    requires: []

  - id: artifact.kodi.skin.arctic-fuse
    kind: kodi-addon
    upstream:
      project: skin.arctic.fuse
      version: 2.1.0-rc.3
    release:
      channel: prerelease
      exception:
        rationale: Stable release lacks the accepted pilot skin behavior.
        approval: approval.issue-52
        acceptance_evidence: evidence.skin-pilot-2026-09-18
        approved_on: "2026-09-18"
        expires_on: "2026-10-18"
        review_trigger: stable-release-published
    source:
      scheme: https
      url: https://example.test/releases/skin.arctic.fuse-2.1.0-rc.3.zip
      sha256: 2b22222222222222222222222222222222222222222222222222222222222222
    final_sha256: 2b22222222222222222222222222222222222222222222222222222222222222
    platforms:
      - coreelec-21-amlogic-ng
    requires: []

  - id: artifact.kodi.plugin.video.example-patched
    kind: kodi-addon
    upstream:
      project: plugin.video.example
      version: 7.4.1
    release:
      channel: stable
    source:
      scheme: repository-build
      path: artifacts/build-inputs/plugin.video.example/7.4.1/
      sha256: 3c33333333333333333333333333333333333333333333333333333333333333
    build:
      recipe: build.kodi-addon-patched.v1
      upstream_sha256: 4d44444444444444444444444444444444444444444444444444444444444444
      patches:
        - path: artifacts/patches/plugin.video.example/0001-coreelec-compat.patch
          sha256: 5e55555555555555555555555555555555555555555555555555555555555555
        - path: artifacts/patches/plugin.video.example/0002-kodi-api.patch
          sha256: 6f66666666666666666666666666666666666666666666666666666666666666
    final_sha256: 7a77777777777777777777777777777777777777777777777777777777777777
    platforms:
      - coreelec-21-amlogic-ng
    requires:
      - artifact.kodi.script.module.example
```

Stable is the default policy. A prerelease requires a structured rationale,
approval reference, acceptance-evidence reference, approval date, and mandatory
expiry or review trigger. An expired exception fails validation.

A patched Artifact requires the upstream source digest, ordered patch entries
and their digests, reproducible build recipe identity, and final digest. Full
provenance is exposed during resolution, while the Device receives only the
final verified payload. Any source, patch, build, or final digest mismatch
fails.

The Artifact dependency graph is distinct from the Resource dependency graph.
It must be transitively resolved, acyclic, and digest-verified. Resolving an
Artifact dependency never implicitly creates a Device Resource.

A Profile binds an Artifact without restating supply-chain details:

```yaml
id: addon.weather.ha
type: KodiAddon
management: enforce
desired: present
selectors:
  - selector.services
requires: []
intent:
  artifact: artifact.kodi.weather.ha
  enabled: true
```

## 10. Resolved pre-transport summary

After parsing, composition, conditions, selection, closure, reference checks,
graph validation, Artifact resolution, and ownership expansion, a
secret-free summary can take this shape:

```yaml
schema_version: 1
device_id: living-room.ugoos-am6b-plus
profiles:
  platform: platform.coreelec-21.amlogic-ng
  room: room.living-room
  device: device.living-room.ugoos-am6b-plus
selection:
  requested:
    - selector.skin
  expanded_resources:
    - skin.playlist.new-shows
resources:
  - id: skin.playlist.new-shows
    type: KodiSmartPlaylist
    management: enforce
    desired: present
    dependency_ids: []
    state_addresses:
      - special://profile/playlists/video/NewShows.xsp
    representation:
      format: kodi-smart-playlist-xml
      identity: playlist.video.new-shows
    field_origins:
      intent.playlist.limit: profiles/device/living-room-ugoos.yaml
artifacts: []
secret_references: []
diagnostics: []
transport_ready: true
```

The summary may expose derived representation metadata needed for review, but
not transport recipes, commands, observed state, or secret values. A production
canonical Plan and Run report schema is a separate decision.

## 11. Invalid examples

The following examples are intentionally concise. Production diagnostics must
include the complete location and stable-code envelope defined above.

### 11.1 Duplicate ownership

```yaml
resources:
  - id: skin.playlist.new-shows
    type: KodiSmartPlaylist
  - id: skin.file.new-shows
    type: ManagedFile
    intent:
      path: special://profile/playlists/video/NewShows.xsp
```

Fails because two Resources derive the same whole-file State Address.

### 11.2 Missing and cyclic Resource dependencies

```yaml
- id: service.weather
  requires: [addon.weather.missing]
- id: addon.weather.ha
  requires: [service.weather]
- id: service.weather
  requires: [addon.weather.ha]
```

The first edge is unresolved; the latter two edges form a cycle. Both fail
before transport.

### 11.3 Inline and missing secrets

```yaml
password: super-secret
```

Fails because secret-bearing Intent requires a typed reference.

```yaml
password:
  type: secret
  provider: controller.environment
  key: kodi.not-declared
```

Fails because the provider does not declare the logical key.

### 11.4 Missing or expired prerelease exception

```yaml
release:
  channel: prerelease
```

Fails because the structured exception is missing.

```yaml
release:
  channel: prerelease
  exception:
    rationale: Pilot dependency.
    approval: approval.issue-52
    acceptance_evidence: evidence.skin-pilot
    approved_on: "2026-08-01"
    expires_on: "2026-09-01"
```

Fails after expiry.

### 11.5 Patched provenance or digest mismatch

```yaml
build:
  recipe: build.kodi-addon-patched.v1
  upstream_sha256: 4d44444444444444444444444444444444444444444444444444444444444444
  patches: []
final_sha256: does-not-match-rebuilt-output
```

Fails because ordered patch provenance is incomplete and the rebuilt final
digest does not match.

### 11.6 Unknown field, type, or version

```yaml
kind: Profile
schema_version: 99
id: room.living-room
layer: room
resoruces: []
```

Fails for unsupported version and unknown misspelled field.

```yaml
type: ArbitraryShellResource
```

Fails because Resource Types are closed and unknown types are not ignored.

### 11.7 Duplicate-key and multi-document YAML

```yaml
kind: Profile
kind: ArtifactCatalog
schema_version: 1
```

Fails for duplicate key.

```yaml
kind: Profile
schema_version: 1
---
kind: Profile
schema_version: 1
```

Fails because one file may contain exactly one document.

## 12. Validation and composition sequence

The pre-transport gate is:

1. discover files only under the four conventional roots;
2. parse the restricted one-document YAML subset;
3. dispatch by supported `kind` and integer `schema_version`;
4. reject unknown fields and validate field types and logical IDs;
5. register declared IDs and reject duplicates;
6. resolve the inventory-selected platform, room, and Device Profiles;
7. compose only in fixed layer order while retaining field provenance;
8. evaluate constrained `when` predicates from typed facts/capabilities;
9. select by selector tags, then add Resource and shared-document closure;
10. validate Resource references, acyclicity, and independent-verification
    prerequisites;
11. resolve and verify the separate Artifact graph;
12. validate secret provider/key existence without resolving values;
13. derive State Addresses and representation identities through Resource
    Types;
14. reject all ownership collisions globally;
15. aggregate diagnostics and construct transport only if no failures remain.

No stage silently fixes authored input. No Device connection or mutation occurs
until the complete applicable configuration passes this gate.

## 13. Consequences

- Authored files remain readable domain policy rather than transport programs.
- Device identity and repository organization can evolve independently.
- Fixed composition is explainable and provenance-preserving.
- Omission, explicit absence, observe-only policy, and conditional
  non-applicability remain distinct.
- Exclusive ownership and independently verified dependencies fail safely
  before mutation.
- Secrets remain late-bound and excluded from durable outputs.
- Artifact provenance and dependency resolution are explicit without conflating
  Artifacts with Device Resources.
- Future schema changes require explicit supported versions and reviewed
  migrations.

The contract deliberately leaves production parser mechanics and exact model
class/file names open for the implementation tickets.
