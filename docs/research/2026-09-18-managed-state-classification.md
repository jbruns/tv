# Managed-state classification

Date: 2026-09-18

Ticket: [Classify the legacy managed-state inventory](https://github.com/jbruns/tv/issues/35)

Factual source: [Current managed State Address inventory](2026-09-18-current-managed-state-inventory.md)

## 1. Decision rules

This matrix classifies all 169 provisional inventory rows. The six top-level
roles are exhaustive: **Resource**, **Guard**, **Effect**, **Guided Action**,
**Run Infrastructure**, and **Unmanaged/Inventory Fact**. `Migrate` means
preserve the intentional outcome in the replacement design, not preserve the
shell mechanism. `Retire` means deliberately omit the behavior. `Outside`
means retain or observe the fact outside Reconciler Desired State.

- A physical document that is safely mutable is a Resource. A partial-document
  Resource owns only its declared State Addresses and preserves all other
  content. A whole-file Resource is authoritative for the complete file. Plans
  expose per-setting Changes even when settings share a document Resource.
- `baseline`, `core`, `cec`, `addons`, `services`, `skin`, and `room` survive
  only as familiar selectors/presets. They neither own state nor create partial
  transaction boundaries. Selecting one concern reconciles the complete shared
  document Resource and its dependency closure.
- Profile presence is explicit. A conditional integration Resource is present,
  `desired: absent`, or omitted and unmanaged. Environment-variable presence
  never infers Desired State. All surviving desired values move from shell into
  Profiles, templates, secret references, and the Artifact catalog.
- Independent Verification compares a fresh Observation with Desired State.
  Command success, a successful write, or an Effect completing is not
  Verification. A Health Check reports usability independently of Convergence
  and does not trigger rollback of correctly persisted configuration.
- Platform, model, and release mismatches are non-bypassable Guards.
  `--force-unsupported` is retired.
- One unified Run Infrastructure system owns the Device lock, immutable local
  workspace, remote marker, backups, recovery, finalization, and reports.
  Report facts survive only when they serve a Guard, evidence, Verification,
  recovery, inventory/audit, or troubleshooting purpose.

## 2. Classification matrix

The `IDs` column uses only explicit IDs or inclusive contiguous ranges. Every
range is expanded mechanically in the coverage reconciliation in section 5.

| IDs | Role | Disposition | Proposed ownership boundary | Selector / preset | Key rationale | Verification / health distinction | Downstream finalizer |
|---|---|---|---|---|---|---|---|
| PLAT-001–PLAT-002 | Guard | Migrate | Unified immutable platform/release/model Guard evidence for a Run | all | CoreELEC identity, supported release/platform, and Device model must match before mutation; no force bypass | Fresh pre-mutation Observation; mismatch blocks, not drift | #37 must fix Guard schema and evidence |
| PLAT-003 | Unmanaged/Inventory Fact | Outside | Purpose-driven inventory/troubleshooting facts for kernel and hostname | inventory/audit | Neither fact is Desired State or a convergence criterion | Observation only; never Verification or Health | #37 must decide report evidence schema |
| PLAT-004 | Guard | Migrate | Same unified platform/release Guard as PLAT-001; retire the lifecycle installer's duplicate guard boundary | services | The lifecycle gateway cannot create a second platform policy or bypass | One Guard result reused by dependent Resources | #37 must define Guard reuse |
| PLAT-005 | Guard | Migrate | OpenSSH capability Guard for lifecycle authorized-key representation | services | Capability selects `restrict` or equivalent fail-closed restrictions; it owns no state | Observe before planning the lifecycle gateway; inability to prove capability blocks | #37 must define capability evidence |
| SSH-001–SSH-002 | Unmanaged/Inventory Fact | Outside | Bootstrap operations guide: controller key creation and initial administrator key installation | none | A Manageable Device already has administrator SSH; these operations precede the Reconciler | Successful administrator SSH establishes the boundary, but is not Resource Verification | Documentation-transition ticket must preserve bootstrap steps |
| SSH-003 | Resource | Migrate | Partial managed document/service Resource for `/storage/.cache/services/sshd.conf`; owns only declared hardening addresses | core, baseline | SSH hardening is persistent Device Desired State and must preserve unrelated service content | Verify fresh document Observation and active/reachable sshd after Effect; reconnect alone does not prove every setting | Managed-file and service slice tickets must finalize schema/rollback |
| SSH-004 | Guard | Migrate | Controller transport host-identity Guard using explicit trusted known-hosts input | all | Host authentication is a transport safety prerequisite, not Device Desired State | Fail closed before Observation/mutation; not a Health Check | #37 must define inventory/transport binding |
| CORE-001–CORE-005 | Resource | Migrate | `KodiGuiSettings` partial-document Resource for locale and timezone settings in `guisettings.xml` | core, baseline | One shared physical document owns all surviving declared GUI settings | Fresh per-setting JSON-RPC/file Observation after Kodi Effect; timezone also depends on coordinated cache Resource | Kodi settings slice must finalize canonicalization |
| CORE-006 | Resource | Migrate | `CoreElecTimezone` partial-document Resource for `/storage/.cache/timezone` | core, baseline | CoreELEC needs coordinated cache state in addition to Kodi GUI settings | Verify the declared cache value independently after `tz-data.service` restart | Managed-file/service slice must finalize atomic write and rollback |
| CORE-007 | Unmanaged/Inventory Fact | Migrate | Derived Verification evidence for `CoreElecTimezone`: `/etc/localtime` representation and current offset | core, baseline | CoreELEC may materialize a symlink or copy; the Reconciler must not claim ownership of either representation | Evidence contributes to timezone Verification; it is not a Resource or separate Health Check | Timezone implementation ticket must formalize accepted representations |
| CORE-008–CORE-019 | Resource | Migrate | `KodiGuiSettings` partial-document Resource for update, input, file-list, library, and video settings | core, baseline | Surviving intentional values move to Profile data; shared document means one ownership boundary | Every declared setting needs honest independent Observation, including currently unverified CORE-008 and CORE-018–019 | Kodi settings slice must add missing verification |
| CORE-020–CORE-027 | Resource | Migrate | `KodiGuiSettings` partial-document Resource for event/web-service settings and typed secret references | core, services, baseline | Web access is persistent configuration; secrets remain references and never report literals | Per-setting verification where observable plus authenticated endpoint evidence; reachability alone is not sufficient | Kodi settings/reporting tickets must define secret-safe evidence |
| CORE-028–CORE-029 | Resource | Migrate | `KodiGuiSettings` partial-document Resource for audio device and passthrough-device Intent | core, baseline | Stable Profile Intent resolves against Device enumeration; opaque representation is not authored policy | Verify resolved representation from a fresh Observation; missing/ambiguous capability blocks planning | Kodi settings slice must finalize Intent resolver |
| CEC-001–CEC-005 | Resource | Migrate | One `KodiCecSettings` partial-document Resource owning exactly five settings in the exactly-one discovered CEC XML | cec, baseline | Adapter filename is discovered, while the five owned addresses are fixed and all other XML is preserved | Verify five fresh values in the same uniquely discovered document after Kodi Effect | CEC slice must finalize discovery ambiguity handling |
| ART-001–ART-041 | Resource | Migrate | One `KodiAddon` Resource per explicit add-on; each owns directory, version, enabled state, and final content digest/signatures | addons plus dependent core/services/skin selectors | All 41 required add-ons are explicit and digest-pinned; dependencies may be catalog-derived, but every resolved Plan names all Resources and Artifacts | Fresh directory/version/enabled/final-content Observation; install command success is insufficient | #38 and the stable supply-chain ticket must finalize catalog/dependency/provenance contracts |
| ADDON-001 | Resource | Migrate | Enabled-state address folded into each corresponding `KodiAddon` Resource ART-001–ART-041 | addons | Enablement is part of each add-on's cohesive convergence boundary, not a collection-wide side effect | Re-query each add-on after enablement and relevant Kodi Effect | Add-on slice must define registry Observation/rollback |
| ADDON-002 | Unmanaged/Inventory Fact | Outside | Inventory/audit observation of undeclared installed user add-ons | inventory/audit | Undeclared add-ons are Unmanaged State; omission never means removal | Surface IDs without treating them as drift or failed Verification | Inventory/reporting ticket must define purpose-driven output |
| ADDON-003 | Unmanaged/Inventory Fact | Retire | No Desired State owner; remove `ADDON_UNMANAGED_ALLOWED` | none | An acknowledgement list changes report cosmetics without changing ownership; unmanaged is unmanaged | Inventory may report all undeclared add-ons uniformly | Profile migration ticket must remove the field |
| PATCH-001–PATCH-004 | Run Infrastructure | Migrate | Repository Artifact build/provenance pipeline; runtime transforms retire, while the owning `KodiAddon` receives a reproducibly prebuilt final Artifact | none (GitHub Actions proposal workflow) | Compatibility patches are supply-chain inputs, not on-Device patch Resources | CI verifies upstream, patch-set, build, and final digests; Device Verification checks final digest/signatures | New stable add-on supply-chain ticket |
| SVC-001 | Resource | Migrate | `KodiGuiSettings` owns `weather.addon` with an explicit Weather integration Resource dependency | services, baseline | Selector choice is GUI Desired State in the shared document; configuration is never inferred from environment presence | Verify persisted selector independently; Weather availability is a separate Health Check | Kodi/Weather slices must finalize dependency |
| SVC-002–SVC-005 | Resource | Migrate | Partial document Resource for repository-owned `addon_data/weather.ha/settings.xml` addresses | services, baseline | Repository owns these declared settings while preserving unrelated add-on content | Verify every declared value/presence, including SVC-005; HA/runtime weather availability is separate and cannot roll back converged settings | Weather settings ticket must finalize secret-safe Observation |
| SVC-006–SVC-011 | Resource | Migrate | Partial document Resource for repository-owned NextPVR instance settings | services, baseline | Explicit Resource presence/absence/omission replaces environment-driven inference | Verify all six declared addresses, including protocol/name; backend availability is a separate Health Check | NextPVR settings ticket must finalize instance identity and absence |
| SVC-012–SVC-013 | Resource | Migrate | Partial document Resource for repository-owned TMDb Helper settings | services, baseline | API-key presence is persistent configuration; TMDb has no Guided Action | Fresh secret-safe presence/validity evidence without exposing values | TMDb settings ticket must finalize typed secrets |
| SVC-014–SVC-017 | Unmanaged/Inventory Fact | Retire | PM4K-owned settings remain an observation surface for its Guided Action; no Reconciler ownership | none | Retire all four cleanup mutations unless a reviewed pinned Artifact migration absorbs them | Do not claim convergence from deleting add-on-owned state; a future Artifact digest would be verified by `KodiAddon` | Stable supply-chain ticket may explicitly absorb a migration |
| GUIDE-001–GUIDE-005 | Guided Action | Migrate | PM4K onboarding Action, including capability/UI preconditions and separate token/server-binding observations | services | Interactive account linking and server selection cannot be expressed as repairable Desired State | Report Action readiness/completion evidence; never report it as Resource drift or Verification | Guided Actions ticket must define Action schema and redaction |
| GUIDE-006 | Guided Action | Migrate | Emby onboarding Action with account/handshake/sync observation ladder | services | Human-mediated server/account linking is not Desired State | Preserve the false-success-resistant completion ladder as Action evidence, not Resource Verification | Guided Actions ticket must finalize completion states |
| GUIDE-007 | Unmanaged/Inventory Fact | Migrate | Weather external-availability Health Check associated with the Weather settings Resource | services | Correct persisted configuration can converge while Home Assistant or weather labels are unavailable | Health failure is reported separately and causes no rollback of converged settings | Health/reporting ticket must define status and freshness |
| GUIDE-008 | Unmanaged/Inventory Fact | Migrate | NextPVR external-availability Health Check associated with the NextPVR settings Resource | services | Backend login/channel availability is operational health, not persisted configuration | Health failure is separate from Verification and causes no rollback | Health/reporting ticket must define status and freshness |
| SKIN-001–SKIN-002 | Resource | Migrate | `KodiGuiSettings` owns look-and-feel skin and sound-skin settings | skin, baseline | These are surviving shared GUI document addresses, not a separate skin transaction | Fresh per-setting Observation after Kodi/skin Effects | Kodi settings slice must define skin readiness evidence |
| SKIN-003–SKIN-010 | Resource | Migrate | One partial `ArcticFuseSettings` document Resource owning declared hub and tile addresses | skin, baseline | Current outcomes migrate unchanged as Profile data; unrelated skin settings remain unmanaged | Verify every declared address/absence after Effects, allowing only documented equivalent empty materialization | Skin settings ticket must finalize canonicalization |
| SKIN-011 | Resource | Migrate | Authoritative whole-file Resource for home widget JSON | skin, baseline | Ordered JSON is intentional complete content | Whole-file canonical/digest Verification after Kodi Effect | Skin generated-state ticket must finalize JSON schema |
| SKIN-012 | Resource | Migrate | Authoritative whole-file Resource for TV hub widget JSON | skin, baseline | One Resource per widget file avoids hidden shared ownership | Whole-file canonical/digest Verification | Skin generated-state ticket |
| SKIN-013 | Resource | Migrate | Authoritative whole-file Resource for Movies hub widget JSON | skin, baseline | Current ordered content migrates unchanged as Profile/template data | Whole-file canonical/digest Verification | Skin generated-state ticket |
| SKIN-014 | Resource | Migrate | Authoritative whole-file Resource for power-menu widget JSON | skin, baseline | File content is managed; the actions it exposes do not make reboot a Reconciler Effect | Whole-file canonical/digest Verification | Skin generated-state ticket |
| SKIN-015–SKIN-016 | Resource | Migrate | One authoritative whole-file viewtype source JSON Resource | skin, baseline | The source file, not individual keys or compiled output, is authoritative | Verify entire source file before and after `BuildSkinViews` | Skin generated-state ticket must finalize source template |
| SKIN-017–SKIN-018 | Unmanaged/Inventory Fact | Migrate | Derived Verification evidence produced from the authoritative viewtype source by `BuildSkinViews` | skin, baseline | Generated include must not become a second owner or rollback boundary | Parse compiled expressions as post-Effect evidence; generation command/poll success alone is insufficient | Skin generated-state ticket must finalize predicate |
| SKIN-019 | Resource | Migrate | Authoritative whole-file Resource for `InProgressMovies90Days.xsp` | skin, baseline | Each playlist XML has independent complete-file authority | Whole-file canonical/digest Verification | Skin playlist ticket |
| SKIN-020 | Resource | Migrate | Authoritative whole-file Resource for `InProgressShows90Days.xsp` | skin, baseline | Same | Whole-file canonical/digest Verification | Skin playlist ticket |
| SKIN-021 | Resource | Migrate | Authoritative whole-file Resource for `RecentlyAiredEpisodes30Days.xsp` | skin, baseline | Same | Whole-file canonical/digest Verification | Skin playlist ticket |
| SKIN-022 | Resource | Migrate | Authoritative whole-file Resource for `RecentlyReleasedMoviesCurrentAndPreviousYear.xsp` | skin, baseline | Dynamic year bounds must resolve visibly in the Plan, not hide in code | Verify resolved whole-file content; date input is Plan evidence | Skin playlist ticket must finalize clock binding |
| SKIN-023 | Resource | Migrate | Authoritative whole-file Resource for `TraktPopularTVShows.xsp` | skin, baseline | Persisted query can converge independently of runtime tag population | Whole-file Verification; tag population is health/runtime evidence, not rollback cause | Skin playlist ticket |
| SKIN-024 | Resource | Migrate | Authoritative whole-file Resource for `TraktWeekendBoxOffice.xsp` | skin, baseline | Same | Whole-file Verification distinct from runtime content availability | Skin playlist ticket |
| SKIN-025 | Resource | Migrate | Authoritative whole-file Resource for `NewShows.xsp` | skin, baseline | Current intentional outcome migrates | Whole-file canonical/digest Verification | Skin playlist ticket |
| SKIN-026 | Resource | Migrate | Authoritative whole-file Resource for `NewMovies.xsp` | skin, baseline | Current intentional outcome migrates | Whole-file canonical/digest Verification | Skin playlist ticket |
| SKIN-027 | Resource | Migrate | Whole-file Resource for `RecentlyReleasedMovies90Days.xsp` with explicit `desired: absent` | skin, baseline | Managed removal must remain visible as a destructive Change | Verify absence independently; omission would instead mean unmanaged | Skin playlist ticket |
| SKIN-028 | Resource | Migrate | Whole-file Resource for `RecentlyReleasedMoviesCurrentYear.xsp` with explicit `desired: absent` | skin, baseline | Same | Verify absence independently | Skin playlist ticket |
| ROOM-001–ROOM-011 | Resource | Migrate | `KodiGuiSettings` owns all current room display/audio addresses in `guisettings.xml` | room | Room values are Profile data; display/audio labels are stable Intent resolved against observed capability | Per-setting fresh Verification of resolved representation after Kodi Effect; unsupported or ambiguous Intent blocks | Kodi room-settings ticket must finalize resolvers and fixtures |
| LIFE-001–LIFE-002 | Resource | Migrate | One lifecycle-gateway Resource owning wrapper plus only the dedicated marked authorized-key entry | services | The two addresses form one independently testable gateway; unrelated authorized keys are preserved | Verify bytes/modes/unique marker and end-to-end allowed/denied commands; platform/OpenSSH remain Guards | Lifecycle gateway ticket must finalize partial-file rollback |
| LIFE-003 | Effect | Migrate | Temporary Kodi start/stop Effects requested by lifecycle-gateway Verification | services | Service state is restored to its initial Observation and is not steady-state Desired State | Effect success is not Resource Verification; gateway behavior and restored state are independently re-observed | Effect scheduling ticket must define restoration semantics |
| EFFECT-001 | Effect | Migrate | Coalesced Kodi stop/start Effect shared by affected Resource Changes | core, cec, addons, services, skin, room, baseline | Components cannot create separate restart transactions; planner schedules safe dependency barriers | Wait for readiness, then re-observe every affected Resource | #38 must finalize Effect barriers |
| EFFECT-002 | Effect | Migrate | `tz-data.service` restart Effect requested by `CoreElecTimezone` | core, baseline | Restart materializes coordinated timezone state | Re-observe cache plus localtime/offset evidence; restart exit alone is insufficient | Timezone/service ticket |
| EFFECT-003 | Effect | Migrate | `sshd.service` restart Effect requested by SSH hardening | core, baseline | Hardening must be activated without folding service state into the document Resource | Reconnect, service readiness, and fresh document Observation all required | SSH hardening/service ticket |
| EFFECT-004 | Effect | Migrate | `BuildSkinViews` Effect, including deterministic build invocation and required skin reload | skin, baseline | Compiled include is derived from the authoritative source Resource | Re-observe source and compiled expression evidence after readiness; polling is not Convergence | Skin generated-state ticket |
| EFFECT-005 | Unmanaged/Inventory Fact | Outside | Skin power-menu content and operational documentation only | none | The Reconciler does not currently require a Device reboot; exposed UI action is not an execution Effect | No Reconciler Verification or Health status | None unless a future Resource proves reboot necessary |
| FACT-001–FACT-005 | Unmanaged/Inventory Fact | Outside | Purpose-driven Device inventory/audit and troubleshooting evidence | inventory/audit | Network, service, module, HDMI/audio capability, and storage facts have no declared Desired State | Observations may support Guards, Intent resolution, health, or troubleshooting; never generic compatibility fields | #37/reporting ticket must select retained facts |
| FACT-006 | Unmanaged/Inventory Fact | Outside | Controller-to-Device connectivity diagnostic | inventory/audit | Device-local observation remains authoritative for Verification | Troubleshooting/Health evidence only; controller reachability is not Convergence | Transport/reporting ticket |

## 3. Explicit `KodiAddon` Resource roster

The ART range above means 41 separate Resources, not one collection Resource.
Every row below is required in the resolved Profile/Artifact catalog, names its
final Artifact digest, and converges directory, version, enabled state, and
final content. Catalog-derived dependencies are permitted only when the
resolved Plan explicitly names every dependency Resource and Artifact.

| Inventory ID | `KodiAddon` Resource ID / add-on |
|---|---|
| ART-001 | `repository.emby.kodi` |
| ART-002 | `repository.dontpanic` |
| ART-003 | `repository.jurialmunkey` |
| ART-004 | `plugin.service.emby-next-gen` |
| ART-005 | `plugin.video.themoviedb.helper` |
| ART-006 | `pvr.nextpvr` |
| ART-007 | `script.plexmod` |
| ART-008 | `skin.arctic.fuse.3` |
| ART-009 | `weather.ha` |
| ART-010 | `resource.language.en_us` |
| ART-011 | `script.artistslideshow` |
| ART-012 | `resource.images.arctic.waves` |
| ART-013 | `resource.images.weatherfanart.multi` |
| ART-014 | `resource.images.moviecountryicons.maps` |
| ART-015 | `resource.images.studios.white` |
| ART-016 | `resource.uisounds.fromashes` |
| ART-017 | `inputstream.adaptive` |
| ART-018 | `inputstream.ffmpegdirect` |
| ART-019 | `resource.font.robotocjksc` |
| ART-020 | `resource.images.studios.coloured` |
| ART-021 | `resource.images.weathericons.white` |
| ART-022 | `script.module.addon.signals` |
| ART-023 | `script.module.certifi` |
| ART-024 | `script.module.chardet` |
| ART-025 | `script.module.defusedxml` |
| ART-026 | `script.module.dateutil` |
| ART-027 | `script.module.future` |
| ART-028 | `script.module.idna` |
| ART-029 | `script.module.infotagger` |
| ART-030 | `script.module.inputstreamhelper` |
| ART-031 | `script.module.iso8601` |
| ART-032 | `script.module.jurialmunkey` |
| ART-033 | `script.module.kodi-six` |
| ART-034 | `script.module.pysocks` |
| ART-035 | `script.module.qrcode` |
| ART-036 | `script.module.requests` |
| ART-037 | `script.module.six` |
| ART-038 | `script.module.urllib3` |
| ART-039 | `script.module.yaml` |
| ART-040 | `script.skinvariables` |
| ART-041 | `script.texturemaker` |

## 4. Cross-cutting retirement and preservation

These conclusions apply to the classified rows and to the unnumbered
cross-cutting implementation evidence in the factual inventory:

- Retire component byte-isolation and ownership promises. Components remain
  selectors/presets only; selecting any concern that contributes addresses to
  `guisettings.xml` reconciles the complete `KodiGuiSettings` Resource.
- Retire separate provisioning/lifecycle transaction and report schemas.
  Unified Run Infrastructure owns one Device mutation lock, local workspace,
  remote marker, backup/recovery/finalization model, and purpose-driven report.
- Preserve semantic test cases and durable Device facts, but retire
  fixture-only shell CLI hooks and raw report fields without a Guard, evidence,
  Verification, recovery, inventory/audit, health, or troubleshooting purpose.
- Remove the superseded plan/spec tree early after preserving the factual
  inventory and durable facts identified in its section 6. Repair its three
  incoming links.
  Historical implementation instructions do not become replacement contracts.
- Home Assistant package/config copying and its runtime Kodi policy remain
  outside destination reconciliation. Only the Device-side lifecycle gateway
  Resource migrates.
- GitHub Actions may propose reviewed add-on update pull requests. It never
  auto-merges or deploys. Stable releases are the default. Every prerelease
  exception requires per-Artifact rationale, digest, additional acceptance,
  and an expiry or review trigger. Patched Artifacts are reproducibly built
  with upstream, patch-set, and final provenance digests. See
  [ADR 0005](../adr/0005-stable-addon-artifact-supply-chain.md).

## 5. Coverage reconciliation

### By contiguous factual-inventory range

| Factual inventory IDs | Rows | Classification records | Exactly once |
|---|---:|---|---|
| PLAT-001–PLAT-005 | 5 | `001–002`, `003`, `004`, `005` | yes |
| SSH-001–SSH-004 | 4 | `001–002`, `003`, `004` | yes |
| CORE-001–CORE-029 | 29 | `001–005`, `006`, `007`, `008–019`, `020–027`, `028–029` | yes |
| CEC-001–CEC-005 | 5 | `001–005` | yes |
| ART-001–ART-041 | 41 | `001–041` plus explicit 41-entry roster | yes |
| ADDON-001–ADDON-003 | 3 | `001`, `002`, `003` | yes |
| PATCH-001–PATCH-004 | 4 | `001–004` | yes |
| SVC-001–SVC-017 | 17 | `001`, `002–005`, `006–011`, `012–013`, `014–017` | yes |
| GUIDE-001–GUIDE-008 | 8 | `001–005`, `006`, `007`, `008` | yes |
| SKIN-001–SKIN-028 | 28 | `001–002`, `003–010`, `011`, `012`, `013`, `014`, `015–016`, `017–018`, `019`, `020`, `021`, `022`, `023`, `024`, `025`, `026`, `027`, `028` | yes |
| ROOM-001–ROOM-011 | 11 | `001–011` | yes |
| LIFE-001–LIFE-003 | 3 | `001–002`, `003` | yes |
| EFFECT-001–EFFECT-005 | 5 | `001`, `002`, `003`, `004`, `005` | yes |
| FACT-001–FACT-006 | 6 | `001–005`, `006` | yes |
| **Total** | **169** | **169 expanded IDs** | **yes** |

### By top-level role

| Role | Rows |
|---|---:|
| Resource | 128 |
| Guard | 5 |
| Effect | 5 |
| Guided Action | 6 |
| Run Infrastructure | 4 |
| Unmanaged/Inventory Fact | 21 |
| **Total** | **169** |

### By disposition

| Disposition | Rows |
|---|---:|
| Migrate | 153 |
| Retire | 5 |
| Outside | 11 |
| **Total** | **169** |

No provisional inventory ID is omitted or classified more than once.
