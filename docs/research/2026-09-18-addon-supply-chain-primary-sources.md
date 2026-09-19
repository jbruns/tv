# Add-on supply-chain primary-source verification

Date: 2026-09-18

Ticket: [Define the stable add-on update and patch supply chain](https://github.com/jbruns/tv/issues/47)

Status: **Primary-source research record; no implementation decision**

## 1. Scope and method

This record answers [issue #47](https://github.com/jbruns/tv/issues/47) by
checking repository claims against the repository's accepted records and
implementation, and external claims against primary sources: official
documentation, source, specifications, and first-party APIs.

The repository evidence read for this record is:

- the issue text and supplied research output;
- [ADR 0005](../adr/0005-stable-addon-artifact-supply-chain.md);
- the accepted [authored Artifact schema](2026-09-18-authored-configuration-schema.md#9-artifact-catalog);
- the [M6 roadmap contract](2026-09-18-implementation-milestones-documentation-transitions.md#m6--add-ons-artifact-supply-chain-and-add-on-settings);
- the [current managed-state inventory](2026-09-18-current-managed-state-inventory.md);
- the current [`provision.conf`](../../config/shared/ugoos-am6b-plus/coreelec-21.3/provision.conf);
- the current [artifact library](../../lib/coreelec-artifacts.sh) and
  [artifact tests](../../tests/test-coreelec-artifacts.sh); and
- the current [Device-side patch implementation](../../provision-coreelec.sh#L1940-L2230).

Sections 2 and 3 are established facts. Section 5 contains candidate
recommendations only. This record does not select an implementation, approve
an exception, or amend an accepted contract.

## 2. Established repository facts

### 2.1 Accepted contract and issue boundary

Issue #47 asks for repository automation that discovers eligible stable
upstream releases, applies reviewed prerelease exceptions, reproducibly builds
patched Artifacts, records upstream/patch-set/final provenance digests,
validates catalog and dependency changes, and opens evidence-rich pull
requests without auto-merging or deploying.
[Issue #47](https://github.com/jbruns/tv/issues/47)

The accepted records already constrain that work:

- stable upstream releases are the default;
- ADR 0005 originally required per-Artifact rationale, a pinned digest,
  additional acceptance evidence, and an expiry or review trigger; the final
  issue #47 refinement makes `expires_on` mandatory and limits it to 90 days;
- a patched Artifact is reproducibly built and records upstream, patch-set,
  and final digests;
- the Device receives the prebuilt final Artifact rather than running source
  transforms; and
- automation may propose a pull request but may not auto-merge or deploy.
  [ADR 0005](../adr/0005-stable-addon-artifact-supply-chain.md#use-a-stable-first-reviewed-add-on-artifact-supply-chain)

The authored schema puts supply-chain facts in an Artifact catalog, not in a
Profile. Each entry has a stable logical ID, kind, upstream identity, exact
version, digest-pinned source, final SHA-256, platform constraints, and
Artifact dependency IDs. It forbids `latest`, version ranges, ad hoc Profile
digests, mutable absolute local paths, SSH/SCP sources, and Device-side
downloads. A patched entry additionally records an immutable recipe identity,
the upstream digest, and ordered patch paths and digests. The dependency graph
must be complete, acyclic, and digest-verified.
[Authored schema](2026-09-18-authored-configuration-schema.md#9-artifact-catalog)

The roadmap makes the complete live scope an M6 prerequisite and acceptance
surface: `ART-001–ART-041`, `PATCH-001–PATCH-004`, stable/prerelease fixtures,
dependency expansion, reproducible build evidence, ZIP/content safety, and
failure before Device mutation on digest, provenance, dependency, or
prerelease-policy error. Release-discovery/update-PR automation may trail the
first live acceptance, but must be complete before M10.
[M6 roadmap](2026-09-18-implementation-milestones-documentation-transitions.md#m6--add-ons-artifact-supply-chain-and-add-on-settings)

### 2.2 Exact 41-entry initial Artifact scope

The initial scope is exactly the 41 `ADDON_ARTIFACT` records in
[`provision.conf`](../../config/shared/ugoos-am6b-plus/coreelec-21.3/provision.conf#L156-L210),
cross-indexed as `ART-001–ART-041` in the
[inventory](2026-09-18-current-managed-state-inventory.md#34-add-on-artifacts-installation-enabled-state-settings-and-onboarding).
It comprises 3 repository add-ons, 7 selected add-ons/resources, 6 optional
skin dependencies, 2 CoreELEC binary dependencies, and 23 transitive
dependencies:

| Inventory ID | Add-on ID | Locked version | Category / current source family |
|---|---|---:|---|
| ART-001 | `repository.emby.kodi` | `1.0.8` | Repository add-on; publisher HTTPS |
| ART-002 | `repository.dontpanic` | `0.2.10` | Repository add-on; publisher HTTPS |
| ART-003 | `repository.jurialmunkey` | `3.4` | Repository add-on; publisher HTTPS |
| ART-004 | `plugin.service.emby-next-gen` | `11.1.27` | Selected; Emby Omega repository |
| ART-005 | `plugin.video.themoviedb.helper` | `6.17.1` | Selected; Jurialmunkey moving `master` |
| ART-006 | `pvr.nextpvr` | `21.3.2.1` | Selected; CoreELEC platform repository |
| ART-007 | `script.plexmod` | `1.3.19` | Selected; commit-addressed Don't Panic repository |
| ART-008 | `skin.arctic.fuse.3` | `3.2.16` | Selected; Jurialmunkey moving `master` |
| ART-009 | `weather.ha` | `0.0.6.6` | Selected; GitHub tag-generated archive |
| ART-010 | `resource.language.en_us` | `11.0.82` | Selected; Kodi Omega repository |
| ART-011 | `script.artistslideshow` | `4.2.0` | Optional skin dependency; Kodi Omega |
| ART-012 | `resource.images.arctic.waves` | `0.0.2` | Optional skin dependency; Jurialmunkey moving `master` |
| ART-013 | `resource.images.weatherfanart.multi` | `0.0.6` | Optional skin dependency; Kodi Omega |
| ART-014 | `resource.images.moviecountryicons.maps` | `0.0.1` | Optional skin dependency; Kodi Omega |
| ART-015 | `resource.images.studios.white` | `0.0.34` | Optional skin dependency; Kodi Omega |
| ART-016 | `resource.uisounds.fromashes` | `3.0.01` | Optional skin dependency; Kodi Omega |
| ART-017 | `inputstream.adaptive` | `21.5.24.1` | Binary dependency; CoreELEC platform repository |
| ART-018 | `inputstream.ffmpegdirect` | `21.3.8.1` | Binary dependency; CoreELEC platform repository |
| ART-019 | `resource.font.robotocjksc` | `0.0.3` | Transitive; Jurialmunkey moving `master` |
| ART-020 | `resource.images.studios.coloured` | `0.0.24` | Transitive; Kodi Omega |
| ART-021 | `resource.images.weathericons.white` | `0.0.6` | Transitive; Kodi Omega |
| ART-022 | `script.module.addon.signals` | `0.0.6+matrix.1` | Transitive; Kodi Omega |
| ART-023 | `script.module.certifi` | `2023.5.7` | Transitive; Kodi Omega |
| ART-024 | `script.module.chardet` | `5.1.0` | Transitive; Kodi Omega |
| ART-025 | `script.module.defusedxml` | `0.6.0+matrix.1` | Transitive; Kodi Omega |
| ART-026 | `script.module.dateutil` | `2.8.2` | Transitive; Kodi Omega |
| ART-027 | `script.module.future` | `1.0.0+matrix.1` | Transitive; Kodi Omega |
| ART-028 | `script.module.idna` | `3.10.0` | Transitive; Kodi Omega |
| ART-029 | `script.module.infotagger` | `0.0.9` | Transitive; Jurialmunkey moving `master` |
| ART-030 | `script.module.inputstreamhelper` | `0.8.5` | Transitive; Kodi Omega |
| ART-031 | `script.module.iso8601` | `2.0.0` | Transitive; Kodi Omega |
| ART-032 | `script.module.jurialmunkey` | `0.2.35` | Transitive; Jurialmunkey moving `master` |
| ART-033 | `script.module.kodi-six` | `0.1.3.1` | Transitive; Kodi Omega |
| ART-034 | `script.module.pysocks` | `1.7.0+matrix.1` | Transitive; Kodi Omega |
| ART-035 | `script.module.qrcode` | `6.1.0+matrix.3` | Transitive; Kodi Omega |
| ART-036 | `script.module.requests` | `2.31.0` | Transitive; Kodi Omega |
| ART-037 | `script.module.six` | `1.16.0+matrix.1` | Transitive; Kodi Omega |
| ART-038 | `script.module.urllib3` | `2.2.3` | Transitive; Kodi Omega |
| ART-039 | `script.module.yaml` | `6.0.1` | Transitive; Kodi Omega |
| ART-040 | `script.skinvariables` | `2.2.2` | Transitive; Jurialmunkey moving `master` |
| ART-041 | `script.texturemaker` | `0.2.11` | Transitive; Jurialmunkey moving `master` |

Every row already has an exact URL and SHA-256 in the lock. Eight rows still
retrieve through mutable Jurialmunkey `master`: ART-005, ART-008, ART-012,
ART-019, ART-029, ART-032, ART-040, and ART-041. Their SHA-256 pins detect
different bytes, but the URLs do not guarantee that the reviewed bytes remain
retrievable. ART-007 is already commit-addressed. ART-009 is a codeload
archive for an exact tag because upstream release `0.0.6.6` has no attached
asset.
[`provision.conf`](../../config/shared/ugoos-am6b-plus/coreelec-21.3/provision.conf#L45-L81)

Three archives have a top-level directory that differs from the declared add-on
ID: ART-004 `plugin.service.emby-next-gen`, ART-019
`resource.font.robotocjksc`, and ART-009 `weather.ha`. The configuration comment
lists four packaging cases, but ART-007 `script.plexmod` has the root
`script.plexmod/`, exactly equal to its ID, so it is not an override. These are
required compatibility fixtures; installation identity comes from `addon.xml`,
not the archive root.
[`provision.conf` packaging notes](../../config/shared/ugoos-am6b-plus/coreelec-21.3/provision.conf#L212-L219)

### 2.3 Exact four-patch initial scope

The current Device transformer contains exactly four classified compatibility
patch groups, affecting three locked add-ons:

| Patch ID | Exact locked input | Files and transformation | Current checks |
|---|---|---|---|
| PATCH-001 | `weather.ha` `0.0.6.6` | `resources/settings.xml`: require the sole `ha_request_attempts` setting to have `type="int"` and change it to `type="number"` | Required file, exact prior structure |
| PATCH-002 | `weather.ha` `0.0.6.6` | `lib/homeassistant/_adapter.py`: insert `continue` after the request exception fallback so `r` is not read unbound | Exact ID/version, exact line sequence/counts, idempotent exact-prepatched acceptance, Python compile check |
| PATCH-003 | `script.plexmod` `1.3.19` | `lib/monitor.py`: guard the `windowutils.HOME` close operations with `if windowutils.HOME` | Exact ID/version, exactly one expected sequence, Python compile check |
| PATCH-004 | `plugin.video.themoviedb.helper` `6.17.1` | `resources/tmdbhelper/lib/monitor/service.py`: mark Cron and Image threads daemon before start; `cronjob.py`: return if abort/exit becomes true after `waitForAbort` and before `_on_poll()` | Exact ID/version, exact sequences/counts, exact-prepatched acceptance, rejects partial/different patches, Python compile checks |

The implementation expands ZIPs in a remote staging area, runs these
transformers there, and only then enters Device replacement. It does not emit
a reusable, final digest-pinned patched ZIP, so its current result cannot meet
ADR 0005's prebuilt-Artifact contract.
[`provision-coreelec.sh`](../../provision-coreelec.sh#L1940-L2230)

The tests preserve important patch acceptance and rejection cases: correct
PM4K guard, TMDb daemon/abort edits, exact-prepatched acceptance, wrong-version
refusal, missing/duplicate/different sequence refusal, compile failure, and
Weather retry patch identity/idempotence.
[`test-coreelec-artifacts.sh`](../../tests/test-coreelec-artifacts.sh#L1224-L1643)
[`test-coreelec-artifacts.sh`](../../tests/test-coreelec-artifacts.sh#L1929-L2042)

### 2.4 Current artifact validation baseline

The existing artifact library accepts `id|version|https-url|sha256`, validates
the field grammar, requires HTTPS and a 64-hex SHA-256, rejects duplicate IDs,
downloads with HTTPS/TLS constraints and retries, hashes the bytes, rejects
unsafe ZIP names and multiple roots, and verifies `addon.xml` ID/version. It
does not resolve upstream releases, build patched ZIPs, record patch
provenance, validate the transitive dependency graph, or create update PRs.
[`coreelec-artifacts.sh`](../../lib/coreelec-artifacts.sh#L40-L197)

The test suite covers manifest sequencing, record grammar, checksum and
manifest mismatches, multiple roots, path traversal, absolute paths, duplicate
IDs, use of manifest identity rather than ZIP-root identity, selection from
the lock, remote revalidation, transaction ordering, and rollback behavior.
[`test-coreelec-artifacts.sh`](../../tests/test-coreelec-artifacts.sh#L112-L428)
[`test-coreelec-artifacts.sh`](../../tests/test-coreelec-artifacts.sh#L1673-L1928)
[`test-coreelec-artifacts.sh`](../../tests/test-coreelec-artifacts.sh#L2430-L2518)

These are migration inputs and regression cases, not proof that the proposed
supply chain already exists.

## 3. Established external facts

### 3.1 GitHub release discovery is metadata-driven, not a version solver

- `GET /repos/{owner}/{repo}/releases/latest` returns the most recent published
  release that is neither a draft nor a prerelease. GitHub sorts this result by
  `created_at`; for a release, that is the date of the commit used for the
  release, not the draft or publication date. It therefore must not be
  interpreted as “greatest semantic version.”
  [GitHub REST — Get the latest release](https://docs.github.com/en/rest/releases/releases#get-the-latest-release)
- `GET /repos/{owner}/{repo}/releases` does not include plain Git tags that have
  no Release object. Published releases are public, while draft releases are
  listed only for callers with push access. The endpoint defaults to 30 results
  and allows at most 100 per page.
  [GitHub REST — List releases](https://docs.github.com/en/rest/releases/releases#list-releases)
- A publisher can set `make_latest` when creating or updating a release.
  `make_latest` accepts `true`, `false`, or `legacy`; the `legacy` behavior uses
  creation date and a higher semantic version. “Latest” is consequently
  publisher-influenced metadata, not an immutable independent calculation.
  [GitHub REST — Create a release](https://docs.github.com/en/rest/releases/releases#create-a-release)
- GitHub GraphQL exposes release fields including `isDraft`, `isPrerelease`,
  `isLatest`, `immutable`, `tagCommit`, and paginated `releaseAssets`. GitHub
  requires `first` or `last` on connections, with values from 1 through 100.
  [GitHub GraphQL reference](https://docs.github.com/en/graphql/reference)
  [GitHub GraphQL limits](https://docs.github.com/en/graphql/overview/rate-limits-and-query-limits-for-the-graphql-api)

The supplied `weather.ha` counterexample is verified. On 2026-09-18, the
first-party API returned release `0.0.6.6` with name `0.0.6.6 Beta`,
`draft=false`, `prerelease=false`, `isLatest=true`, `immutable=false`, and no
attached assets. Tag `0.0.6.6` resolved to commit
`396e91fc069f6af0172167c6f6d15e1d0201536d`.
[REST release API](https://api.github.com/repos/Eugeniusz-Gienek/kodi_weather_ha/releases/latest)
[GraphQL API](https://api.github.com/graphql)
[Git ref API](https://api.github.com/repos/Eugeniusz-Gienek/kodi_weather_ha/git/ref/tags/0.0.6.6)

**Conclusion:** GitHub's `prerelease` flag is useful evidence, but it is not a
sufficient semantic stability policy. A release name can say “Beta” while the
publisher leaves `prerelease` false.

### 3.2 Release assets, generated source archives, and immutability

- Release-asset metadata includes numeric ID, node ID, name, size,
  `created_at`, `updated_at`, browser download URL, and a nullable
  algorithm-qualified `digest`.
  [GitHub REST — Get a release asset](https://docs.github.com/en/rest/releases/assets#get-a-release-asset)
- Requesting an asset endpoint with `Accept: application/octet-stream` may
  return either a `200` byte stream or a `302` redirect; clients must handle
  both.
  [GitHub REST — Get a release asset](https://docs.github.com/en/rest/releases/assets#get-a-release-asset)
- GitHub's generated release source ZIP and tarball are created on request and
  are not attached release assets. `gh release verify-asset` cannot verify
  them.
  [GitHub — Verifying the integrity of a release](https://docs.github.com/en/code-security/how-tos/secure-your-supply-chain/secure-your-dependencies/verify-release-integrity)
- For an ordinary mutable release, the REST API permits release updates and
  asset deletion. Uploading another asset with an existing filename fails
  until the old asset is deleted, after which a new asset object can use that
  filename. A tag/name URL is therefore not sufficient byte identity without a
  retained digest.
  [GitHub REST — Update a release](https://docs.github.com/en/rest/releases/releases#update-a-release)
  [GitHub REST — Delete a release asset](https://docs.github.com/en/rest/releases/assets#delete-a-release-asset)
  [GitHub REST — Upload a release asset](https://docs.github.com/en/rest/releases/assets#upload-a-release-asset)
- An immutable GitHub release locks its tag target and attached assets.
  Release title, notes, prerelease status, and latest status remain editable.
  GitHub also creates a release attestation covering the tag, commit, and
  release assets. If the immutable release is deleted, its tag can then be
  deleted, but the tag name cannot be reused.
  [GitHub — Immutable releases](https://docs.github.com/en/code-security/concepts/supply-chain-security/immutable-releases)

On 2026-09-18, CoreELEC release `21.3-Omega` was an ordinary
`immutable=false` release. Its
`CoreELEC-Amlogic-ng.arm-21.3-Omega-Generic.img.gz` asset had ID `312495762`
and API-reported digest
`sha256:9edf06e752ed285e11a565584a2369a39b734df56bd0852ce37eee3d9ea9d16b`.
[CoreELEC release API](https://api.github.com/repos/CoreELEC/CoreELEC/releases/tags/21.3-Omega)
[CoreELEC asset API](https://api.github.com/repos/CoreELEC/CoreELEC/releases/assets/312495762)

**Conclusion:** record the exact downloaded-byte SHA-256 independently even
when GitHub supplies a digest. Also retain release ID, asset ID, tag, resolved
commit, observed mutability flags, timestamps, and retrieval URL as provenance.
For authenticated asset retrieval, follow the documented `200`/`302`
behavior, but do not forward authorization across an unrelated redirect
origin.

### 3.3 Kodi repository and installation behavior

Kodi's official repository model consists of:

- an `addons.xml` index;
- a repository “checksum”/change marker;
- a `datadir` containing packages conventionally located at
  `/addon.id/addon.id-x.y.z.zip`; and
- optional package hashes selected by the repository's `<hashes>` value.

[Kodi Wiki — Add-on repositories](https://kodi.wiki/view/Add-on_repositories)

Important integrity distinctions:

- The repository `checksum` is historically named. By default it is a change
  detector and need not be a cryptographic checksum; it only has to change when
  the index changes.
  [Kodi Wiki — `checksum`](https://kodi.wiki/view/Add-on_repositories#checksum)
- Kodi Omega source supports a `verify` attribute on the repository checksum.
  When configured with a recognized digest type, Kodi calculates that digest
  over the downloaded index and rejects a mismatch.
  [Kodi Omega `Repository.cpp` at verified commit](https://github.com/xbmc/xbmc/blob/f8815ee40f49a700c047982d752be4b2a61420e2/xbmc/addons/Repository.cpp)
- With package hashes enabled, Kodi resolves a hash from the
  `content-{algorithm}` response header or a sidecar
  `.<algorithm>` file, hashes the downloaded package, and rejects a mismatch
  before installation. Kodi warns that MD5 is broken and protects only against
  accidental corruption.
  [Kodi Omega `Repository.cpp` at verified commit](https://github.com/xbmc/xbmc/blob/f8815ee40f49a700c047982d752be4b2a61420e2/xbmc/addons/Repository.cpp)
  [Kodi Omega `AddonInstaller.cpp` at verified commit](https://github.com/xbmc/xbmc/blob/f8815ee40f49a700c047982d752be4b2a61420e2/xbmc/addons/AddonInstaller.cpp)
- “Install from ZIP” is materially different from a repository install. Kodi
  requires exactly one top-level directory and a loadable `addon.xml`, then
  installs without a repository object. The repository-provided package hash
  path therefore does not authenticate an arbitrary manually supplied ZIP.
  [Kodi Omega `AddonInstaller.cpp` at verified commit](https://github.com/xbmc/xbmc/blob/f8815ee40f49a700c047982d752be4b2a61420e2/xbmc/addons/AddonInstaller.cpp)
- The add-on manifest is authoritative for add-on ID, version, dependencies,
  and platform compatibility. Kodi's source requires non-empty ID and version,
  parses dependency declarations, and constructs the conventional repository
  ZIP path from ID and version. The official structure documentation says
  `addon.xml` resides at the root of the add-on directory and the installed
  directory is placed under `.kodi/addons/`.
  [Kodi Omega `AddonInfoBuilder.cpp` at verified commit](https://github.com/xbmc/xbmc/blob/f8815ee40f49a700c047982d752be4b2a61420e2/xbmc/addons/addoninfo/AddonInfoBuilder.cpp)
  [Kodi Wiki — Add-on structure](https://kodi.wiki/view/Add-on_structure)

Kodi orders add-on versions with `CAddonVersion`, a Debian-style component
comparison with epoch and revision handling. Numeric runs compare numerically,
`~` sorts before the corresponding final version, and local Kodi suffixes such
as `+matrix.1` participate in ordering. This is not Semantic Versioning.
[Kodi Omega `AddonVersion.cpp` at verified commit](https://github.com/xbmc/xbmc/blob/f8815ee40f49a700c047982d752be4b2a61420e2/xbmc/addons/AddonVersion.cpp)
[Kodi Omega version tests at verified commit](https://github.com/xbmc/xbmc/blob/f8815ee40f49a700c047982d752be4b2a61420e2/xbmc/addons/test/TestAddonVersion.cpp)

CoreELEC 21's official add-on packaging script reads the add-on version from
`addon.xml`, creates a ZIP whose top-level path is the add-on ID, and, for its
Jenkins bundle, emits a SHA-256 sidecar. This establishes CoreELEC build
behavior, not a guarantee that every third-party ZIP follows the same naming or
publishing process.
[CoreELEC 21 `install_addon` at verified commit](https://github.com/CoreELEC/CoreELEC/blob/15970b8e469b8e299a8947b1751593bdaf53ed82/scripts/install_addon)

**Conclusion:** a supply-chain workflow should validate ZIP structure and
manifest identity itself, verify the complete dependency closure before device
mutation, and never treat “Kodi can unzip it” or ZIP CRC32 as cryptographic
authenticity.

### 3.4 Checksums, signatures, attestations, and what they prove

- The ZIP format requires CRC32 integrity data for each member and optionally
  permits digital signatures. CRC32 is an archive-integrity mechanism, not a
  cryptographic publisher-authentication claim.
  [PKWARE APPNOTE 6.3.10, sections 4.1.5–4.1.6](https://pkware.cachefly.net/webdocs/casestudies/APPNOTE.TXT)
- GitHub artifact attestations cryptographically bind an artifact subject to
  provenance such as repository, workflow, commit SHA, environment, and
  triggering event. GitHub explicitly warns that an attestation does not
  guarantee an artifact is secure; consumers still need a verification policy.
  [GitHub — Artifact attestations](https://docs.github.com/en/actions/concepts/security/artifact-attestations)
- GitHub documents the permissions for a binary attestation job as
  `contents: read`, `id-token: write`, and `attestations: write`.
  [GitHub — Using artifact attestations](https://docs.github.com/en/actions/how-tos/secure-your-work/use-artifact-attestations/use-artifact-attestations)
- GitHub states that artifact attestations alone provide SLSA v1.0 Build Level
  2; an appropriately designed vetted reusable workflow can support Build Level
  3.
  [GitHub — Artifact attestations](https://docs.github.com/en/actions/concepts/security/artifact-attestations)
- OIDC lets a job request a GitHub identity token whose claims an external
  provider validates before issuing its own short-lived credential. The
  external trust relationship and claim policy provide authorization;
  `id-token: write` alone does not authorize access to an external service.
  [GitHub — OpenID Connect](https://docs.github.com/en/actions/concepts/security/openid-connect)

**Conclusion:** distinguish:

1. hash comparison — exact-byte integrity against an expected digest;
2. signature or attestation verification — a cryptographic statement from an
   identified signer/provenance system;
3. reproducibility — independent builds produce identical bytes; and
4. security review — an assessment of whether the inputs or behavior are safe.

None substitutes for all the others. An attestation over the final patched ZIP
does not by itself preserve the upstream archive digest or ordered patch
digests, so those provenance elements remain separate.

### 3.5 GitHub Actions trust and publication boundaries

- GitHub creates a repository-scoped `GITHUB_TOKEN` for every job, and actions
  can read it through `github.token` even when it is not explicitly passed.
  [GitHub — `GITHUB_TOKEN`](https://docs.github.com/en/actions/concepts/security/github_token)
- Once a workflow or job supplies any `permissions` entries, omitted
  `GITHUB_TOKEN` scopes are set to `none`. Relevant scopes for this problem
  include `contents`, `pull-requests`, `attestations`, and `id-token`.
  [GitHub — Workflow permissions](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#permissions)
- A fork `pull_request` workflow runs the pull request merge-commit code with a
  read-only token, withheld secrets, and fork approval protections.
  `pull_request_target` instead runs default-branch workflow code with the base
  repository's token and secrets. Fetching PR-controlled code or artifacts and
  then executing their build scripts, tests, dependencies, configuration, or
  Makefiles in a privileged context creates the documented “pwn request”
  condition.
  [GitHub — Securely using `pull_request_target`](https://docs.github.com/en/actions/reference/security/securely-using-pull_request_target)
- GitHub's public-repository default `pull_request_target` policy was in
  evaluation mode on the research date and the documentation scheduled
  enforcement for affected repositories on 2026-11-02.
  [GitHub — Default `pull_request_target` policy](https://docs.github.com/en/actions/reference/security/securely-using-pull_request_target#default-policy-for-pull_request_target)
- GitHub recommends pinning third-party actions to a full-length commit SHA and
  says this is currently the only immutable way to consume an action. The SHA
  should be verified as belonging to the action's repository.
  [GitHub — Secure use of third-party actions](https://docs.github.com/en/actions/reference/security/secure-use#using-third-party-actions)
- Creating and merging a pull request are separate REST operations. A workflow
  can be designed with branch/PR creation permission but no merge or deployment
  operation.
  [GitHub REST — Pull requests](https://docs.github.com/en/rest/pulls/pulls)

**Conclusion:** discovery and building should run from trusted
`schedule`/`workflow_dispatch` code with read-only permissions. Any branch/PR
publication should be a separately permissioned job. The workflow should have
no deployment credential, environment, device access, auto-merge operation, or
execution of untrusted PR content.

### 3.6 Scheduling, concurrency, caching, and API limits

- Scheduled workflows use UTC cron, must exist on the default branch, execute
  the default-branch workflow, and can be delayed or dropped during periods of
  high load. A schedule is therefore a discovery trigger, not a guaranteed
  timer.
  [GitHub — Scheduled workflows](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#onschedule)
- A manually runnable workflow must define `workflow_dispatch` on the default
  branch. GitHub supports invocation from the UI, CLI, and REST API, and permits
  selection of another ref for the run.
  [GitHub — Manually running a workflow](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow)
- A concurrency group allows at most one running job/workflow. The default
  `queue: single` keeps only one pending run and replaces the older pending run;
  `queue: max` allows up to 100 pending runs and cannot be combined with
  `cancel-in-progress: true`. Group names are case-insensitive and
  repository-wide, and execution order is not guaranteed.
  [GitHub — Workflow concurrency](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency)
- Cache lookup can restore prefix matches and `restore-keys`, not only exact
  keys. Fork pull requests can read caches available to their base branch.
  GitHub warns not to store credentials or other sensitive data in caches.
  [GitHub — Dependency caching](https://docs.github.com/en/actions/reference/workflows-and-actions/dependency-caching)
- REST limits are 60 unauthenticated requests per hour per IP, generally 5,000
  authenticated-user requests per hour, and 1,000 `GITHUB_TOKEN` requests per
  hour per repository. GitHub documents `x-ratelimit-reset`, `retry-after`,
  bounded concurrency, and increasing backoff behavior for rate-limit handling.
  GraphQL uses a separate point budget and requires pagination on connections.
  [GitHub REST rate limits](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api)
  [GitHub GraphQL limits](https://docs.github.com/en/graphql/overview/rate-limits-and-query-limits-for-the-graphql-api)

**Conclusion:** caches are disposable acceleration, not provenance. Cache keys
should include every content-affecting digest, and restored inputs and outputs
should still be rehashed.

### 3.7 Reproducible patched ZIPs

- ZIP records member order and per-entry metadata including timestamps,
  compression method, platform/file attributes, comments, and optional extra
  fields.
  [PKWARE ZIP APPNOTE](https://pkware.cachefly.net/webdocs/casestudies/APPNOTE.TXT)
- Reproducible Builds identifies modification times, filesystem-dependent
  ordering, permissions, owner/group data, and ZIP extra fields as common
  reproducibility hazards.
  [Reproducible Builds — Archive metadata](https://reproducible-builds.org/docs/archives/)
- Python's `zipfile` exposes the compression method, compression level, ZIP64
  behavior, and timestamp constraints. ZIP timestamps are bounded to
  1980-01-01 through 2107-12-31; out-of-range values are clipped only when
  `strict_timestamps=False`.
  [Python `zipfile`](https://docs.python.org/3/library/zipfile.html)

**Conclusion:** reproducibility requires an explicit canonical recipe. At
minimum it should fix the tool/runtime version, normalized relative names,
member ordering, directory-entry policy, timestamps, permissions, symlink and
special-file policy, extra fields/comments, compression implementation and
level, ZIP64 behavior, and output root. Two clean builds should produce the
same final SHA-256.

## 4. Corrections and qualifications to the supplied output

1. **Kodi repository “checksum” is not automatically integrity protection.**
   The default field is a change token. Cryptographic index verification needs
   an explicit supported `verify` algorithm; package-byte verification needs
   `<hashes>` and a valid response header or sidecar hash.
2. **Manual ZIP installation is not equivalent to repository installation.**
   Kodi validates the single-root/add-on-description shape, but no
   repository-supplied expected digest is available in that path. Independent
   digest verification must occur before installation.
3. **ZIP CRC32 is not a cryptographic authenticity mechanism.** It detects
   corruption but should not be described as a signature or trusted checksum.
4. **GitHub `latest` is not “highest version.”** It is based on release
   metadata and `created_at`, and publishers can influence latest designation.
5. **GitHub's asset `digest` is nullable.** Its presence is corroborating
   evidence, not a reason to omit the catalog's own expected SHA-256.
6. **Generated source archives are a distinct artifact class.** They are
   produced on request, are not attached release assets, and cannot be checked
   with `gh release verify-asset`.
7. **Attestation does not mean safe.** It proves a signed provenance statement
   subject to verification policy; it does not assess upstream code or patch
   safety.
8. **The 41-artifact count, category totals, moving-branch list, three actual
   archive-root exceptions, and four patch groups are repository facts, not external
   claims.** Section 2 validates them against the lock, inventory, tests, and
   current transformer.

## 5. Candidate recommendations

The following are recommendations supported by the facts above, not yet final
policy:

1. Implement source-specific discovery adapters: GitHub Releases, Git
   tags/commits, and Kodi-style repository indexes are different publication
   systems.
2. Apply stable-first policy using all first-party signals. Treat a conflict
   such as `prerelease=false` plus “Beta” in the release name as requiring
   explicit review, not automatic stable promotion.
3. Prefer attached assets with immutable identity when available. Otherwise
   resolve tags/branches to commit IDs, record the exact retrieval form, and
   always retain an independently computed SHA-256.
4. Separate upstream-byte digest, each ordered patch digest, canonical
   patch-set digest, immutable recipe identity, and final ZIP digest.
5. Validate the ZIP's sole top-level directory, `addon.xml` ID/version,
   dependency closure, platform constraints, and expected output root before
   publication.
6. Build twice in clean environments and require identical final SHA-256.
7. Pin all actions and reusable workflows to verified full commit SHAs.
8. Keep discovery/build read-only; grant only narrowly scoped branch/PR write
   permission to a publication job.
9. Do not build untrusted PR content under `pull_request_target`,
   `workflow_run`, or another privileged event.
10. Open or refresh evidence-rich pull requests only. Do not auto-merge and do
    not expose deployment, environment, or device credentials. Candidate PR
    evidence includes old/new versions, source and release identities,
    stability classification and exception status, resolved commit, upstream
    digest, ordered patch digests and patch-set digest, final digest,
    dependency/catalog diff, two-build reproducibility result, validation/test
    results, attestation result when used, workflow run URL, and an explicit
    statement that no deployment occurred.
11. If attestations are generated, verify them in CI but retain the independent
    upstream/patch/final digest chain as the catalog's provenance record.
12. Use per-Artifact concurrency and immutable per-candidate branches. An exact
    rerun reuses its PR; a different final digest receives a separate branch
    and PR. Do not infer ordering from GitHub's concurrency queue.

## 6. Primary-source URL index

- GitHub releases REST:
  <https://docs.github.com/en/rest/releases/releases>
- GitHub release assets REST:
  <https://docs.github.com/en/rest/releases/assets>
- GitHub immutable releases:
  <https://docs.github.com/en/code-security/concepts/supply-chain-security/immutable-releases>
- GitHub release integrity verification:
  <https://docs.github.com/en/code-security/how-tos/secure-your-supply-chain/secure-your-dependencies/verify-release-integrity>
- GitHub Actions token:
  <https://docs.github.com/en/actions/concepts/security/github_token>
- GitHub `pull_request_target` security:
  <https://docs.github.com/en/actions/reference/security/securely-using-pull_request_target>
- GitHub artifact attestations:
  <https://docs.github.com/en/actions/concepts/security/artifact-attestations>
- GitHub OIDC:
  <https://docs.github.com/en/actions/concepts/security/openid-connect>
- GitHub workflow concurrency:
  <https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency>
- GitHub cache behavior:
  <https://docs.github.com/en/actions/reference/workflows-and-actions/dependency-caching>
- GitHub REST rate limits:
  <https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api>
- GitHub GraphQL limits:
  <https://docs.github.com/en/graphql/overview/rate-limits-and-query-limits-for-the-graphql-api>
- Kodi add-on repositories:
  <https://kodi.wiki/view/Add-on_repositories>
- Kodi add-on structure:
  <https://kodi.wiki/view/Add-on_structure>
- Kodi Omega repository implementation:
  <https://github.com/xbmc/xbmc/blob/f8815ee40f49a700c047982d752be4b2a61420e2/xbmc/addons/Repository.cpp>
- Kodi Omega installer implementation:
  <https://github.com/xbmc/xbmc/blob/f8815ee40f49a700c047982d752be4b2a61420e2/xbmc/addons/AddonInstaller.cpp>
- Kodi Omega manifest implementation:
  <https://github.com/xbmc/xbmc/blob/f8815ee40f49a700c047982d752be4b2a61420e2/xbmc/addons/addoninfo/AddonInfoBuilder.cpp>
- Kodi Omega add-on version ordering:
  <https://github.com/xbmc/xbmc/blob/f8815ee40f49a700c047982d752be4b2a61420e2/xbmc/addons/AddonVersion.cpp>
- CoreELEC 21 add-on packaging:
  <https://github.com/CoreELEC/CoreELEC/blob/15970b8e469b8e299a8947b1751593bdaf53ed82/scripts/install_addon>
- PKWARE ZIP specification:
  <https://pkware.cachefly.net/webdocs/casestudies/APPNOTE.TXT>
- Python `zipfile`:
  <https://docs.python.org/3/library/zipfile.html>
- Reproducible Builds archive guidance:
  <https://reproducible-builds.org/docs/archives/>

## 7. Questions resolved by the final decision

The final answers are recorded in
[`2026-09-18-addon-update-patch-supply-chain.md`](2026-09-18-addon-update-patch-supply-chain.md).

- No general claim is made here that upstream artifacts are signed. For each
  upstream, signature availability and verification procedure must be
  established from that upstream's first-party publication process; absence of
  a GitHub asset digest or attestation is not itself proof that no other
  signature mechanism exists.
- CoreELEC's official wiki page retrieved during this pass contained
  insufficient detail for installation semantics, so the CoreELEC-specific
  findings above rely on its official source and release API. Kodi runtime
  behavior is grounded in the Kodi Omega source used by CoreELEC 21.
- The decision selects immutable per-candidate branches, exact-rerun reuse,
  per-Artifact concurrency, source-specific adapters, deterministic
  repository-owned mirroring, required attestations for repository-built
  outputs, and rendered evidence values. Exact production file names and
  pinned tool versions remain build-issue details.
- Each source family receives an explicit stable-channel rule. GitHub Release
  flags, repository-index membership, version syntax, release names, and
  publisher documentation can disagree; this record establishes that the
  automation must expose such disagreement rather than silently deciding it.
- Mutable, generated, repacked, and patched bytes are retained as
  repository-owned content-addressed Release assets. A digest still does not
  preserve availability; deletion remains a catalog failure.
