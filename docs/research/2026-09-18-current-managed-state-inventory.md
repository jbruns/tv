# Current managed State Address inventory

Date: 2026-09-18
Ticket: [Catalogue current managed State Addresses](https://github.com/jbruns/tv/issues/34)

## 1. Scope and method

This is a factual inventory of the committed shell implementation at commit
`b4bb4e7`. It traces every committed entry point, library, configuration file,
test suite, operator guide, Device guide, room record, Home Assistant asset,
and superseded implementation artifact. It records state the implementation
observes, mutates, verifies, reports, backs up, restores, removes, installs,
patches, or treats as an Effect.

The vocabulary is the CoreELEC Device Configuration vocabulary: each row names
a provisional **State Address**, its current **Observation**, current mutation
mechanics, and any **Effect**. A current shell “component” is retained only as
the existing user-facing grouping; it is not treated as a future Resource.

**No future disposition is decided here.** In particular, this inventory makes
no migrate, retire, Guided Action, or Unmanaged State decision. Guided
onboarding is recorded only as current observation/interaction behavior.
Runtime Home Assistant policy is outside the Reconciler destination; only the
Device-side lifecycle gateway installed by repository code is inventoried as
Device state.

Method:

1. enumerated tracked files and all three executable entry points;
2. traced configuration precedence and component expansion;
3. followed every remote script from preflight through backup, staging,
   mutation, Effects, Observation, Verification, report, finalize, and rollback;
4. extracted every Kodi setting ID, add-on artifact, add-on-data setting,
   managed file, compatibility patch, generated skin surface, and service call;
5. mapped tests and fixture-only emitters to each area;
6. compared superseded design/plan facts with durable documentation.

## 2. Entry points and current ownership/component grouping

| Entry point | Current grouping and boundary | Evidence |
|---|---|---|
| `provision-coreelec.sh` | Default `baseline` expands to `core`, `cec`, `addons`, `services`, and `skin`; `room` is opt-in. Dependencies are `services -> addons`, `skin -> core, addons`, and `room -> core`. Component selection narrows mutation, backup, verification, and reporting. | [`provision-coreelec.sh:L65-L175`](../../provision-coreelec.sh#L65-L175), [`provision-coreelec.sh:L4107-L4223`](../../provision-coreelec.sh#L4107-L4223) |
| `configure-coreelec-addons.sh` | Post-deployment observer/assistant for `weather.ha`, `pvr.nextpvr`, `script.plexmod`, and `plugin.service.emby-next-gen`. It does not write weather or NextPVR settings; it reports configuration and onboarding on separate axes. | [`configure-coreelec-addons.sh:L40-L75`](../../configure-coreelec-addons.sh#L40-L75), [`configure-coreelec-addons.sh:L217-L275`](../../configure-coreelec-addons.sh#L217-L275) |
| `configure-kodi-lifecycle.sh` | Separate transactional installer for the Device-side restricted Kodi lifecycle gateway: one forced-command wrapper and one marked `authorized_keys` entry. It verifies `start`, `stop`, `status`, denial, and service-state restoration. | [`configure-kodi-lifecycle.sh:L57-L100`](../../configure-kodi-lifecycle.sh#L57-L100), [`configure-kodi-lifecycle.sh:L360-L410`](../../configure-kodi-lifecycle.sh#L360-L410) |
| Home Assistant package/config examples | Copied manually to Home Assistant, not installed on the CoreELEC Device by a repository script. They consume the Device-side gateway. Runtime policy is not inventoried as a Reconciler destination. | [`docs/home-assistant/ugoos-kodi-lifecycle.md:L192-L218`](../home-assistant/ugoos-kodi-lifecycle.md#L192-L218), [`home-assistant/ssh/ugoos-kodi-lifecycle.conf.example:L1-L13`](../../home-assistant/ssh/ugoos-kodi-lifecycle.conf.example#L1-L13) |

Current configuration precedence is built-in defaults, selected
`provision.conf`, explicit CLI overrides, then the allowlisted secret values
from `.env`; room state comes from a separate strict `room.conf` parser
([`provision-coreelec.sh:L169-L175`](../../provision-coreelec.sh#L169-L175),
[`lib/coreelec-config.sh:L261-L296`](../../lib/coreelec-config.sh#L261-L296),
[`lib/coreelec-config.sh:L496-L620`](../../lib/coreelec-config.sh#L496-L620)).

## 3. Comprehensive inventory

### 3.1 Platform, release, connection, and administrator SSH

| ID | State Address / Device representation | Source | Current owner / entry point | Observation path | Mutation path | Verification / report evidence | Backup / rollback / removal | Dependencies / Effects | Reusable Device facts and citations |
|---|---|---|---|---|---|---|---|---|---|
| PLAT-001 | CoreELEC identity in `/etc/os-release` and `/etc/release` | Hard-coded identity check plus configured `EXPECTED_RELEASE` (`21.3`) | provisioner preflight | Reads both release files | None | Warning/refusal before ordinary mutation; report inventory includes both files | None | Blocks later mutation unless `--force-unsupported` | CoreELEC, release substring, and `Amlogic-ng` are required; [`provision-coreelec.sh:L5957-L6008`](../../provision-coreelec.sh#L5957-L6008) |
| PLAT-002 | Device-tree model `/proc/device-tree/model` | Hard-coded Ugoos AM6-family expectation | provisioner preflight/report | NUL-stripped file read | None | Warns, but does not set the fatal guard bit; raw inventory records model | None | No Effect | Model check is weaker than release/platform guards; [`provision-coreelec.sh:L5963-L6003`](../../provision-coreelec.sh#L5963-L6003), [`provision-coreelec.sh:L6515-L6525`](../../provision-coreelec.sh#L6515-L6525) |
| PLAT-003 | Kernel and hostname | Observed facts only | provisioner preflight/report | `uname -r`/`uname -a`, `hostname` | None | Printed in preflight and raw report inventory | None | No Effect | These are reported but not convergence criteria; [`provision-coreelec.sh:L5957-L5982`](../../provision-coreelec.sh#L5957-L5982), [`provision-coreelec.sh:L6513-L6521`](../../provision-coreelec.sh#L6513-L6521) |
| PLAT-004 | Lifecycle platform guard in `/etc/os-release` | Hard-coded `CoreELEC`, `21.3`, `Amlogic-ng` | lifecycle installer | Reads configured production path `/etc/os-release` | None | Distinct `PLATFORM_CHECK_FAIL:*` refusal | None | Blocks lifecycle mutation; no force bypass | Lifecycle guard is stricter and non-overridable; [`lib/coreelec-lifecycle.sh:L165-L184`](../../lib/coreelec-lifecycle.sh#L165-L184) |
| PLAT-005 | Installed OpenSSH capability (`/usr/sbin/sshd -V`) | Hard-coded OpenSSH `restrict` threshold 7.2 | lifecycle installer | Parses server version | None | Reports `KEY_MODE=restrict\|fallback`; fails closed when absent/unparseable | None | Selects authorized-key representation | Fallback spells out equivalent restrictions; [`lib/coreelec-lifecycle.sh:L187-L218`](../../lib/coreelec-lifecycle.sh#L187-L218) |
| SSH-001 | Controller-local administrator identity and `.pub` file (default `~/.ssh/coreelec_admin_ed25519`) | CLI/default, locally generated | provisioner | File existence; derives missing public key | Creates Ed25519 key; modes private `0600`, public `0644` | Successful keyed connection is required before password auth is disabled; report names identity path, not key content | Local key is not transaction-backed | May prompt; adds key to agent best effort | Key creation and modes: [`provision-coreelec.sh:L5910-L5931`](../../provision-coreelec.sh#L5910-L5931) |
| SSH-002 | `/storage/.ssh/authorized_keys`: administrator key line | Local public key; installer normalizes key grammar | provisioner | Initial keyed SSH succeeds or password bootstrap path is used | Adds key idempotently via emitted `authorized-key` program | Opens a new key-only SSH connection | Independently reversible only by manual/key-file edit; not included in main transaction | Enables all subsequent SSH; no daemon Effect itself | Key is the only Device change allowed before room/audio preflight probes; [`provision-coreelec.sh:L5933-L5955`](../../provision-coreelec.sh#L5933-L5955), [`provision-coreelec.sh:L6010-L6013`](../../provision-coreelec.sh#L6010-L6013) |
| SSH-003 | `/storage/.cache/services/sshd.conf` with password authentication disabled | Hard-coded policy gated by configured `HARDEN_SSH` | provisioner | Later checks file indirectly through successful SSH and nonempty `authorized_keys` | Atomic candidate writes `SSH_ARGS="-o 'PasswordAuthentication no'"` and `SSHD_DISABLE_PW_AUTH="true"` | `sshd.service` must be active and `authorized_keys` nonempty | Selective operational backup includes service cache; main deployment transaction does not own this earlier mutation | **Effect:** restart `sshd.service`, sleep, reconnect | `--no-harden` preserves password auth; [`provision-coreelec.sh:L6122-L6153`](../../provision-coreelec.sh#L6122-L6153) |
| SSH-004 | SSH host key acceptance / known-hosts state | OpenSSH client behavior and operator setup | all entry points | SSH client validation | No explicit repository mutation of administrator known-hosts; lifecycle controller requires a preauthenticated explicit file | Connection succeeds or fails closed | Outside Device transaction | Transport dependency | Lifecycle controller uses strict checking, one attempt, and a 15-second outer deadline; [`lib/coreelec-lifecycle.sh:L1118-L1147`](../../lib/coreelec-lifecycle.sh#L1118-L1147) |

### 3.2 CoreELEC/Kodi shared `core` state

All Kodi settings below are direct `<setting id="…">value</setting>` children
of `/storage/.kodi/userdata/guisettings.xml`. Mutation canonicalizes
case-insensitive duplicates and preserves unrelated settings. Observation is
Kodi localhost JSON-RPC unless noted
([`provision-coreelec.sh:L676-L768`](../../provision-coreelec.sh#L676-L768),
[`provision-coreelec.sh:L2403-L2437`](../../provision-coreelec.sh#L2403-L2437)).

| ID | State Address / Device representation | Source | Current owner / entry point | Observation path | Mutation path | Verification / report evidence | Backup / rollback / removal | Dependencies / Effects | Reusable Device facts and citations |
|---|---|---|---|---|---|---|---|---|---|
| CORE-001 | `locale.language` | Config `LOCALE_LANGUAGE` | `core` / provisioner | `Settings.GetSettingValue` | XML transform | Independent expected/observed/status | Whole `guisettings.xml` pre-image | Kodi stop/start | Config value and write: [`config/shared/ugoos-am6b-plus/coreelec-21.3/provision.conf:L98-L104`](../../config/shared/ugoos-am6b-plus/coreelec-21.3/provision.conf#L98-L104), [`provision-coreelec.sh:L4804-L4819`](../../provision-coreelec.sh#L4804-L4819) |
| CORE-002 | `locale.country` | Config `LOCALE_COUNTRY` | `core` | JSON-RPC | XML transform | Independent comparison | Same file rollback | Kodi stop/start | Same citations as CORE-001 |
| CORE-003 | `locale.keyboardlayouts` | Config `KEYBOARD_LAYOUT` | `core` | JSON-RPC | XML transform | Independent comparison | Same file rollback | Kodi stop/start | Same citations as CORE-001 |
| CORE-004 | `locale.timezonecountry` | Config `TIMEZONE_COUNTRY` | `core` | JSON-RPC | XML transform | Independent comparison | Same file rollback | Kodi stop/start; timezone reload below | Same citations as CORE-001 |
| CORE-005 | `locale.timezone` | Config `TIMEZONE` | `core` | JSON-RPC | XML transform | Independent comparison | Same file rollback | Kodi stop/start; timezone reload | Same citations as CORE-001 |
| CORE-006 | `/storage/.cache/timezone` (`TIMEZONE=…`) | Config `TIMEZONE` | `core` | Reads `TIMEZONE=` line | Atomic text replacement | Independent comparison | File pre-image/absence marker via scoped backup | `tz-data.service` restart | CoreELEC’s UI normally writes this cache; offline edit must do so explicitly; [`provision-coreelec.sh:L1110-L1115`](../../provision-coreelec.sh#L1110-L1115), [`provision-coreelec.sh:L2774-L2785`](../../provision-coreelec.sh#L2774-L2785) |
| CORE-007 | `/etc/localtime` representation and current date offset | Transform relies on CoreELEC timezone reload; no direct file write in transformer | `core` verification | Symlink target/realpath, file kind, byte equality against four possible zoneinfo roots, and `date +%Z%z` offset | Indirect through timezone settings/cache plus `tz-data.service` restart | Reports path, kind, byte match, expected/observed offset; mismatch fails | Not directly backed up by scoped settings list | **Effect:** restart `tz-data.service` | CoreELEC may use a symlink or a copied zone file; [`provision-coreelec.sh:L2814-L2873`](../../provision-coreelec.sh#L2814-L2873), [`provision-coreelec.sh:L2936-L2957`](../../provision-coreelec.sh#L2936-L2957) |
| CORE-008 | `general.addonupdates` | Config transform: `auto -> 0`, `notify -> 1` | `core` | **No current verification request** | XML transform | Not independently reported/verified | `guisettings.xml` rollback | Kodi stop/start | Desired policy is config; numeric representation is transform logic; [`provision-coreelec.sh:L678-L682`](../../provision-coreelec.sh#L678-L682), omission from [`provision-coreelec.sh:L2403-L2420`](../../provision-coreelec.sh#L2403-L2420) |
| CORE-009 | `input.enablemouse` | Hard-coded `false` | `core` | JSON-RPC | XML transform | Independent comparison | `guisettings.xml` rollback | Kodi stop/start | Hard-coded policy, not config; [`provision-coreelec.sh:L682-L698`](../../provision-coreelec.sh#L682-L698), [`provision-coreelec.sh:L4824-L4854`](../../provision-coreelec.sh#L4824-L4854) |
| CORE-010 | `filelists.showaddsourcebuttons` | Hard-coded `false` | `core` | JSON-RPC | XML transform | Independent comparison | Same | Kodi stop/start | Same citations as CORE-009 |
| CORE-011 | `filelists.showextensions` | Hard-coded `false` | `core` | JSON-RPC | XML transform | Independent comparison | Same | Kodi stop/start | Same citations as CORE-009 |
| CORE-012 | `filelists.showparentdiritems` | Hard-coded `false` | `core` | JSON-RPC | XML transform | Independent comparison | Same | Kodi stop/start | Same citations as CORE-009 |
| CORE-013 | `videolibrary.flattentvshows` | Hard-coded `1` | `core` | JSON-RPC | XML transform | Independent comparison | Same | Kodi stop/start | Same citations as CORE-009 |
| CORE-014 | `videolibrary.ignorevideoextras` | Hard-coded `true` | `core` | JSON-RPC | XML transform | Independent comparison | Same | Kodi stop/start | Same citations as CORE-009 |
| CORE-015 | `videolibrary.ignorevideoversions` | Hard-coded `true` | `core` | JSON-RPC | XML transform | Independent comparison | Same | Kodi stop/start | Same citations as CORE-009 |
| CORE-016 | `videolibrary.showallitems` | Hard-coded `false` | `core` | JSON-RPC | XML transform | Independent comparison | Same | Kodi stop/start | Same citations as CORE-009 |
| CORE-017 | `videolibrary.tvshowsselectfirstunwatcheditem` | Hard-coded `1` | `core` | JSON-RPC | XML transform | Independent comparison | Same | Kodi stop/start | Same citations as CORE-009 |
| CORE-018 | `videoplayer.adjustrefreshrate` | Hard-coded `2` | `core` | **No current verification request** | XML transform | Not independently reported/verified | Same | Kodi stop/start | Written at [`provision-coreelec.sh:L696-L698`](../../provision-coreelec.sh#L696-L698), absent from [`provision-coreelec.sh:L2403-L2420`](../../provision-coreelec.sh#L2403-L2420) |
| CORE-019 | `videoplayer.usedisplayasclock` | Hard-coded `false` | `core` | **No current verification request** | XML transform | Not independently reported/verified | Same | Kodi stop/start | Same evidence as CORE-018 |
| CORE-020 | `services.esallinterfaces` | Hard-coded `false` when Kodi password is present | `core` | **No current verification request** | XML transform | Only endpoint behavior is exercised indirectly | Same | Kodi stop/start; authenticated JSON-RPC dependency | Web-service block: [`provision-coreelec.sh:L699-L709`](../../provision-coreelec.sh#L699-L709) |
| CORE-021 | `services.esenabled` | Hard-coded `true` when password present | `core` | Buildviews probe reads it; baseline verifier does not compare it | XML transform | Buildviews refuses if unavailable/false; no normal independent row | Same | Kodi stop/start; JSON-RPC/event server | [`provision-coreelec.sh:L699-L709`](../../provision-coreelec.sh#L699-L709), [`provision-coreelec.sh:L3997-L4033`](../../provision-coreelec.sh#L3997-L4033) |
| CORE-022 | `services.webserver` | Hard-coded `true` | `core` | Successful authenticated JSON-RPC indirectly observes service | XML transform | JSON-RPC version required | Same | Kodi stop/start | [`provision-coreelec.sh:L699-L709`](../../provision-coreelec.sh#L699-L709), [`provision-coreelec.sh:L4795-L4802`](../../provision-coreelec.sh#L4795-L4802) |
| CORE-023 | `services.webserverauthentication` | Hard-coded `true` | `core` | Authenticated request succeeds/fails | XML transform | Indirect only | Same | Kodi stop/start | Same evidence as CORE-022 |
| CORE-024 | `services.webserverpassword` | Secret `KODI_WEB_PASSWORD` | `core` | Never returned; used to authenticate | XML transform from private payload | Report says stored in shared env; literal redaction scan | Same; backup may contain secret and is mode-protected | Kodi stop/start | Secret never appears in report/argv request; [`provision-coreelec.sh:L5430-L5439`](../../provision-coreelec.sh#L5430-L5439), [`provision-coreelec.sh:L5515-L5535`](../../provision-coreelec.sh#L5515-L5535) |
| CORE-025 | `services.webserverport` | Config `KODI_PORT` | `core` | Endpoint at configured port | XML transform | Indirect JSON-RPC reachability | Same | Kodi stop/start | Desired value is connection config reused as Device setting |
| CORE-026 | `services.webserverssl` | Hard-coded `false` | `core` | HTTP endpoint use is indirect evidence | XML transform | Indirect only | Same | Kodi stop/start | Hard-coded policy |
| CORE-027 | `services.webserverusername` | Config `KODI_USER` | `core` | Used for authentication | XML transform | Reported username plus successful authenticated RPC | Same | Kodi stop/start | Config/default is `homeassistant`; [`lib/coreelec-config.sh:L261-L269`](../../lib/coreelec-config.sh#L261-L269) |
| CORE-028 | `audiooutput.audiodevice` | Config Intent `AUDIO_DEVICE`; resolved to Device enumeration | `core` | Preflight audio probe plus JSON-RPC setting read | Resolved string written to XML | Independent expected resolved string vs observed | `guisettings.xml` rollback | Requires running Kodi before transaction; Kodi stop/start | Intent vocabulary is not the ALSA string; [`config/shared/ugoos-am6b-plus/coreelec-21.3/provision.conf:L105-L115`](../../config/shared/ugoos-am6b-plus/coreelec-21.3/provision.conf#L105-L115), [`provision-coreelec.sh:L6051-L6113`](../../provision-coreelec.sh#L6051-L6113) |
| CORE-029 | `audiooutput.passthroughdevice` | Config Intent `AUDIO_PASSTHROUGH_DEVICE`; resolved | `core` | Same audio probe plus JSON-RPC | Resolved string written | Independent comparison | Same | Same | Same evidence as CORE-028 |

### 3.3 CEC

The State Address file is the exactly one
`/storage/.kodi/userdata/peripheral_data/*CEC*.xml`; adapter-specific filenames
are discovered and not reported
([`provision-coreelec.sh:L1147-L1161`](../../provision-coreelec.sh#L1147-L1161),
[`provision-coreelec.sh:L2788-L2811`](../../provision-coreelec.sh#L2788-L2811)).

| ID | State Address / representation | Source | Owner | Observation | Mutation | Verification/report | Backup/rollback | Dependencies/Effects | Facts |
|---|---|---|---|---|---|---|---|---|---|
| CEC-001 | `standby_pc_on_tv_standby` | Hard-coded Kodi localization ID `36028` (“Ignore”) | `cec` | Direct XML value attribute | XML transform | `cec.tv_off_action` comparison | Exact discovered file pre-image | Kodi stop/start | Positive repository concept maps to this Kodi setting; [`provision-coreelec.sh:L770-L778`](../../provision-coreelec.sh#L770-L778), [`provision-coreelec.sh:L4886-L4905`](../../provision-coreelec.sh#L4886-L4905) |
| CEC-002 | `activate_source` | Hard-coded `0` | `cec` | Direct XML | XML transform | Independent comparison | Same | Kodi stop/start | Required direct root setting |
| CEC-003 | `wake_devices` | Hard-coded `231` | `cec` | Direct XML | XML transform | Independent comparison | Same | Kodi stop/start | Required direct root setting |
| CEC-004 | `standby_devices` | Hard-coded `231` | `cec` | Direct XML | XML transform | Independent comparison | Same | Kodi stop/start | Required direct root setting |
| CEC-005 | `standby_tv_on_pc_standby` | Hard-coded `0` | `cec` | Direct XML | XML transform | Independent comparison | Same | Kodi stop/start | The five-value operational meaning is documented at [`docs/home-assistant/ugoos-kodi-lifecycle.md:L59-L82`](../home-assistant/ugoos-kodi-lifecycle.md#L59-L82) |

### 3.4 Add-on artifacts, enablement, compatibility patches, inventory, and settings

Each ART row is independently addressable as
`/storage/.kodi/addons/<add-on-id>/`. Its source is one
`ADDON_ARTIFACT=id|version|https-url|sha256` record. All 41 use identical
download/checksum/ZIP-safety/addon.xml validation, staging, directory-swap
backup, localhost `Addons.GetAddonDetails` Observation, enable convergence via
`Addons.SetAddonEnabled`, and fresh-query Verification
([`lib/coreelec-artifacts.sh:L117-L197`](../../lib/coreelec-artifacts.sh#L117-L197),
[`provision-coreelec.sh:L2275-L2295`](../../provision-coreelec.sh#L2275-L2295),
[`provision-coreelec.sh:L2580-L2713`](../../provision-coreelec.sh#L2580-L2713)).
Replaced directories move to `rollback/addons/<id>`; newly created directories
are removed on rollback. Kodi is stopped once before all replacements and
started once after all settings.

| ID | Add-on State Address | Config source citation | Current role / additional behavior |
|---|---|---|---|
| ART-001 | `repository.emby.kodi` | [`provision.conf:L157-L160`](../../config/shared/ugoos-am6b-plus/coreelec-21.3/provision.conf#L157-L160) | Repository artifact |
| ART-002 | `repository.dontpanic` | same | Repository artifact |
| ART-003 | `repository.jurialmunkey` | same | Repository artifact |
| ART-004 | `plugin.service.emby-next-gen` | [`provision.conf:L162-L170`](../../config/shared/ugoos-am6b-plus/coreelec-21.3/provision.conf#L162-L170) | Selected add-on; onboarding observer below |
| ART-005 | `plugin.video.themoviedb.helper` | same | Selected add-on; settings and two-file shutdown patch below |
| ART-006 | `pvr.nextpvr` | same | Selected binary add-on; instance settings/check below |
| ART-007 | `script.plexmod` | same | Selected add-on; settings cleanup, shutdown patch, and guided observations below |
| ART-008 | `skin.arctic.fuse.3` | same | Selected skin; installed directory also contains generated compiled include |
| ART-009 | `weather.ha` | same | Selected add-on; settings and two compatibility patches below |
| ART-010 | `resource.language.en_us` | same | Selected language resource |
| ART-011 | `script.artistslideshow` | [`provision.conf:L171-L180`](../../config/shared/ugoos-am6b-plus/coreelec-21.3/provision.conf#L171-L180) | Optional skin dependency |
| ART-012 | `resource.images.arctic.waves` | same | Optional skin dependency |
| ART-013 | `resource.images.weatherfanart.multi` | same | Optional skin dependency |
| ART-014 | `resource.images.moviecountryicons.maps` | same | Optional skin dependency |
| ART-015 | `resource.images.studios.white` | same | Optional skin dependency |
| ART-016 | `resource.uisounds.fromashes` | same | Optional skin dependency and active sound skin |
| ART-017 | `inputstream.adaptive` | [`provision.conf:L181-L185`](../../config/shared/ugoos-am6b-plus/coreelec-21.3/provision.conf#L181-L185) | CoreELEC binary dependency |
| ART-018 | `inputstream.ffmpegdirect` | same | CoreELEC binary dependency |
| ART-019 | `resource.font.robotocjksc` | [`provision.conf:L187-L210`](../../config/shared/ugoos-am6b-plus/coreelec-21.3/provision.conf#L187-L210) | Transitive dependency; archive root differs |
| ART-020 | `resource.images.studios.coloured` | same | Transitive dependency |
| ART-021 | `resource.images.weathericons.white` | same | Transitive dependency |
| ART-022 | `script.module.addon.signals` | same | Transitive dependency |
| ART-023 | `script.module.certifi` | same | Transitive dependency |
| ART-024 | `script.module.chardet` | same | Transitive dependency |
| ART-025 | `script.module.defusedxml` | same | Transitive dependency |
| ART-026 | `script.module.dateutil` | same | Transitive dependency |
| ART-027 | `script.module.future` | same | Transitive dependency |
| ART-028 | `script.module.idna` | same | Transitive dependency |
| ART-029 | `script.module.infotagger` | same | Transitive dependency |
| ART-030 | `script.module.inputstreamhelper` | same | Transitive dependency |
| ART-031 | `script.module.iso8601` | same | Transitive dependency |
| ART-032 | `script.module.jurialmunkey` | same | Transitive dependency |
| ART-033 | `script.module.kodi-six` | same | Transitive dependency |
| ART-034 | `script.module.pysocks` | same | Transitive dependency |
| ART-035 | `script.module.qrcode` | same | Transitive dependency |
| ART-036 | `script.module.requests` | same | Transitive dependency |
| ART-037 | `script.module.six` | same | Transitive dependency |
| ART-038 | `script.module.urllib3` | same | Transitive dependency |
| ART-039 | `script.module.yaml` | same | Transitive dependency |
| ART-040 | `script.skinvariables` | same | Transitive dependency; buildviews executor |
| ART-041 | `script.texturemaker` | same | Transitive dependency |

Additional add-on State Addresses and operational surfaces:

| ID | State Address / representation | Source | Owner | Observation | Mutation | Verification/report | Backup/rollback/removal | Dependencies/Effects and facts |
|---|---|---|---|---|---|---|---|---|
| ADDON-001 | Enabled flag for each ART-001..041 in Kodi add-on registry | Hard-coded desired enabled state for every selected artifact | `addons` | Probe reads `enabled` | Repeatedly calls `Addons.SetAddonEnabled(true)` then re-queries | Unresolved IDs fail and are named | No independent registry backup; restored add-on directory plus Kodi restart is rollback mechanism | Kodi running after install; command success is explicitly not evidence; [`provision-coreelec.sh:L3027-L3033`](../../provision-coreelec.sh#L3027-L3033), [`provision-coreelec.sh:L2634-L2713`](../../provision-coreelec.sh#L2634-L2713) |
| ADDON-002 | Installed user add-on collection under `/storage/.kodi/addons/*/addon.xml` outside selected lock | Config acknowledgment list `ADDON_UNMANAGED_ALLOWED` | `addons` report | Filesystem scan excludes `packages`, `temp`, non-addon debris, and selected IDs | None | Reports each unselected ID as `unmanaged` or `unmanaged_allowed` plus counts | Never removes these directories | Inventory does not fail baseline Verification; [`provision-coreelec.sh:L2613-L2631`](../../provision-coreelec.sh#L2613-L2631), [`provision-coreelec.sh:L5260-L5286`](../../provision-coreelec.sh#L5260-L5286) |
| ADDON-003 | Allowed observed IDs (9 scraper/autocomplete add-ons) | Config list, not mutation policy | `addons` report | Same scan | None | Acknowledgment changes report classification only | None | Exact list: [`provision.conf:L145-L155`](../../config/shared/ugoos-am6b-plus/coreelec-21.3/provision.conf#L145-L155) |
| PATCH-001 | `weather.ha/resources/settings.xml`, `ha_request_attempts` type | Hard-coded patch tied to selected version/source shape | artifact deploy | Requires exact source shape | Changes `type="int"` to `number` | Construction fails on mismatch; no independent post-install signature | Installed add-on directory rollback | Kodi 21 compatibility; [`provision-coreelec.sh:L1972-L1991`](../../provision-coreelec.sh#L1972-L1991) |
| PATCH-002 | `weather.ha/lib/homeassistant/_adapter.py` retry loop | Hard-coded source transform for `weather.ha` 0.0.6.6 | artifact deploy | Requires exact unpatched/already-patched shape | Inserts missing `continue`; compiles result | Construction fails on mismatch; no independent post-install signature | Add-on directory rollback | Prevents unreachable HA from escaping as `UnboundLocalError`; [`provision-coreelec.sh:L1992-L2041`](../../provision-coreelec.sh#L1992-L2041) |
| PATCH-003 | `script.plexmod/lib/monitor.py` shutdown path | Hard-coded transform for PM4K 1.3.19 | artifact deploy | Requires exact source sequence | Guards `windowutils.HOME`; compiles result | Construction fails on mismatch; no independent post-install signature | Add-on directory rollback | Shutdown compatibility; [`provision-coreelec.sh:L2043-L2087`](../../provision-coreelec.sh#L2043-L2087) |
| PATCH-004 | TMDb Helper `service.py` worker daemon flags and `cronjob.py` abort recheck | Hard-coded transforms for 6.17.1 | artifact deploy | Requires exact source sequences | Adds daemon flags and abort guard; compiles both | Construction fails on mismatch; no independent post-install signature | Add-on directory rollback | Shutdown/restart compatibility; [`provision-coreelec.sh:L2089-L2221`](../../provision-coreelec.sh#L2089-L2221) |
| SVC-001 | `weather.addon` in `guisettings.xml` | Conditional config: HA URL + weather entity + token => `weather.ha` | `services` | JSON-RPC read | XML transform | Independent comparison only when configured | `guisettings.xml` rollback; Kodi restart | [`provision-coreelec.sh:L667-L718`](../../provision-coreelec.sh#L667-L718), [`provision-coreelec.sh:L3094-L3103`](../../provision-coreelec.sh#L3094-L3103) |
| SVC-002 | `addon_data/weather.ha/settings.xml`: `ha_server` | Secret-derived endpoint | `services` | Device-local XML comparison returns only configured boolean | XML setting write | Aggregated configured boolean; postdeploy also calls HA and checks weather labels | Exact file pre-image/absence | Kodi restart; live HA endpoint dependency; [`provision-coreelec.sh:L825-L839`](../../provision-coreelec.sh#L825-L839), [`lib/coreelec-addon-workflows.sh:L1224-L1359`](../../lib/coreelec-addon-workflows.sh#L1224-L1359) |
| SVC-003 | Same file: `ha_key` | Secret token | `services` | Presence only, never returned | XML setting with `version=1` | Aggregated boolean/redacted | Same | Same |
| SVC-004 | Same file: `ha_weather_forecast_entity_id` | Config `HOME_ASSISTANT_WEATHER_ENTITY` | `services` | Exact local comparison | XML write | Aggregated boolean | Same | Same |
| SVC-005 | Same file: `ha_sun_entity_id` | Config `HOME_ASSISTANT_SUN_ENTITY` | `services` | Written; **not part of baseline configured predicate** | XML write | Postdeploy behavior may exercise add-on; no independent value comparison | Same | Same; [`provision-coreelec.sh:L833-L839`](../../provision-coreelec.sh#L833-L839), predicate omission at [`provision-coreelec.sh:L3094-L3103`](../../provision-coreelec.sh#L3094-L3103) |
| SVC-006 | `addon_data/pvr.nextpvr/instance-settings-1.xml`: `host` | Secret `NEXTPVR_HOST` | `services` | Local exact host comparison | XML write | Aggregated configured boolean; postdeploy performs initiate/login and optional channel-group check | Exact file pre-image/absence | Kodi restart; NextPVR endpoint dependency; [`provision-coreelec.sh:L793-L815`](../../provision-coreelec.sh#L793-L815), [`lib/coreelec-addon-workflows.sh:L1360-L1460`](../../lib/coreelec-addon-workflows.sh#L1360-L1460) |
| SVC-007 | Same file: `hostprotocol` | Config `NEXTPVR_PROTOCOL` | `services` | **Written but omitted from baseline configured predicate** | XML write | Postdeploy connectivity uses configured protocol | Same | Same |
| SVC-008 | Same file: `kodi_addon_instance_enabled` | Conditional hard-coded `true`; if no backend and file absent, create `false` | `services` | Exact true in configured predicate | XML write | Aggregated boolean | Same | Same |
| SVC-009 | Same file: `kodi_addon_instance_name` | Config or transform default `"NextPVR"` | `services` | **Written but omitted from baseline configured predicate** | XML write | No independent comparison | Same | Same |
| SVC-010 | Same file: `pin` | Secret `NEXTPVR_PIN` | `services` | Presence only | XML write | Aggregated boolean/redacted | Same | Same |
| SVC-011 | Same file: `port` | Config `NEXTPVR_PORT` | `services` | Exact comparison when configured | XML write | Aggregated boolean | Same | Same |
| SVC-012 | `addon_data/plugin.video.themoviedb.helper/settings.xml`: `mdblist_apikey` | Secret | `services` | Presence boolean | XML write | Separate presence observation; grouped add-on settings verdict | Exact file pre-image/absence | Kodi restart; [`provision-coreelec.sh:L780-L792`](../../provision-coreelec.sh#L780-L792), [`provision-coreelec.sh:L3115-L3125`](../../provision-coreelec.sh#L3115-L3125) |
| SVC-013 | Same file: `omdb_apikey` | Secret | `services` | Presence boolean | XML write | Separate presence observation | Same | Same |
| SVC-014 | `addon_data/script.plexmod/settings.xml`: remove `allow_insecure` | Hard-coded cleanup policy | `services` | No independent baseline Observation | Removes setting node | File rollback; postdeploy does not classify these four individually | Kodi restart | [`provision-coreelec.sh:L816-L824`](../../provision-coreelec.sh#L816-L824) |
| SVC-015 | Same: remove `local_mode` | Hard-coded | `services` | Same | Remove | Same | Same | Same |
| SVC-016 | Same: remove `local_servers_json` | Hard-coded | `services` | Same | Remove | Same | Same | Same |
| SVC-017 | Same: remove `local_profiles_json` | Hard-coded | `services` | Same | Remove | Same | Same | Same |

### 3.5 Guided onboarding observations (no disposition assigned)

These observations are made by `configure-coreelec-addons.sh`; they are listed
without classifying them as Resources, Guided Actions, or Unmanaged State.
Every report records `config_status` and `onboarding_status` separately
([`configure-coreelec-addons.sh:L217-L255`](../../configure-coreelec-addons.sh#L217-L255)).

| ID | Observed surface | Observation / possible interaction | Mutation/verification behavior | Evidence |
|---|---|---|---|---|
| GUIDE-001 | Kodi JSON-RPC method capabilities | `JSONRPC.Introspect` requires ten named methods; `PVR.GetChannelGroups` is advisory | No persistent mutation | [`lib/coreelec-addon-workflows.sh:L172-L223`](../../lib/coreelec-addon-workflows.sh#L172-L223) |
| GUIDE-002 | Current Kodi GUI window/control labels | `GUI.GetProperties` and exact trimmed label comparison | Used as fail-closed precondition for guided input | [`lib/coreelec-addon-workflows.sh:L226-L279`](../../lib/coreelec-addon-workflows.sh#L226-L279) |
| GUIDE-003 | PM4K pinned/installed version | `Addons.GetAddonDetails(version)` | Version mismatch fails configuration axis | [`lib/coreelec-addon-workflows.sh:L281-L335`](../../lib/coreelec-addon-workflows.sh#L281-L335) |
| GUIDE-004 | PM4K account token presence in `auth.token` or JSON `myplex.MyPlexAccount.authToken` | Reads add-on settings over administrator SSH; returns boolean only | Interactive path may launch PM4K, select, and send link code text; secret values are not reported | [`lib/coreelec-addon-workflows.sh:L337-L390`](../../lib/coreelec-addon-workflows.sh#L337-L390), [`lib/coreelec-addon-workflows.sh:L483-L521`](../../lib/coreelec-addon-workflows.sh#L483-L521) |
| GUIDE-005 | PM4K server binding | Reads PM4K settings/state separately from account token | Separate onboarding predicate; no server identifiers emitted | [`lib/coreelec-addon-workflows.sh:L393-L455`](../../lib/coreelec-addon-workflows.sh#L393-L455) |
| GUIDE-006 | Emby add-on state database/account ladder | Reads account state and sync state; distinguishes database existence, authenticated account, handshake, and completed sync | Interactive assistance opens server manager through JSON-RPC notification; no credentials are preseeded by provisioner | [`lib/coreelec-addon-workflows.sh:L587-L767`](../../lib/coreelec-addon-workflows.sh#L587-L767), [`lib/coreelec-addon-workflows.sh:L768-L986`](../../lib/coreelec-addon-workflows.sh#L768-L986) |
| GUIDE-007 | Home Assistant Weather runtime readiness | Reads provider setting, calls configured HA endpoint through add-on semantics, and requires populated weather labels | Observation/check only; provisioning owns persistent settings | [`lib/coreelec-addon-workflows.sh:L989-L1223`](../../lib/coreelec-addon-workflows.sh#L989-L1223), [`lib/coreelec-addon-workflows.sh:L1224-L1359`](../../lib/coreelec-addon-workflows.sh#L1224-L1359) |
| GUIDE-008 | NextPVR runtime readiness | Initiate/login HTTP handshake plus optional PVR channel groups | Observation/check only | [`lib/coreelec-addon-workflows.sh:L1360-L1460`](../../lib/coreelec-addon-workflows.sh#L1360-L1460) |

### 3.6 Arctic Fuse settings, nodes, viewtypes, generated includes, and playlists

| ID | State Address / representation | Source | Owner | Observation / mutation / verification | Backup/rollback/removal | Dependencies/Effects and facts |
|---|---|---|---|---|---|---|
| SKIN-001 | `guisettings.xml` `lookandfeel.skin` | Hard-coded `skin.arctic.fuse.3` | `skin` | JSON-RPC read; XML write; independent comparison | `guisettings.xml` rollback | Add-on installed first; Kodi restart; [`provision-coreelec.sh:L718-L722`](../../provision-coreelec.sh#L718-L722) |
| SKIN-002 | `guisettings.xml` `lookandfeel.soundskin` | Hard-coded `resource.uisounds.fromashes` | `skin` | XML file predicate, not general JSON-RPC list; aggregated Kodi-defaults verdict | Same | Add-on dependency; Kodi restart; [`provision-coreelec.sh:L3377-L3386`](../../provision-coreelec.sh#L3377-L3386) |
| SKIN-003 | `addon_data/skin.arctic.fuse.3/settings.xml`: TV hub 1101 (`Name`, `Toggle`, `Icon`, `Mode`, `Spotlight.Label`, `.Path`, `.Target`, `Shortcut.Path`, `.Target`) | Hard-coded policy/content | `skin` | Canonical root string nodes; aggregate exact predicate | Whole settings file pre-image/absence | Kodi restart; individual settings enumerated at [`provision-coreelec.sh:L876-L893`](../../provision-coreelec.sh#L876-L893), verified at [`provision-coreelec.sh:L3265-L3283`](../../provision-coreelec.sh#L3265-L3283) |
| SKIN-004 | Same file: Movies hub 1102, same nine fields | Hard-coded policy/content | `skin` | Same semantics | Same | Same; [`provision-coreelec.sh:L895-L907`](../../provision-coreelec.sh#L895-L907), [`provision-coreelec.sh:L3284-L3302`](../../provision-coreelec.sh#L3284-L3302) |
| SKIN-005 | Same file: Plex hub 1103 (`Name`, `Toggle`, `Icon`, `Shortcut.Path`; clear `Shortcut.Target`, three spotlight fields) | Hard-coded policy/content | `skin` | Exact/blank aggregate predicate | Same | Requires PM4K artifact; [`provision-coreelec.sh:L909-L917`](../../provision-coreelec.sh#L909-L917), [`provision-coreelec.sh:L3303-L3315`](../../provision-coreelec.sh#L3303-L3315) |
| SKIN-006 | Same file: custom hub 1104 nine fields removed; verifier checks six behaviorally active destination/toggle fields blank | Hard-coded disable policy | `skin` | Removes all enumerated fields; accepts absent/empty runtime materialization for six checked fields | Same | Kodi may recreate inert empty/case-varied nodes; [`provision-coreelec.sh:L919-L923`](../../provision-coreelec.sh#L919-L923), [`provision-coreelec.sh:L3316-L3324`](../../provision-coreelec.sh#L3316-L3324) |
| SKIN-007 | Same file: PVR hub `HomeSwitcher.1107.Toggle`; clear `Hub.1107.DisableSearch`, `DisableChannels`, `DisableGroups`, `DisableRecordings` | Conditional on complete NextPVR config | `skin` | Exact/blank aggregate predicate | Same | NextPVR condition; [`provision-coreelec.sh:L924-L931`](../../provision-coreelec.sh#L924-L931), [`provision-coreelec.sh:L3325-L3339`](../../provision-coreelec.sh#L3325-L3339) |
| SKIN-008 | Same file: `HomeSwitcher.1108.Toggle` | Hard-coded `true` | `skin` | Exact predicate in hubs aggregate | Same | Kodi restart |
| SKIN-009 | Same file: option tiles `01.include=NowPlaying`, `02.include=Settings`, `04.include=SystemInfo` | Hard-coded | `skin` | Exact aggregate predicate | Same | Kodi restart; [`provision-coreelec.sh:L932-L945`](../../provision-coreelec.sh#L932-L945) |
| SKIN-010 | Same file: Weather tile `03.include`; remove `03.path` and `03.target` | Conditional on complete HA Weather config | `skin` | Exact/blank aggregate predicate | Same | Weather config dependency; [`provision-coreelec.sh:L937-L945`](../../provision-coreelec.sh#L937-L945), [`provision-coreelec.sh:L3355-L3375`](../../provision-coreelec.sh#L3355-L3375) |
| SKIN-011 | `script.skinvariables/.../skinvariables-shortcut-homewidgets.json` | Hard-coded ordered six-item array | `skin` | Whole JSON equality; atomic replacement | Exact file pre-image/absence | Kodi restart; each item is explicit at [`provision-coreelec.sh:L957-L967`](../../provision-coreelec.sh#L957-L967) |
| SKIN-012 | `.../skinvariables-shortcut-1101widgets.json` | Hard-coded ordered four-item TV array | `skin` | Whole JSON equality; atomic replacement | Same | Kodi restart; [`provision-coreelec.sh:L969-L977`](../../provision-coreelec.sh#L969-L977) |
| SKIN-013 | `.../skinvariables-shortcut-1102widgets.json` | Hard-coded ordered four-item Movies array | `skin` | Whole JSON equality; atomic replacement | Same | Kodi restart; [`provision-coreelec.sh:L979-L987`](../../provision-coreelec.sh#L979-L987) |
| SKIN-014 | `.../skinvariables-shortcut-powermenu.json` | Hard-coded ordered five-item array: power off, timer, suspend, reboot, restart Kodi | `skin` | Whole JSON equality; atomic replacement | Same | Entries expose Device/Kodi actions but file mutation itself uses Kodi restart; [`provision-coreelec.sh:L989-L998`](../../provision-coreelec.sh#L989-L998), [`provision-coreelec.sh:L3424-L3435`](../../provision-coreelec.sh#L3424-L3435) |
| SKIN-015 | `addon_data/script.skinvariables/skin.arctic.fuse.3-viewtypes.json`, `library.seasons` | Hard-coded view `509` | `skin` | Reads JSON mapping; updates only named key; verifies named key | Exact whole-file pre-image; preserves other keys | Requires subsequent buildviews Effect; [`provision-coreelec.sh:L1000-L1022`](../../provision-coreelec.sh#L1000-L1022), [`provision-coreelec.sh:L3437-L3453`](../../provision-coreelec.sh#L3437-L3453) |
| SKIN-016 | Same, `library.episodes` | Hard-coded view `549` | `skin` | Same | Same | Same |
| SKIN-017 | Installed skin `1080i/script-skinviewtypes-includes.xml`: compiled seasons expression owner | Transform/generator output | `skin` | Parses expressions and requires exactly `Exp_View_509` for library `seasons` | Exact file pre-image/absence | **Effect:** execute `script.skinvariables` buildviews while Kodi runs; [`provision-coreelec.sh:L3455-L3494`](../../provision-coreelec.sh#L3455-L3494), [`provision-coreelec.sh:L3948-L4053`](../../provision-coreelec.sh#L3948-L4053) |
| SKIN-018 | Same compiled include: episodes expression owner | Generator output | `skin` | Requires exactly `Exp_View_549` | Same | Same |
| SKIN-019 | `playlists/video/InProgressMovies90Days.xsp` | Hard-coded XML signature | `skin` | Whole canonical signature equality | Exact file pre-image/absence | Kodi restart; signature: [`provision-coreelec.sh:L1053-L1059`](../../provision-coreelec.sh#L1053-L1059), verifier [`provision-coreelec.sh:L3496-L3503`](../../provision-coreelec.sh#L3496-L3503) |
| SKIN-020 | `InProgressShows90Days.xsp` | Hard-coded | `skin` | Same | Same | Same; [`provision-coreelec.sh:L1061-L1065`](../../provision-coreelec.sh#L1061-L1065) |
| SKIN-021 | `RecentlyAiredEpisodes30Days.xsp` | Hard-coded | `skin` | Same | Same | Same; [`provision-coreelec.sh:L1067-L1072`](../../provision-coreelec.sh#L1067-L1072) |
| SKIN-022 | `RecentlyReleasedMoviesCurrentAndPreviousYear.xsp` | Transform uses current Device/controller date year bounds | `skin` | Whole signature with dynamic year | Same | Date dependency; [`provision-coreelec.sh:L1053-L1084`](../../provision-coreelec.sh#L1053-L1084) |
| SKIN-023 | `TraktPopularTVShows.xsp` | Hard-coded tag query | `skin` | Whole signature | Same | Emby tag population is runtime dependency; [`provision-coreelec.sh:L1086-L1090`](../../provision-coreelec.sh#L1086-L1090) |
| SKIN-024 | `TraktWeekendBoxOffice.xsp` | Hard-coded tag query | `skin` | Whole signature | Same | Same; [`provision-coreelec.sh:L1092-L1096`](../../provision-coreelec.sh#L1092-L1096) |
| SKIN-025 | `NewShows.xsp` | Hard-coded | `skin` | Whole signature | Same | Kodi restart; [`provision-coreelec.sh:L1098-L1102`](../../provision-coreelec.sh#L1098-L1102) |
| SKIN-026 | `NewMovies.xsp` | Hard-coded | `skin` | Whole signature | Same | Kodi restart; [`provision-coreelec.sh:L1104-L1108`](../../provision-coreelec.sh#L1104-L1108) |
| SKIN-027 | `RecentlyReleasedMovies90Days.xsp` absence | Hard-coded removal | `skin` | Filesystem absence; removes regular file and refuses nonregular/symlink | Pre-image permits rollback | Kodi restart; [`provision-coreelec.sh:L1045-L1077`](../../provision-coreelec.sh#L1045-L1077), [`provision-coreelec.sh:L3555-L3561`](../../provision-coreelec.sh#L3555-L3561) |
| SKIN-028 | `RecentlyReleasedMoviesCurrentYear.xsp` absence | Hard-coded removal | `skin` | Same | Same | Same |

### 3.7 Room display and audio

Every room value is required and comes from the selected room’s strict
`room.conf`; no default silently supplies a room value
([`lib/coreelec-config.sh:L503-L620`](../../lib/coreelec-config.sh#L503-L620)).

| ID | Kodi State Address | Source / transform | Observation and mutation | Verification / rollback / Effects | Evidence |
|---|---|---|---|---|---|
| ROOM-001 | `videoscreen.resolution` | Config label `ROOM_DISPLAY_RESOLUTION`; preflight resolves unstable Kodi numeric index | Display probe queries running Kodi; XML writes resolved index | Independent setting comparison; `guisettings.xml` rollback; Kodi restart | [`config/rooms/theater/room.conf:L12-L17`](../../config/rooms/theater/room.conf#L12-L17), [`provision-coreelec.sh:L6014-L6045`](../../provision-coreelec.sh#L6014-L6045) |
| ROOM-002 | `videoscreen.whitelist` | Config exact ordered mode list | Preflight confirms support; XML writes scalar/list representation | Normalizes separators but preserves order; statuses include unsupported/unobservable/mismatch; rollback/restart | [`provision-coreelec.sh:L4654-L4686`](../../provision-coreelec.sh#L4654-L4686) |
| ROOM-003 | `coreelec.amlogic.disabledolbyvision` | Positive config `ROOM_DOLBY_VISION`; inverted write (`1 -> false`) | JSON-RPC read; XML write | Independent comparison; rollback/restart | [`provision-coreelec.sh:L727-L742`](../../provision-coreelec.sh#L727-L742) |
| ROOM-004 | `coreelec.amlogic.dolbyvisionled` | Config `tv-led -> 0`, `player-led -> 1` | JSON-RPC/XML | Independent comparison; rollback/restart | Same |
| ROOM-005 | `audiooutput.passthrough` | Config boolean | JSON-RPC/XML | Independent comparison; rollback/restart | [`config/rooms/theater/room.conf:L24-L36`](../../config/rooms/theater/room.conf#L24-L36) |
| ROOM-006 | `audiooutput.ac3passthrough` | Config boolean | JSON-RPC/XML | Same | Same |
| ROOM-007 | `audiooutput.eac3passthrough` | Config boolean | JSON-RPC/XML | Same | Same |
| ROOM-008 | `audiooutput.dtspassthrough` | Config boolean | JSON-RPC/XML | Same | Same |
| ROOM-009 | `audiooutput.truehdpassthrough` | Config boolean | JSON-RPC/XML | Same | Same |
| ROOM-010 | `audiooutput.dtshdpassthrough` | Config boolean | JSON-RPC/XML | Same | Same |
| ROOM-011 | `audiooutput.channels` | Config layout label; preflight resolves opaque enum ordinal | Audio probe queries running Kodi; XML writes ordinal | Independent comparison; rollback/restart | [`provision-coreelec.sh:L6051-L6113`](../../provision-coreelec.sh#L6051-L6113) |

The display/audio probes happen after administrator-key installation but before
the main backup/transaction. A failed probe leaves no main-transaction change
to undo, but the administrator key may already have been installed
([`provision-coreelec.sh:L6010-L6013`](../../provision-coreelec.sh#L6010-L6013),
[`provision-coreelec.sh:L6047-L6050`](../../provision-coreelec.sh#L6047-L6050)).

### 3.8 Device-side lifecycle gateway and service Effects

| ID | State Address / representation | Source | Owner | Observation / mutation / verification | Backup/rollback/removal | Dependencies/Effects and facts |
|---|---|---|---|---|---|---|
| LIFE-001 | `/storage/.config/kodi-lifecycle`, mode `0700` | Hard-coded rendered wrapper using `/usr/bin/systemctl` and `kodi.service` | lifecycle installer | Content rendered locally; atomically installed; restricted identity executes it | Byte-verified pre-image or absence marker; atomic restore/removal; verified rollback | Wrapper accepts only `start`, `stop`, `status`; [`lib/coreelec-lifecycle.sh:L88-L145`](../../lib/coreelec-lifecycle.sh#L88-L145), [`lib/coreelec-lifecycle.sh:L659-L701`](../../lib/coreelec-lifecycle.sh#L659-L701) |
| LIFE-002 | `/storage/.ssh/authorized_keys` marked `homeassistant-ugoos-kodi-lifecycle` entry | Supplied controller public key plus hard-coded restrictions; representation selected by observed sshd capability | lifecycle installer | Replaces only marked line, preserves all others; end-to-end separate restricted SSH verification | Byte-verified whole-file pre-image/absence; atomic restore; mode `0600` | Requires preauthenticated host key and matching private/public controller pair; [`lib/coreelec-lifecycle.sh:L35-L86`](../../lib/coreelec-lifecycle.sh#L35-L86), [`lib/coreelec-lifecycle.sh:L675-L700`](../../lib/coreelec-lifecycle.sh#L675-L700) |
| LIFE-003 | `kodi.service` running/stopped state during gateway install | Initial Observation, not a configured desired steady state | lifecycle installer | `systemctl is-active/is-failed`; verification performs status/start/status/stop/status/restore/status and arbitrary denial | Rollback and verification restore exactly initial running/stopped state; failed initial state refuses before mutation | **Effects:** start/stop `kodi.service`; this is gateway acceptance behavior, while later runtime HA policy is out of scope; [`lib/coreelec-lifecycle.sh:L522-L547`](../../lib/coreelec-lifecycle.sh#L522-L547), [`configure-kodi-lifecycle.sh:L360-L410`](../../configure-kodi-lifecycle.sh#L360-L410) |
| EFFECT-001 | Provisioning-wide Kodi stop/start | Hard-coded transaction sequencing | provisioner | Stops once before file/add-on mutation; starts once after settings | On failure rollback restores files/add-ons and starts Kodi; post-deploy Verification waits/retries | Shared Effect for core/CEC/addons/services/skin/room; [`provision-coreelec.sh:L2264-L2267`](../../provision-coreelec.sh#L2264-L2267), [`provision-coreelec.sh:L2317-L2327`](../../provision-coreelec.sh#L2317-L2327) |
| EFFECT-002 | `tz-data.service` restart | Hard-coded after settings | provisioner | `systemctl restart`, failure ignored | Timezone Verification must still pass | Service reload/restart Effect; [`provision-coreelec.sh:L2317-L2321`](../../provision-coreelec.sh#L2317-L2321) |
| EFFECT-003 | `sshd.service` restart | Hard-coded after SSH hardening | provisioner | Restart then reconnect/active check | Not part of main settings transaction | Service restart Effect; [`provision-coreelec.sh:L6145-L6152`](../../provision-coreelec.sh#L6145-L6152) |
| EFFECT-004 | Skinvariables buildviews execution and skin reload | Hard-coded buildviews sequence | `skin` | Requires JSON-RPC ping/event server, invokes `kodi-send RunScript(...buildviews,force=True,no_reload=True)`, polls compiled output, then reloads skin through JSON-RPC when appropriate | Compiled include has transaction pre-image/absence | Runs after deployment before Verification; stage itself does not decide convergence; [`provision-coreelec.sh:L3948-L4053`](../../provision-coreelec.sh#L3948-L4053), [`provision-coreelec.sh:L5564-L5574`](../../provision-coreelec.sh#L5564-L5574) |
| EFFECT-005 | Device reboot | No provisioning mutation invokes reboot | reports/docs/raw power menu only | Power menu contains `Reset()` and inventory reports boot/platform facts | No rollback semantics | Reboot is exposed as skin UI content, not executed by provisioner; [`provision-coreelec.sh:L989-L995`](../../provision-coreelec.sh#L989-L995) |

### 3.9 Report-only Device facts

These facts are current observations but not convergence criteria:

| ID | Observation surface | Evidence |
|---|---|---|
| FACT-001 | Network interface names/MAC addresses, `ip addr`, and routes | [`provision-coreelec.sh:L6527-L6535`](../../provision-coreelec.sh#L6527-L6535) |
| FACT-002 | Active state of `sshd.service`, `kodi.service`, `opentee_linuxdriver.service` | [`provision-coreelec.sh:L6537-L6540`](../../provision-coreelec.sh#L6537-L6540) |
| FACT-003 | Dolby Vision module files at three candidate paths, SHA-256, `lsmod`, and `modinfo` | [`provision-coreelec.sh:L6542-L6552`](../../provision-coreelec.sh#L6542-L6552) |
| FACT-004 | HDMI `disp_cap`, `dc_cap`, `hdr_cap`, `dv_cap`, `aud_cap` sysfs files | [`provision-coreelec.sh:L6554-L6562`](../../provision-coreelec.sh#L6554-L6562) |
| FACT-005 | `/proc/asound/cards` and `/storage` free space | [`provision-coreelec.sh:L6564-L6567`](../../provision-coreelec.sh#L6564-L6567) |
| FACT-006 | Controller-to-Device Kodi JSON-RPC reachability | Convenience network observation only; Device-local JSON-RPC decides Verification; [`provision-coreelec.sh:L6398-L6434`](../../provision-coreelec.sh#L6398-L6434) |

## 4. Cross-cutting operational state

### Main provisioning transaction

- Selective snapshot:
  `/storage/backup/coreelec-provision/<UTC timestamp>/`, private under `umask
  077`, copies component-scoped managed settings and selected add-on-related
  state. Files that may contain credentials are protected
  ([`provision-coreelec.sh:L1212-L1253`](../../provision-coreelec.sh#L1212-L1253)).
- Mutation journal:
  dated transaction directories contain `files/`, optional
  `rollback/addons/`, `DEPLOYED.txt`, `APPLIED.txt`, `PLAN.tsv`,
  `MANIFEST.txt`, and `STATE`; a pointer is written before moves
  ([`provision-coreelec.sh:L2225-L2263`](../../provision-coreelec.sh#L2225-L2263)).
- Pointer/staging:
  `/storage/.cache/coreelec-provision/` holds the current transaction pointer,
  uploaded `settings-payload.conf`, verify request/curl config, artifact stage,
  expanded artifacts, and deployment plan. Secret payloads are mode `0600` and
  removed by traps/best-effort cleanup
  ([`provision-coreelec.sh:L6241-L6251`](../../provision-coreelec.sh#L6241-L6251),
  [`provision-coreelec.sh:L6313-L6324`](../../provision-coreelec.sh#L6313-L6324),
  [`provision-coreelec.sh:L6483-L6509`](../../provision-coreelec.sh#L6483-L6509)).
- Finalize retains the dated backup/manifest as evidence, removes rollback-only
  material/stage/payload/plan, writes `committed`, and removes the pointer.
  Rollback restores pre-images, removes created managed paths, and preserves
  evidence; incomplete rollback retains pointer/material
  ([`provision-coreelec.sh:L2334-L2363`](../../provision-coreelec.sh#L2334-L2363)).
- Reports default to local `coreelec-provision-reports/`, directory mode `0700`,
  file mode `0600`. They include config fingerprint, scope, deployment state,
  verification comparisons, add-on inventory, recovery instructions, secret
  presence booleans, and fenced raw inventory
  ([`provision-coreelec.sh:L5404-L5513`](../../provision-coreelec.sh#L5404-L5513),
  [`provision-coreelec.sh:L5537-L5557`](../../provision-coreelec.sh#L5537-L5557)).

### Lifecycle transaction

- `/storage/backup/kodi-lifecycle/<timestamp>-<uuid>/` contains `manifest`,
  `phase`, `backups-complete`, and `rollback/` pre-images/absence markers.
  `/storage/.cache/kodi-lifecycle/current-transaction` points to pending work
  ([`lib/coreelec-lifecycle.sh:L147-L163`](../../lib/coreelec-lifecycle.sh#L147-L163),
  [`lib/coreelec-lifecycle.sh:L504-L565`](../../lib/coreelec-lifecycle.sh#L504-L565)).
- Durable receipts
  `finalizing-transaction`, `last-finalized-transaction`,
  `last-rolled-back-transaction`, and `last-abandoned-transaction` distinguish
  cleanup/retry outcomes after transaction-directory deletion
  ([`lib/coreelec-lifecycle.sh:L338-L364`](../../lib/coreelec-lifecycle.sh#L338-L364),
  [`lib/coreelec-lifecycle.sh:L923-L955`](../../lib/coreelec-lifecycle.sh#L923-L955)).
- Inspection reports only presence/phase/completion, never backup contents,
  because an `authorized_keys` pre-image may contain unrelated key material
  ([`lib/coreelec-lifecycle.sh:L959-L1047`](../../lib/coreelec-lifecycle.sh#L959-L1047)).
- Local lifecycle reports default to `coreelec-lifecycle-reports/`, mode
  `0700/0600`; key blobs and private-key first lines trigger report deletion
  ([`configure-kodi-lifecycle.sh:L263-L324`](../../configure-kodi-lifecycle.sh#L263-L324)).

### Secrets and redaction

- `.env` allowlists seven names and imports only those values; config files
  reject secret keys
  ([`lib/coreelec-env.sh:L3-L48`](../../lib/coreelec-env.sh#L3-L48),
  [`lib/coreelec-config.sh:L250-L256`](../../lib/coreelec-config.sh#L250-L256)).
- Main settings payload uses base64 as transport encoding, records explicit
  presence flags, and avoids secret process arguments
  ([`provision-coreelec.sh:L6155-L6172`](../../provision-coreelec.sh#L6155-L6172)).
- Device Verification receives the Kodi password because it must authenticate;
  all other secret facts return only booleans
  ([`provision-coreelec.sh:L6436-L6465`](../../provision-coreelec.sh#L6436-L6465)).
- Main and add-on workflow reports scan for every nonblank literal secret and
  delete themselves on a match
  ([`provision-coreelec.sh:L5515-L5535`](../../provision-coreelec.sh#L5515-L5535),
  [`configure-coreelec-addons.sh:L202-L215`](../../configure-coreelec-addons.sh#L202-L215)).

There is no explicit mutating-Run lock in the shell implementation. Pending
transaction pointers refuse overlapping work inside each of the two transaction
namespaces, but the namespaces and pre-transaction SSH changes are independent.

## 5. Current test coverage and fixture seams

| Area | Coverage and seams |
|---|---|
| Strict config, CLI precedence, room schema, secret rejection, add-on lock grammar | 65 tests in `tests/test-coreelec-config.sh`; local function-level fixtures and shipped config checks. Representative seams: [`tests/test-coreelec-config.sh:L15-L209`](../../tests/test-coreelec-config.sh#L15-L209), [`tests/test-coreelec-config.sh:L939-L1185`](../../tests/test-coreelec-config.sh#L939-L1185). |
| Secret environment loading | 8 tests in `tests/test-coreelec-env.sh`; isolated `.env` fixtures and entry-point checks: [`tests/test-coreelec-env.sh:L26-L150`](../../tests/test-coreelec-env.sh#L26-L150). |
| XML/JSON transforms, CEC, service settings, skin, playlists, viewtype source, room/audio writes, idempotence/unmanaged preservation | 80 tests in `tests/test-coreelec-settings.sh`; `--transform-fixture ROOT PAYLOAD` executes the production transformer against fixture roots: [`provision-coreelec.sh:L118-L122`](../../provision-coreelec.sh#L118-L122), [`tests/test-coreelec-settings.sh:L387-L621`](../../tests/test-coreelec-settings.sh#L387-L621), [`tests/test-coreelec-settings.sh:L2615-L2927`](../../tests/test-coreelec-settings.sh#L2615-L2927). |
| Artifact records, ZIP safety, patches, remote staging/deploy/rollback/finalize, scoped backups, service sequencing | 92 tests in `tests/test-coreelec-artifacts.sh`; `--emit-remote-script` runs exact remote programs against filesystem and command fixtures: [`provision-coreelec.sh:L123-L134`](../../provision-coreelec.sh#L123-L134), [`tests/test-coreelec-artifacts.sh:L156-L309`](../../tests/test-coreelec-artifacts.sh#L156-L309), [`tests/test-coreelec-artifacts.sh:L3282-L3483`](../../tests/test-coreelec-artifacts.sh#L3282-L3483). |
| Device-local Observation, Verification, report comparison, redaction, unmanaged add-on inventory, room statuses, generated compiled viewtypes | 205 tests in `tests/test-coreelec-report.sh`; fixture hooks `--verify-fixture`, `--report-fixture`, and `--conclude-fixture` plus emitted verify probe: [`provision-coreelec.sh:L138-L149`](../../provision-coreelec.sh#L138-L149), [`tests/test-coreelec-report.sh:L591-L880`](../../tests/test-coreelec-report.sh#L591-L880), [`tests/test-coreelec-report.sh:L5892-L6162`](../../tests/test-coreelec-report.sh#L5892-L6162). |
| Postdeploy capability checks, PM4K/Emby observation ladders, Weather/NextPVR runtime checks, two-axis report/redaction | 46 tests in `tests/test-coreelec-addon-workflows.sh`; stubbed SSH/curl/JSON-RPC and add-on-data fixtures: [`tests/test-coreelec-addon-workflows.sh:L376-L700`](../../tests/test-coreelec-addon-workflows.sh#L376-L700), [`tests/test-coreelec-addon-workflows.sh:L1381-L1854`](../../tests/test-coreelec-addon-workflows.sh#L1381-L1854). |
| Lifecycle wrapper/key grammar, platform/key-mode guards, transaction state machine, atomic backup/restore, recovery receipts, hardened controller transport | 63 tests in `tests/test-coreelec-lifecycle.sh`; emitted production scripts run against fixture roots and stub `systemctl`/`sshd`: [`configure-kodi-lifecycle.sh:L174-L237`](../../configure-kodi-lifecycle.sh#L174-L237), [`tests/test-coreelec-lifecycle.sh:L350-L595`](../../tests/test-coreelec-lifecycle.sh#L350-L595), [`tests/test-coreelec-lifecycle.sh:L2035-L2516`](../../tests/test-coreelec-lifecycle.sh#L2035-L2516). |
| Runtime Home Assistant policy (outside destination) | 51 tests in `tests/test-home-assistant-ugoos-package.sh` exercise the copied package’s lifecycle policy and explicitly reject suspend/shutdown/reboot/WOL/toggle commands: [`tests/test-home-assistant-ugoos-package.sh:L275-L328`](../../tests/test-home-assistant-ugoos-package.sh#L275-L328). |

Known fixture boundaries: most state logic is embedded Python or emitted shell
rather than importable modules; tests exercise production text through hidden
CLI hooks. Live Device acceptance evidence is documentary/manual rather than a
default automated suite.

## 6. Documentation evidence extraction before superseded artifact deletion

The documentation architecture says superseded plan/spec artifacts will be
removed and that durable docs should retain current operational truth, not
acceptance journals
([`docs/decisions/repository-documentation-architecture.md:L39-L54`](../decisions/repository-documentation-architecture.md#L39-L54)).
The following unique facts must not be lost merely because their dated
artifact is deleted:

| Superseded artifact(s) | Unique factual evidence to preserve | Durable location already carrying it / remaining gap |
|---|---|---|
| `2026-09-13-arctic-fuse-3-provisioning-{design,plan}.md` | Exact hub/widget/playlist semantics; Kodi 21 playlist-year limitation; preservation of unrelated settings; rationale for exact ordered JSON and managed removals | Current executable transformer/verifier is authoritative; operator outcomes are summarized in [`docs/operations/provision-ugoos.md:L167-L269`](../operations/provision-ugoos.md#L167-L269). Detailed State Addresses are now preserved in this inventory. |
| `2026-09-15-component-scoped-coreelec-provisioning-{design,plan}.md` | Component dependency graph; CEC’s exactly-one-file/five-setting ownership; scope-specific backup/verification; one stop/start transaction; distinction between component selection and add-on selection | Durable operational contract: [`docs/operations/provision-ugoos.md:L11-L78`](../operations/provision-ugoos.md#L11-L78), CEC contract: [`docs/home-assistant/ugoos-kodi-lifecycle.md:L51-L107`](../home-assistant/ugoos-kodi-lifecycle.md#L51-L107). |
| `2026-09-16-addon-onboarding-restart-sequencing-{design,plan}.md` | Two independent status axes; Emby completion ladder and false-success window; PM4K token vs server binding; one provisioning restart checkpoint; TMDb Helper has no onboarding step | Durable contract: [`docs/devices/ugoos-am6b-plus/addon-onboarding-contract.md:L10-L116`](../devices/ugoos-am6b-plus/addon-onboarding-contract.md#L10-L116), evidence/rationale: [`docs/devices/ugoos-am6b-plus/addon-onboarding-contract.md:L117-L200`](../devices/ugoos-am6b-plus/addon-onboarding-contract.md#L117-L200). |
| `2026-09-17-arctic-fuse-viewtypes-{design,plan}.md` | `script.skinvariables` owns/rebuilds the source; deterministic `kodi-send` trigger; restart alone does not regenerate a missing compiled include; source and compiled output need separate observations; exact expression ownership predicate | Durable operator contract: [`docs/operations/provision-ugoos.md:L205-L253`](../operations/provision-ugoos.md#L205-L253). The exact current source/compiled State Addresses and predicate are preserved in SKIN-015..018 above. |
| `2026-09-17-audio-device-management.md` | Audio output must be expressed as stable Intent and resolved from Kodi’s Device enumeration; missing match fails rather than falling back; decoded channels and passthrough devices are different concerns | Durable document: [`docs/devices/ugoos-am6b-plus/audio-output.md:L12-L121`](../devices/ugoos-am6b-plus/audio-output.md#L12-L121). |
| `2026-09-17-room-desired-state-{design,plan}.md` | Live Device showed whitelist as one scalar, ten 2160p modes, no separate Atmos key, Dolby Vision mode enum semantics, and unstable resolution/channel ordinals; display must be active for preflight resolution | Durable contract and representation facts: [`docs/devices/ugoos-am6b-plus/room-desired-state.md:L43-L180`](../devices/ugoos-am6b-plus/room-desired-state.md#L43-L180), exact current theater values/source: [`config/rooms/theater/room.conf:L9-L36`](../../config/rooms/theater/room.conf#L9-L36). |

Plan-only implementation instructions, commit commands, temporary evidence
paths, live report filenames, and dated acceptance results are not current
Device facts and are intentionally not promoted. The durable-doc deletion rule
itself distinguishes those historical artifacts
([`docs/decisions/repository-documentation-architecture.md:L41-L50`](../decisions/repository-documentation-architecture.md#L41-L50)).

## 7. Factual gaps and ambiguities for later classification

1. `general.addonupdates`, `videoplayer.adjustrefreshrate`, and
   `videoplayer.usedisplayasclock` are mutated but absent from the normal
   JSON-RPC verification list.
2. Most Kodi web-service settings are verified only indirectly by authenticated
   JSON-RPC success, not by per-setting comparison. `services.esenabled` is
   separately queried only during the skin buildviews stage.
3. `HOME_ASSISTANT_SUN_ENTITY`, NextPVR `hostprotocol` and instance name, and
   the four removed PM4K local-mode settings lack independent baseline
   comparisons.
4. Artifact compatibility patches are validated while constructing the
   installed directory, but Verification checks add-on ID/version/enabled
   rather than the patched file signatures.
5. The add-on lock is treated as a selected installation set, while unselected
   installed user add-ons are observed and reported but never removed. This
   inventory does not decide authority over that collection.
6. The main selective backup occurs before SSH hardening but the main
   deployment transaction begins later; the exact automated restoration path
   for a hardening-only failure is not expressed as one unified transaction.
7. Administrator-key installation is intentionally before display/audio
   preflight and outside the main transaction.
8. Main provisioning and lifecycle installation use independent pointer and
   backup namespaces; there is no shared Device mutation lock.
9. `/etc/localtime` is indirectly changed by the timezone service and verified,
   but is not directly included in scoped file rollback.
10. Compiled viewtype generation is triggered before Verification, and the
    trigger stage polls but does not itself determine Convergence.
11. The current report-only hardware/service facts have no declared ownership
    or freshness contract beyond one run’s raw inventory.
12. The postdeploy Emby/PM4K flows observe and may guide interactive state, but
    the repository does not express those surfaces as verifiable Desired State.
13. Home Assistant package and SSH config installation is manual copying; only
    the CoreELEC-side gateway has a repository installer.
14. A Device reboot is not a provisioning Effect today. It appears as a skin
    power-menu action and in manual operational validation only.
15. The shell suite has extensive fixture coverage, but no committed opt-in
    automated live-Device acceptance runner.

These are observations, not recommendations or future disposition decisions.

## 8. Summary counts and examination checklist

### Counts

Counts use the stable provisional inventory IDs in this document. Grouped skin
rows enumerate all individual setting IDs whose current observation/mutation/
verification semantics are identical.

| Broad area | Inventory rows | Individually enumerated addresses/items |
|---|---:|---:|
| Platform/release/administrator SSH | 9 | 9 |
| Shared CoreELEC/Kodi core state | 29 | 29 |
| CEC | 5 | 5 |
| Pinned add-on artifacts | 41 | 41 add-on directories plus enabled/version observations |
| Add-on collection, patches, and add-on settings | 24 | 1 collection inventory, 9 acknowledged IDs, 4 patches, 17 setting/removal addresses |
| Guided onboarding observations | 8 | 8 observed operational surfaces |
| Arctic Fuse/skin/generated state | 28 | 66 setting fields, JSON nodes, viewtype keys/outputs, and playlist files |
| Room display/audio | 11 | 11 |
| Lifecycle gateway and Effects | 8 | 2 installed files/entries, service state, and 5 Effect surfaces |
| Report-only reusable Device facts | 6 | 6 grouped fact surfaces |
| **Total provisional inventory rows** | **169** | **At least 256 explicitly named addresses/items** |

The 256 figure counts the 169 rows plus additional explicitly enumerated
members hidden by neither “etc.” nor an unnamed wildcard: 40 additional
per-add-on enabled flags beyond ADDON-001’s grouped row, 39 extra skin setting
fields beyond their grouped rows, and the eight additional allowed add-on IDs
beyond ADDON-003’s grouped row. Ordered JSON members are described but are not
inflated into separate State Addresses for this count because the current
implementation replaces and verifies each JSON file as a whole.

### Examination checklist

- [x] `provision-coreelec.sh`: CLI/internal fixture entry points, component
  graph, preflight, SSH bootstrap/hardening, display/audio resolution, backup,
  staging, deployment, patches, settings transform, Effects, Observation,
  Verification, report, finalize, rollback, and raw inventory.
- [x] `configure-coreelec-addons.sh` and
  `lib/coreelec-addon-workflows.sh`: all four supported workflows, capability
  probes, Guided observations/interactions, runtime checks, and report/redaction.
- [x] `configure-kodi-lifecycle.sh` and `lib/coreelec-lifecycle.sh`: wrapper,
  key entry, platform/key-mode guards, transaction/pointers/receipts, verify,
  rollback, finalize, inspect, reports, and service restoration.
- [x] `lib/coreelec-config.sh`, `lib/coreelec-env.sh`,
  `lib/coreelec-artifacts.sh`, and `lib/coreelec-ssh.sh`.
- [x] Shared `provision.conf`, theater `room.conf`, `.env.example`, and config
  documentation.
- [x] All eight substantive shell test suites plus the Home Assistant fixture
  driver; all hidden production fixture seams were traced.
- [x] Durable architecture/decision, Device, operations, lifecycle, network,
  runbook, and room documentation.
- [x] Every committed superseded specification and implementation-plan
  artifact was examined for facts that must survive
  their planned deletion.
- [x] Home Assistant package and SSH config example were examined to identify
  the Device-side gateway boundary without inventorying runtime policy as a
  Reconciler destination.
- [x] All 41 `ADDON_ARTIFACT` records and all 9
  `ADDON_UNMANAGED_ALLOWED` IDs were enumerated.
