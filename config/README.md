# Deployable configuration

`provision-coreelec.sh` reads exactly one strict `KEY=value` configuration
file plus a fixed set of secret environment variables. This directory holds
that file for the validated platform; see
[`../provision-coreelec.sh --help`](../provision-coreelec.sh) for the full CLI.

```text
config/
  shared/
    ugoos-am6b-plus/
      coreelec-21.3/
        provision.conf     The only configuration file provisioning loads today
  rooms/
    theater/<device-id>/    Reserved for future room-specific values
    living/<device-id>/
    guest/<device-id>/
    master/<device-id>/
```

Only `config/shared/ugoos-am6b-plus/coreelec-21.3/provision.conf` exists and is
consumed. `config/rooms/` remains a convention for values a future task may
add; no per-room configuration file is read, merged, or overlaid onto the
shared file today. Keep hostname, address/reservation, remote model, and room
video/audio choices with the target device instead. Keep shared defaults
independent of any room. Version-specific assets should remain tied to the
matching platform; CoreELEC 21.3 `-ng` and CoreELEC 22 `-no` are separate
installations.

The shared edge routing target is **pfSense Plus 26.07**. Follow the
[network onboarding guide](../docs/network/pfsense-plus-26.07-onboarding.md)
for DHCP static mappings and device records. Future network inventory should
retain each device's active MAC, pfSense interface/subnet, reserved IPv4, and
hostname; keep devices on DHCP. No mapping deployment or pfSense configuration
import is implemented. Keep full firewall configuration backups outside the
repository.

Keep the [shared WoL destination](../docs/network/wake-on-lan.md),
`172.16.99.99`, separate from per-device DHCP addresses. Future wake
configuration can share that destination while supplying each unit's real
wired MAC. Preserve the existing LAN static ARP entry and record the verified
UDP port before deployment.

## Running it

### Two-phase operator workflow

Run shared provisioning first, then the separate post-deployment checks:

```bash
./provision-coreelec.sh --target <host>
./configure-coreelec-addons.sh --target <host>
./configure-coreelec-addons.sh --target <host> --interactive \
  --addon script.plexmod \
  --addon plugin.video.youtube \
  --addon plugin.service.emby-next-gen
```

- `provision-coreelec.sh --target <host>` is transactional and unattended:
  it stages the pinned baseline, verifies it from the device's own localhost,
  and then commits or rolls back as one unit.
- `configure-coreelec-addons.sh --target <host>` is a separate
  post-deployment command. Its default run is read-only, never rewrites
  settings, and never rolls back an already valid baseline.
- `--interactive` is opt-in for guarded PM4K, YouTube, and Emby account
  flows. It may pause while you finish browser/device-code approval elsewhere,
  but a timeout or `manual-required` result still leaves the provisioned
  baseline intact.
- `--dry-run`, even with `--interactive`, validates locally and writes the
  static status `dry-run` for every selected add-on. It makes zero SSH/device
  calls and transmits no secrets.
- Provisioning itself still cannot sign Emby in. `EMBY_PASSWORD` appears in
  the shared config/help surface because the post-deployment helper uses the
  same configuration library, not because the provisioner consumes it.

### What can be configured

The two commands share one config format, but they have different jobs.
`provision-coreelec.sh` writes declarative settings transactionally.
`configure-coreelec-addons.sh` never rewrites those settings: it validates
configured services and, with `--interactive`, assists account flows that
cannot be declared safely.

| Add-on | Non-secret config keys | Runtime secrets | Provisioner action | Post-deployment action |
| --- | --- | --- | --- | --- |
| Home Assistant Weather (`weather.ha`) | `HOME_ASSISTANT_URL`, `HOME_ASSISTANT_WEATHER_ENTITY`, `HOME_ASSISTANT_SUN_ENTITY` | `HOME_ASSISTANT_TOKEN` | Writes the provider URL and entity IDs. The deployer also patches 0.0.6.6's invalid legacy `int` setting type to Kodi 21's `number` type after checksum validation. | Calls Home Assistant from CoreELEC, verifies the weather entity, requires `weather.addon=weather.ha`, and requires populated Kodi Weather labels. |
| NextPVR (`pvr.nextpvr`) | `NEXTPVR_HOST`, `NEXTPVR_PORT`, `NEXTPVR_PROTOCOL`, `NEXTPVR_INSTANCE_NAME` | `NEXTPVR_PIN` | Writes and enables the named client instance. | Authenticates to NextPVR from CoreELEC and observes Kodi channel groups. |
| PM4K local-server mode (`script.plexmod`) | `PLEX_SERVER_HOST`, `PLEX_SERVER_PORT`, `PLEX_SERVER_NAME`, `PLEX_PROFILE_IDS` | `PLEX_TOKEN` | Writes direct local-server settings. | Verifies the server identity and token, then launches PM4K. |
| PM4K account mode (`script.plexmod`) | none | none supplied to these scripts | Leaves local-server mode unset. | With `--interactive`, opens the Plex device-link flow for local or shared remote servers. |
| YouTube (`plugin.video.youtube`) | none | `YOUTUBE_API_KEY`, `YOUTUBE_CLIENT_ID`, and `YOUTUBE_CLIENT_SECRET` together | Writes personal API credentials when all three are present. | With `--interactive`, opens the Google device-code flow and waits for persisted authorization. A token without a usable API client is only a partial login. |
| Emby Next Gen (`plugin.service.emby-next-gen`) | `EMBY_SERVER_URL`, `EMBY_USERNAME`; `EMBY_ALLOW_LOCAL_HTTP=1` only for an RFC1918/loopback HTTP server | `EMBY_PASSWORD` | Installs the add-on but does not sign in. | With `--interactive`, opens the running service's server manager, enters credentials only through recognized dialogs, and verifies the server handshake. Unrecognized custom-skin dialogs must be completed on the TV. |
| TMDb Helper (`plugin.video.themoviedb.helper`) | none | `OMDB_API_KEY` and `MDBLIST_API_KEY` — both required for real `APPLY_KODI=1` deployments; both optional for `--check-config` and `--check-artifacts` | Writes both metadata keys when present. | No post-deployment workflow; Trakt and TMDb user-account linking remain manual. |

Supplying only a secret is not enough: each secret that belongs to a service
endpoint requires the corresponding non-secret keys. Conversely, endpoint
keys without the secret leave that integration installed but unconfigured.
YouTube is all-or-none for its three credentials. For PM4K, choose either
local-server mode or the guided Plex account flow; remote shared servers
normally use the account flow and need no `PLEX_SERVER_*` values.

For a complete YouTube account acceptance test, supply a Google API key and
OAuth client ID/secret whose OAuth consent-screen test-user allowlist includes
the account being linked. A device-code flow can still leave access and
refresh tokens when these values are absent or invalid, but the add-on reports
that state as partially logged in and may repeatedly request authorization.

The post-deployment helper supports only `weather.ha`, `pvr.nextpvr`,
`script.plexmod`, `plugin.video.youtube`, and
`plugin.service.emby-next-gen`. Other pinned add-ons are installed and
verified by the provisioner but have no workflow accepted by `--addon`.

```bash
./provision-coreelec.sh --check-config
./provision-coreelec.sh --check-artifacts
./provision-coreelec.sh --target coreelec-theater
./provision-coreelec.sh --config /path/to/device.conf --target 172.16.99.50
```

- `--check-config` loads defaults, the config file, and CLI overrides, runs
  the semantic secret cross-checks, and exits 0 without a device or
  `--target`.
- `--check-artifacts` does the same and additionally downloads every locked
  add-on artifact to a private scratch directory, verifies its SHA-256, opens
  the ZIP to confirm a single safe top-level directory, and checks its
  `addon.xml` `id`/`version` against the lock — all without touching a
  device.
- `--target coreelec-theater` provisions that host using the default shared
  config file.
- `--config /path/to/device.conf --target 172.16.99.50` replaces the entire
  default file with `device.conf` — there is no merge with the shared file;
  supply a complete file if you need one that differs from the shared
  baseline.

For a real device, copy the complete shared file outside the repository,
restrict it to the operator, and edit only the site-specific non-secret
values:

```bash
install -d -m 700 ~/.config/tv
install -m 600 \
  config/shared/ugoos-am6b-plus/coreelec-21.3/provision.conf \
  ~/.config/tv/coreelec-theater.conf
$EDITOR ~/.config/tv/coreelec-theater.conf
```

Do not replace the shared file with a short override fragment. Because
`--config` performs replacement rather than merging, the private file must
retain the complete `ADDON_ARTIFACT` lock.


## Lifecycle and Home Assistant package inputs

The Kodi lifecycle gateway is separate from the shared provisioning config. `configure-kodi-lifecycle.sh` reads controller key paths only from CLI flags:

```bash
./configure-kodi-lifecycle.sh \
  --target ugoos-theater \
  --controller-public-key "$HOME/.ssh/ugoos_kodi_lifecycle_ed25519.pub" \
  --controller-identity "$HOME/.ssh/ugoos_kodi_lifecycle_ed25519"
```

The controller key files are operational secrets/identities, not repository configuration. Keep them outside this repository, remove any temporary Mac copy after deployment, and use the Home Assistant runtime paths documented in [`../docs/home-assistant/ugoos-kodi-lifecycle.md`](../docs/home-assistant/ugoos-kodi-lifecycle.md): `/config/.ssh/ugoos_kodi_lifecycle_ed25519`, `/config/.ssh/known_hosts`, `/config/.ssh/ugoos-kodi-lifecycle.conf`, and `/config/packages/ugoos_theater_kodi_lifecycle.yaml`.

The theater package intentionally hard-codes `media_player.sony_xr_65a90j`, `media_player.kodi_theater`, `ugoos-theater`, and `stop_when_display_off: true`. Future room-specific package copies must set their own entity IDs and reserved Ugoos address/name explicitly; no `config/rooms/` file is read or merged into Home Assistant today.

## Grammar (strict, never shell)

The parser reads the file line by line and dispatches every line through an
explicit allowlist. It never calls `eval`, `source`, or indirect/`${!x}`
expansion, so shell metacharacters in a value are inert data:

- Blank lines and lines whose first non-whitespace character is `#` are
  skipped.
- Every other line must be exactly `KEY=value` (no quoting, no `${...}`
  expansion, no command substitution, no arrays beyond the one repeatable key
  below) or the file is rejected with `file:line: expected KEY=value`.
- An unknown key is rejected with `unknown configuration key: KEY`.
- Every scalar key may appear at most once; a repeat is rejected with
  `duplicate configuration key: KEY`.
- `ADDON_ARTIFACT` is the one repeatable key; each occurrence appends a
  record instead of overwriting.
- Any of the ten reserved secret keys (below) found in the file is rejected
  outright, naming the key, never its value.
- `TARGET` is not a supported key and can never be set from a config file.

## Supported scalar keys

| Key | Default | Validation |
| --- | --- | --- |
| `EXPECTED_RELEASE` | `21.3` | identifier charset |
| `SSH_PORT` | `22` | `1`-`65535` |
| `KODI_PORT` | `8080` | `1`-`65535` |
| `KODI_USER` | `homeassistant` | identifier charset |
| `REPORT_DIR` | `$PWD/coreelec-provision-reports` | no shell metacharacters |
| `APPLY_KODI` | `1` | `0` or `1` |
| `HARDEN_SSH` | `1` | `0` or `1` |
| `FORCE_UNSUPPORTED` | `0` | `0` or `1` |
| `ASSUME_YES` | `0` | `0` or `1` |
| `TIMEZONE_COUNTRY` | `United States` | free-text display charset |
| `TIMEZONE` | `America/Los_Angeles` | relative zoneinfo path, no `..` |
| `LOCALE_LANGUAGE` | `resource.language.en_us` | identifier charset |
| `LOCALE_COUNTRY` | `USA (12h)` | free-text display charset |
| `KEYBOARD_LAYOUT` | `English QWERTY` | free-text display charset |
| `ADDON_UPDATE_MODE` | `notify` | `notify` or `auto` |
| `HOME_ASSISTANT_URL` | unset | `https://...` |
| `HOME_ASSISTANT_WEATHER_ENTITY` | unset | identifier charset |
| `HOME_ASSISTANT_SUN_ENTITY` | unset | identifier charset |
| `NEXTPVR_HOST` | unset | host charset |
| `NEXTPVR_PORT` | unset | `1`-`65535` |
| `NEXTPVR_PROTOCOL` | unset | `http` or `https` |
| `NEXTPVR_INSTANCE_NAME` | unset | free-text display charset |
| `PLEX_SERVER_HOST` | unset | host charset |
| `PLEX_SERVER_PORT` | unset | `1`-`65535` |
| `PLEX_SERVER_NAME` | unset | free-text display charset |
| `PLEX_PROFILE_IDS` | unset | comma-separated numeric IDs |
| `EMBY_SERVER_URL` | unset | `https://...`; `http://...` only for RFC1918/loopback with `EMBY_ALLOW_LOCAL_HTTP=1` |
| `EMBY_USERNAME` | unset | non-empty |
| `EMBY_ALLOW_LOCAL_HTTP` | `0` | `0` or `1` |
| `ADDON_ARTIFACT` | (42 records shipped) | repeatable, see below |

`ADDON_ARTIFACT` records are `id|version|https-url|sha256`, one per line,
repeated once per locked artifact. The shipped shared file locks 42 records:
the six requested default add-ons (Emby for Kodi Next Gen, PM4K, official
Kodi YouTube, Arctic Fuse 3, NextPVR, Home Assistant Weather) plus TMDb
Helper, the regional language resource, their repositories, six Arctic Fuse
optional add-ons (`script.artistslideshow`, `resource.images.arctic.waves`,
`resource.images.weatherfanart.multi`, `resource.images.moviecountryicons.maps`,
`resource.images.studios.white`, `service.upnext`), two transitive modules they
introduce (`script.module.defusedxml`, `script.module.future`), and their
complete transitive dependency closure. `--check-artifacts` downloads and
verifies all 42 over HTTPS.

## Precedence

1. Built-in defaults (`coreelec_config_defaults`).
2. The selected configuration file (`--config PATH`, default the shared file
   above).
3. Explicit CLI options (`--ssh-port`, `--kodi-port`, `--kodi-user`,
   `--report-dir`, `--expected-release`, `--no-kodi`, `--no-harden`,
   `--force-unsupported`, `--yes`, `--addon`/`--with-youtube`) always win over
   the config file.
4. Secret environment variables are read only at validation time and are
   never assignable from the config file or the CLI.

`--target HOST` is always required (except with `--check-config` /
`--check-artifacts`) and is supplied only on the command line; it is never a
config-file key.

## Secret environment variables

None of the ten reserved keys below may appear in the configuration file
(each is rejected outright, naming the key, never its value); the nine
listed here as usable are read directly from the process environment and
are never echoed, logged, or written into the audit report:

- `OMDB_API_KEY` and `MDBLIST_API_KEY` — required together for real
  `APPLY_KODI=1` deployments; optional for `--check-config` and
  `--check-artifacts`. No config-file or CLI secret form exists for either key.
  Never export `TMDB_API_KEY` expecting it to configure TMDb Helper — it is
  not a usable exported secret (see below).
- `YOUTUBE_API_KEY`, `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET` (all three
  or none)
- `HOME_ASSISTANT_TOKEN` (requires `HOME_ASSISTANT_URL`)
- `NEXTPVR_PIN` (requires `NEXTPVR_HOST`)
- `PLEX_TOKEN` (requires `PLEX_SERVER_HOST`)
- `EMBY_PASSWORD` (requires `EMBY_SERVER_URL` and `EMBY_USERNAME`; used only
  by `configure-coreelec-addons.sh --interactive`, never by the transactional
  provisioner)

`TMDB_API_KEY` is the tenth reserved key: it is rejected from the
configuration file exactly like the nine above, but it is not a usable
exported secret — current TMDb Helper has no user-configurable TMDb
API-key setting. TMDb Helper metadata keys are populated only by
`OMDB_API_KEY` and `MDBLIST_API_KEY` (see below); never export
`TMDB_API_KEY` expecting it to do anything.

Safe example — placeholder names only, never a usable credential:

```bash
export YOUTUBE_API_KEY="REPLACE_ME"
export YOUTUBE_CLIENT_ID="REPLACE_ME"
export YOUTUBE_CLIENT_SECRET="REPLACE_ME"
export HOME_ASSISTANT_TOKEN="REPLACE_ME"
export NEXTPVR_PIN="REPLACE_ME"
export PLEX_TOKEN="REPLACE_ME"
export OMDB_API_KEY="REPLACE_ME"
export MDBLIST_API_KEY="REPLACE_ME"
./provision-coreelec.sh --target 172.16.99.50
```

If you plan to use guided Emby sign-in, also configure `EMBY_SERVER_URL` and
`EMBY_USERNAME` in the selected config file, then run:

```bash
export EMBY_PASSWORD="REPLACE_ME"
./configure-coreelec-addons.sh --target <host> --interactive \
  --addon plugin.service.emby-next-gen
```

`provision-coreelec.sh` itself ignores `EMBY_PASSWORD`.

## Shared versus room-specific boundary

The shared file carries only values that are identical for every matching
unit: platform/regional defaults and the pinned add-on lock. Everything that
differs per installation stays outside it and out of the repository:

- The device address/hostname (`--target`, CLI-only, never a config key).
- Site-specific service endpoints and account names (`HOME_ASSISTANT_URL`,
  `NEXTPVR_HOST`, `PLEX_SERVER_HOST`, `EMBY_SERVER_URL`, `EMBY_USERNAME`, ...)
  are commented out by default in the shipped file; set them per deployment,
  or point `--config` at a separate file.
- All API keys, tokens, and PINs — environment variables only, supplied at
  run time, never committed.
- Room video/audio settings, hardware validation, and network reservations
  (see the [network onboarding guide](../docs/network/pfsense-plus-26.07-onboarding.md))
  remain manual and room-specific; `provision-coreelec.sh` does not touch
  them.

Keep passwords, private keys, downloaded firmware/module binaries, and full
device backups outside the repository. Record download sources in the
[shared device guide](../docs/devices/ugoos-am6b-plus/coreelec-21.3.md);
record per-device backup locations and installed values in the appropriate
[room guide](../README.md).

## Arctic Fuse 3 skin integration

The following notes clarify how the managed Arctic Fuse 3 baseline interacts
with its widget and metadata sources. They are not operator actions.

- **Next Aired is disabled**: Arctic Fuse renders a hub whenever
  `Skin.String(HomeSwitcher.1106.Toggle)` is non-empty, so provisioning removes
  every case-insensitive `HomeSwitcher.1106.Toggle` and
  `HomeSwitcher.1106.UpNextMode` node before Kodi starts. Arctic Fuse 3.2.16
  may recreate an empty string-typed toggle placeholder or a bool-typed toggle
  with value `false` after startup. The live verifier accepts no toggle matches,
  or matches that are each one of those two disabled representations.
  `UpNextMode` remains valid only when absent or represented by empty
  string-typed placeholders; every other type/value combination fails.
  TMDb Helper 6.17.1's
  `library_nextaired` route uses Trakt's public calendar but still requires an
  end-user Trakt OAuth token, producing `Unauthorised 401 Error TraktAPI Token`
  without one. The bundled Trakt client ID is valid; no missing API key can
  correct this.
- **No automated fallback**: the `library_airingnext` route uses local
  Kodi/TMDb data, but disposable live testing on this device class hit OMDb
  timeouts and TMDb Helper thread-fanout exhaustion (`can't start new thread`).
  It is not reliable enough for the managed baseline.
- **Trakt terminology**: Trakt labels its application credential the
  `trakt-api-key` HTTP header. That label is intentionally confusing because
  it refers to an application client key, not an end-user OAuth token. The
  managed baseline does not add a Trakt authorization workflow; it disables
  the feature that would require one.
- **TMDb Helper** (`plugin.video.themoviedb.helper`): bundles its own
  application TMDb credentials. `OMDB_API_KEY` and `MDBLIST_API_KEY` are the
  only operator-supplied keys; `TMDB_API_KEY` is reserved and rejected from
  the config file because TMDb Helper has no user-configurable TMDb API-key
  setting.
- **Plex custom slot 1101**: provisioning writes `HomeSwitcher.1101.*` skin
  settings so the Home hub runs `script.plexmod`. PM4K exposes no external
  widget directory.
- **YouTube custom slot 1102**: provisioning writes `HomeSwitcher.1102.*` skin
  settings so the Home hub opens `plugin://plugin.video.youtube/`. YouTube
  widgets are intentionally unmanaged: the provisioner writes the hub entry
  point only, and any widget rows visible in the YouTube hub depend on the
  user's own YouTube account and history within the add-on.
- **Managed Home order after Home**: Plex, YouTube, PVR, Add-ons.
- **Managed skin settings are case-exact in effect**: Kodi resolves
  `Skin.String` case-insensitively and reads only the direct `<setting>`
  children of the settings root. Provisioning therefore writes each managed
  setting as one canonical root node and removes every other case variant,
  and verification compares all case-insensitive matches of a managed ID so a
  lowercase duplicate can neither mask nor override the managed value.
- **Per-hub report lines**: `arctic_fuse.next_aired_hub`,
  `arctic_fuse.pvr_hub`, and `arctic_fuse.addons_hub` say which hub failed;
  `arctic_fuse.hubs` remains the aggregate verdict.
- **Recently Aired Shows** (`RecentlyAiredEpisodes30Days.xsp`): rolling
  previous 30 days; future dates excluded; Kodi Omega XSP field: `airdate`.
- **Recently Released Movies** (`RecentlyReleasedMoviesCurrentYear.xsp`):
  premiere year equals the device year captured during provisioning; ordered by
  year descending. Rerun provisioning after a year boundary to update the
  literal year. Calendar-year behavior was selected because Kodi Omega exposes
  `premiered` through a numeric XSP field that cannot perform day-level
  relative filtering. A deployment that straddles the Dec 31 midnight boundary
  writes one year and verifies against the next, so it fails closed and rolls
  back; rerun it after midnight.
- **Recently Released Movies, obsolete** (`RecentlyReleasedMovies90Days.xsp`):
  not a managed *widget* playlist — no Home widget references it and it is
  never written. It remains in the managed backup set so its removal is
  reversible: provisioning deletes it, and a rollback restores it exactly.
