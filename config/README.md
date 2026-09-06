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
- Any of the nine reserved secret keys (below) found in the file is rejected
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
| `ADDON_ARTIFACT` | (34 records shipped) | repeatable, see below |

`ADDON_ARTIFACT` records are `id|version|https-url|sha256`, one per line,
repeated once per locked artifact. The shipped shared file locks 34 records:
the six requested default add-ons (Emby for Kodi Next Gen, PM4K, official
Kodi YouTube, Arctic Fuse 3, NextPVR, Home Assistant Weather) plus TMDb
Helper, the regional language resource, their repositories, and their
complete transitive dependency closure. `--check-artifacts` downloads and
verifies all 34 over HTTPS.

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

None of these may appear in the configuration file; each is read directly
from the process environment and is never echoed, logged, or written into
the audit report:

- `OMDB_API_KEY`
- `MDBLIST_API_KEY`
- `YOUTUBE_API_KEY`, `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET` (all three
  or none)
- `HOME_ASSISTANT_TOKEN` (requires `HOME_ASSISTANT_URL`)
- `NEXTPVR_PIN` (requires `NEXTPVR_HOST`)
- `PLEX_TOKEN` (requires `PLEX_SERVER_HOST`)

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

## Shared versus room-specific boundary

The shared file carries only values that are identical for every matching
unit: platform/regional defaults and the pinned add-on lock. Everything that
differs per installation stays outside it and out of the repository:

- The device address/hostname (`--target`, CLI-only, never a config key).
- Site-specific service endpoints (`HOME_ASSISTANT_URL`, `NEXTPVR_HOST`,
  `PLEX_SERVER_HOST`, ...) are commented out by default in the shipped file;
  set them per deployment, or point `--config` at a separate file.
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
