# Add-on update and patch supply-chain contract

Date: 2026-09-18

Ticket: [Define the stable add-on update and patch supply chain](https://github.com/jbruns/tv/issues/47)

Status: **Accepted autonomous decision**

## 1. Decision

The repository owns a stable-first, fail-closed supply chain that discovers
source-specific add-on candidates, establishes their exact origin bytes,
validates the candidate manifest and dependency closure, reproducibly creates
any required final ZIP, publishes repository-owned distribution bytes when
availability requires it, and proposes an evidence-rich catalog pull request.
It never merges, deploys, contacts a Device, or executes upstream code.

The contract distinguishes:

- **origin**: the publisher, publication mechanism, resolved retrieval
  identity, and exact bytes received from that source;
- **distribution**: the exact final ZIP that the Reconciler later retrieves;
- **recipe**: deterministic transformations and verification from origin to
  distribution; and
- **proposal**: an immutable candidate branch and human-reviewed catalog PR.

Every catalog entry retains original upstream provenance. A digest proves byte
identity but not availability, authorship, safety, or review.

## 2. Source adapter contracts

Adapters return a normalized discovery snapshot. They do not select a
universal “latest” version.

### 2.1 GitHub attached release assets

The adapter:

1. enumerates all relevant Release pages;
2. excludes drafts;
3. retains `prerelease`, `immutable`, release ID, asset ID, tag, tag commit,
   names, timestamps, asset size, URL, and any API digest;
4. applies repository-specific stability signals; and
5. downloads through the documented asset API `200`/`302` behavior without
   forwarding authorization to an unrelated redirect origin.

An untouched stable attached asset may be distributed directly only while the
exact asset remains retrievable and its downloaded bytes independently match
the committed SHA-256. GitHub's nullable digest is corroborating evidence.

Primary sources:

- [GitHub Releases REST](https://docs.github.com/en/rest/releases/releases)
- [GitHub release assets REST](https://docs.github.com/en/rest/releases/assets)
- [GitHub immutable releases](https://docs.github.com/en/code-security/concepts/supply-chain-security/immutable-releases)
- [GitHub release integrity](https://docs.github.com/en/code-security/how-tos/secure-your-supply-chain/secure-your-dependencies/verify-release-integrity)

### 2.2 GitHub tag, commit, and branch archives

The adapter resolves a tag or branch to a commit before retrieval and records
both the requested ref and resolved commit. Generated codeload archives are not
attached release assets and are not treated as byte-stable publication.
A mutable branch URL, tag-generated archive, or commit-generated archive must
be deterministically repacked and published as a repository-owned release
asset before proposal.

This rule applies to ART-009 `weather.ha`: its upstream tag and commit remain
the origin, but codeload bytes are never the catalog distribution. The
repository applies the accepted patches, normalizes the root, creates the
deterministic final ZIP, attests it, and mirrors it before opening the PR.

### 2.3 Kodi and Jurialmunkey repositories

The adapter retrieves the first-party `addons.xml`, its repository change
marker, configured package-hash metadata when present, and the package from
the declared `datadir`. It records the index identity and package URL, and it
still computes SHA-256 independently. Kodi's historical `checksum` may be only
a change token; cryptographic verification is claimed only when the repository
declares and passes a supported verification algorithm.

Candidate ordering and dependency-floor comparison use Kodi
`CAddonVersion`, not SemVer. The algorithm lowercases versions, compares epoch,
upstream component, then revision; numeric runs compare numerically; `~` sorts
before the corresponding final version; and suffixes such as `+matrix.1`
participate in component ordering. Representative required relations are:

```text
1.0.0~beta < 1.0.0
1.16.0 < 1.16.0+matrix.1
1.16.0+matrix.1 < 1.16.0+matrix.2
21.3.2 < 21.3.2.1
```

Primary sources:

- [Kodi add-on repositories](https://kodi.wiki/view/Add-on_repositories)
- [Kodi Omega repository implementation](https://github.com/xbmc/xbmc/blob/f8815ee40f49a700c047982d752be4b2a61420e2/xbmc/addons/Repository.cpp)
- [Kodi Omega `CAddonVersion`](https://github.com/xbmc/xbmc/blob/f8815ee40f49a700c047982d752be4b2a61420e2/xbmc/addons/AddonVersion.cpp)
- [Kodi Omega version tests](https://github.com/xbmc/xbmc/blob/f8815ee40f49a700c047982d752be4b2a61420e2/xbmc/addons/test/TestAddonVersion.cpp)

### 2.4 CoreELEC indexes

The adapter binds discovery to CoreELEC release, device family, architecture,
repository index, package revision, manifest, and package bytes. A package for
another CoreELEC release or architecture is ineligible. The CoreELEC package
revision remains part of the Kodi version.

Primary sources:

- [CoreELEC 21 add-on packaging](https://github.com/CoreELEC/CoreELEC/blob/15970b8e469b8e299a8947b1751593bdaf53ed82/scripts/install_addon)
- [Kodi Omega manifest parser](https://github.com/xbmc/xbmc/blob/f8815ee40f49a700c047982d752be4b2a61420e2/xbmc/addons/addoninfo/AddonInfoBuilder.cpp)

## 3. Eligibility and stability

Draft GitHub Releases are never candidates. Stable eligibility requires all
source-specific first-party signals to agree. Signals include API channel
flags, release/tag/version names, repository channel and location, publisher
documentation, and manifest version. Names containing alpha, beta, RC,
preview, pre, dev, nightly, snapshot, or candidate markers are prerelease
signals. Unknown syntax, conflicting signals, or insufficient publisher
metadata yields `manual-review`; it never becomes an automated proposal.

Eligible candidates are ordered with `CAddonVersion`, with deterministic
source identity as a tie-breaker. GitHub “latest,” publication time, lexical
sort, and SemVer libraries are not version solvers.

### 3.1 Prerelease exception

A prerelease is eligible only when default-branch data, authored and reviewed
separately from the update workflow, binds:

- exact Artifact ID and version;
- exact origin adapter and resolved source identity;
- rationale and acceptance-evidence reference;
- approval date;
- merged approval PR and merge commit;
- required CODEOWNERS approval; and
- mandatory `expires_on`, after approval and at most 90 days later.

`review_trigger` is optional and additive; it never replaces expiry. The update
workflow cannot create, edit, or approve its own exception. Scheduled catalog
validation and Reconciler preflight validate the exception. Expiry or binding
mismatch blocks Device mutation even if the final digest still matches.

## 4. Snapshot, identity, digest, and distribution

Discovery records a complete resolved identity immediately before fetch. Bytes
are fetched into an isolated no-network build boundary and rehashed. The
adapter resolves identity again immediately after fetch. Any identity change
blocks the candidate; the workflow does not bless bytes obtained across a
TOCTOU change.

For a new candidate, the independently computed hash establishes the proposed
origin digest. There is no old expected digest to compare. When validating a
committed catalog entry, the Reconciler or validation workflow retrieves the
distribution and compares it to the committed final digest.

Untouched stable attached assets and stable Kodi/CoreELEC repository packages
may remain direct distributions when the exact bytes are independently
digest-pinned and retrievable. The following always require a deterministic,
repository-owned, content-addressed release asset:

- mutable branch URLs;
- generated codeload archives;
- patched Artifacts;
- repacked or root-normalized Artifacts; and
- any other origin that is not byte-stable.

Publication happens before the catalog PR. Prefer one immutable GitHub Release
per candidate/proposal. Where immutable releases are unavailable, record
release and asset IDs, enforce repository never-delete policy, and use the
committed digest for integrity; deletion is an availability failure.
Cleanup may remove only unreferenced candidates after the retention policy
allows it. It must never delete an asset referenced by any catalog commit that
remains supported.

## 5. Catalog example

```yaml
kind: ArtifactCatalog
schema_version: 1
artifacts:
  - id: artifact.kodi.weather.ha
    kind: kodi-addon
    version: 0.0.6.6
    origin:
      adapter: github-tag-archive
      project: Eugeniusz-Gienek/kodi_weather_ha
      tag: 0.0.6.6
      commit: 396e91fc069f6af0172167c6f6d15e1d0201536d
      retrieval_url: https://codeload.github.com/Eugeniusz-Gienek/kodi_weather_ha/zip/refs/tags/0.0.6.6
      mutable: true
      sha256: 2978014d258c01e3b5ce73d2a8a73bb3e7d29e64b4d36ae35a355d5665760ae5
    distribution:
      relation: patched-and-repacked-from-origin
      owner: jbruns/tv
      release_id: 47001
      asset_id: 4700101
      asset: weather.ha-0.0.6.6-0123456789ab.zip
      immutable_release: true
      sha256: 0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef
    release:
      channel: stable
    platforms:
      - coreelec-21-amlogic-ng
    dependencies:
      - id: artifact.kodi.script.module.requests
        minimum_version: 2.27.1
      - id: artifact.kodi.script.module.iso8601
        minimum_version: 0.1.12
      - id: artifact.kodi.script.module.yaml
        minimum_version: 5.3.0
      - id: artifact.kodi.script.module.dateutil
        minimum_version: 2.8.1
    recipe:
      id: build.kodi-addon-deterministic.v1
      sha256: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
      patches:
        - id: PATCH-001
          sha256: bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
        - id: PATCH-002
          sha256: cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
      verification:
        patch_preconditions: exact
        occurrence_counts: exact
        idempotence: required
        wrong_version_refusal: required
        compile_mode: isolated-no-network-no-import-execution
        manifest_and_members: exact
        independent_clean_builds: 2
    attestation:
      required: true
      subject_sha256: 0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef

  - id: artifact.kodi.skin.arctic-fuse-3
    kind: kodi-addon
    version: 3.3.0~rc1
    origin:
      adapter: github-release-asset
      project: jurialmunkey/skin.arctic.fuse.3
      release_id: 3301
      asset_id: 330100
      tag: v3.3.0-rc1
      commit: 3301abc3301abc3301abc3301abc3301abc3301
      retrieval_url: https://github.com/jurialmunkey/skin.arctic.fuse.3/releases/download/v3.3.0-rc1/skin.arctic.fuse.3-3.3.0-rc1.zip
      mutable: false
      sha256: dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd
    distribution:
      relation: direct-origin-bytes
      owner: upstream
      release_id: 3301
      asset_id: 330100
      asset: skin.arctic.fuse.3-3.3.0-rc1.zip
      immutable_release: true
      sha256: dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd
    release:
      channel: prerelease
      exception:
        artifact_id: artifact.kodi.skin.arctic-fuse-3
        version: 3.3.0~rc1
        origin_identity: github-release-asset:3301:330100:3301abc3301abc3301abc3301abc3301abc3301
        rationale: Accepted pilot behavior requires this release candidate.
        acceptance_evidence: evidence/skin-pilot-2026-09-18.json
        approval_pr: 147
        approval_merge_commit: 147abc147abc147abc147abc147abc147abc147a
        codeowners:
          - "@jbruns"
        approved_on: "2026-09-18"
        expires_on: "2026-10-18"
        review_trigger: stable-release-published
    platforms:
      - coreelec-21-amlogic-ng
    dependencies: []
    attestation:
      required: false
```

The first entry demonstrates repository-owned patched/repacked distribution;
the second demonstrates eligible direct upstream distribution plus an exact
prerelease exception. A root-normalized but unpatched entry uses
`repacked-from-origin` and still requires a repository-owned mirror and
attestation.

## 6. Candidate dependency closure

The root dependency set comes from the candidate ZIP's validated `addon.xml`,
never from the current catalog entry being replaced. Each required add-on ID
and minimum version is classified as:

- bundled/system: validate against the target CoreELEC image manifest;
- already satisfied: retain the catalog entry;
- new or raised: discover an eligible candidate and include it in the same
  proposal; or
- unavailable/incompatible/ambiguous: block.

Every newly selected dependency is fetched and its own candidate manifest is
added recursively. The final graph must be complete, acyclic, platform
compatible, digest-pinned, and satisfy every floor under `CAddonVersion`.
Optional dependencies are included only by explicit repository policy.
Artifact closure does not implicitly create Device Resources.

## 7. Deterministic ZIP recipe

The pinned recipe and runtime define:

- normalized UTF-8 relative POSIX member names;
- bytewise lexical member order;
- exactly one output root equal to the manifest add-on ID;
- timestamp `1980-01-01T00:00:00` for every entry;
- directory mode `0755`, ordinary file mode `0644`, and only reviewed
  executable files at `0755`;
- empty archive/member comments and extra fields;
- no owner/group, host-path, or nondeterministic metadata;
- pinned DEFLATE implementation and level 9;
- ZIP64 forbidden unless a later recipe explicitly enables it;
- symlinks and special files forbidden; and
- exact expected manifest and member checks after creation.

Two independent clean builds from rehashed inputs must produce identical ZIP
bytes and SHA-256. Reproducibility failure blocks publication.

## 8. Patch migration

The four existing patch groups move from Device runtime transforms to the
repository build:

| ID | Locked input | Required behavior and verification |
|---|---|---|
| PATCH-001 | `weather.ha` `0.0.6.6` | Change the sole `ha_request_attempts` setting from `int` to `number`; enforce exact occurrence and exact-prepatched idempotence; parse XML |
| PATCH-002 | `weather.ha` `0.0.6.6` | Add `continue` after request fallback; preserve RequestError behavior; exact sequence/count, idempotence, wrong-version refusal, isolated Python bytecode compile |
| PATCH-003 | `script.plexmod` `1.3.19` | Guard `windowutils.HOME` close operations; exact one sequence, wrong-version refusal, isolated Python bytecode compile |
| PATCH-004 | `plugin.video.themoviedb.helper` `6.17.1` | Daemonize Cron/Image threads and abort before `_on_poll()`; exact sequences/counts, exact-prepatched acceptance, partial/different-patch rejection, isolated Python bytecode compile |

Existing rejection, wrong-version, idempotence, and compile tests remain
behavioral-equivalence fixtures. Upstream code is never executed. “Compile”
means parsing or bytecode generation in an isolated no-network process without
import execution. The Device receives only the verified final ZIP and performs
no source patching.

## 9. Workflow architecture and security

Trusted default-branch workflows use `schedule` and `workflow_dispatch`.
There is no `pull_request_target` build and no privileged execution of
PR-controlled code, configuration, actions, dependencies, scripts, or cached
outputs.

Jobs are:

1. **discover** — source API/index reads; `contents: read`;
2. **fetch/validate/build** — isolated, no network after input capture, no
   write token, rehash every transfer/cache boundary, never execute upstream;
3. **attest** — final repository-built subject only; `contents: read`,
   `id-token: write`, `attestations: write`;
4. **publish/propose** — upload the release asset before PR creation and write
   only release/content and pull-request state; no environments, Device
   secrets, deployment credentials, merge, or deployment.

All actions and reusable workflows are pinned to verified full commit SHAs.
Caches are optional acceleration; keys include all content-affecting digests
and restored bytes are rehashed. API pagination, rate-limit headers,
`retry-after`, bounded concurrency, and bounded backoff are explicit.
Scheduled delay or drop is an availability signal, not a false candidate
failure.

Attestation is required for every repository-built, repacked, root-normalized,
or patched final Artifact. It is optional corroboration for untouched direct
upstream bytes. It supplements, and never replaces, origin, patch, recipe, and
final digests or human review.

## 10. Proposal identity and behavior

The candidate key is Artifact ID, version, and final-digest prefix. The branch
is immutable per candidate, for example:

```text
automation/addon/weather.ha/0.0.6.6-0123456789ab
```

Concurrency is per Artifact, not repository-wide. An exact rerun is a no-op or
reuses the existing PR. Automation never force-pushes over human or non-bot
commits. A newer candidate uses a separate branch and PR, links to the older
proposal, and may mark it superseded in comments; automation does not merge or
close human work.

The PR renders actual evidence values: origin and distribution identities,
old/new versions and digests, eligibility and exception binding, manifest
dependency floors, cascaded entries, platform, patch and recipe digests,
two-build hashes, attestation subject, validation results, workflow URL, and
the explicit statement that no merge or deployment occurred.

## 11. Initial migration

The first catalog migration is exactly the 41 `ADDON_ARTIFACT` rows in
`provision.conf`. Derived facts are:

- 41 lock entries;
- 8 moving `master` URLs;
- 3 actual differing archive roots:
  `plugin.service.emby-next-gen`, `resource.font.robotocjksc`, and
  `weather.ha`;
- `script.plexmod/` equals its add-on ID and is not a root override despite
  the four-case configuration comment; and
- 4 patch groups across 3 add-ons.

Migration tooling derives these counts from parsed fixture rows and mappings;
tests do not duplicate unexplained count literals.

## 12. Validation, evidence, and failure

Required automated evidence covers:

- every source adapter, draft exclusion, pagination, ambiguity, and ordering;
- `+matrix`, `~`, epoch/revision, and multi-part numeric Kodi versions;
- pre/post identity changes and new-candidate digest establishment;
- committed distribution re-verification and cache poisoning;
- ZIP traversal, absolute/backslash names, multiple roots, symlinks, special
  files, manifest/member mismatch, platform mismatch, and unsafe metadata;
- candidate-manifest dependency expansion, raised/new cascades, bundled/system
  classification, missing dependencies, cycles, and incompatible floors;
- all existing patch acceptance/rejection/compile behavior;
- two clean deterministic builds, publication, attestation, and orphan
  retention;
- exception binding, separate authorship, CODEOWNERS approval, 90-day maximum,
  scheduled expiry, and Reconciler preflight;
- least permissions, action pinning, no untrusted execution, per-Artifact
  concurrency, exact rerun, human-commit protection, and newer-candidate
  supersession; and
- proof that no noneligible candidate reaches `proposed`.

Any failed or ambiguous gate produces a terminal blocked state. No later
handler runs, no distribution is published, no PR is created, and no Device
mutation is allowed. A missing referenced mirror is an availability failure.

## 13. Milestone integration

The lane begins in parallel after M1. Before live M6 add-on acceptance, the
Artifact builder, origin/distribution provenance, mirror publication,
attestation, catalog/schema validation, exception validation, and Reconciler
preflight must exist. `KodiAddon` consumes only committed final distributions.

Discovery and proposal automation must be accepted before M10. Issue #47 is
completed before issue #46 plan handoff, and #46 receives this contract as an
input; this decision does not start #46. No supply-chain merge may occur during
a bound M10 observation window.

## 14. Rejected alternatives

- Trusting GitHub “latest,” release flags alone, lexical order, or SemVer.
- Treating a digest as an availability mechanism.
- Consuming ART-009 codeload bytes directly.
- Deriving candidate dependencies from the current catalog.
- Accepting prerelease approval without mandatory bounded expiry.
- Letting the update workflow author its own exception.
- Patching on the Device.
- Executing upstream tests/imports/build scripts.
- Building PR-controlled content with `pull_request_target`.
- Repository-wide candidate branch/concurrency.
- Reusing a branch by force-pushing over human work.
- Attestation as a substitute for byte digests or review.
- Auto-merge, auto-close of human work, deployment, or Device credentials.

## 15. Deferred implementation details

Exact production file names, workflow YAML layout, release naming punctuation,
retention duration for unreferenced candidates, canonical patch-manifest
serialization, and the pinned ZIP runtime version are selected in build issues.
They may vary only while preserving every invariant and evidence field above.
