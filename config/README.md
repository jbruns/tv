# Shared Ugoos configuration

This repository ships one non-secret configuration file for the locked Ugoos
AM6B+ / CoreELEC 21.3 baseline:

```text
config/shared/ugoos-am6b-plus/coreelec-21.3/provision.conf
```

`provision-coreelec.sh` and `configure-coreelec-addons.sh` read that file by
default. `configure-kodi-lifecycle.sh` does not read `provision.conf`; it
takes its controller key paths from CLI flags and uses the shared `.env` file
for secrets like the other entry points.

The shipped file carries only the shared baseline: release guard, regional
defaults, add-on update policy, site-specific endpoint placeholders, and the
locked add-on artifact set. Keep room-specific hostname/reservation values,
HDMI topology, Dolby Vision mode, whitelist entries, and audio choices outside
this file.

## Shared secret boundary

Copy the repository-root [`.env.example`](../.env.example) to `.env` before
running any Ugoos command:

```bash
cp .env.example .env
chmod 600 .env
```

The real `.env` is gitignored. None of the reserved keys below may appear in
`provision.conf`; each is rejected naming the key, never its value.

- `KODI_WEB_PASSWORD`
- `OMDB_API_KEY`
- `MDBLIST_API_KEY`
- `YOUTUBE_API_KEY`
- `YOUTUBE_CLIENT_ID`
- `YOUTUBE_CLIENT_SECRET`
- `HOME_ASSISTANT_TOKEN`
- `NEXTPVR_PIN`
- `PLEX_TOKEN`
- `EMBY_PASSWORD`
- `TMDB_API_KEY` — reserved and rejected, but not a usable `.env` input

Secret requirements:

- `KODI_WEB_PASSWORD` is required when `APPLY_KODI=1` and by live add-on
  validation.
- `OMDB_API_KEY` and `MDBLIST_API_KEY` are required together for real
  `APPLY_KODI=1` deployments; both are optional for `--check-config` and
  `--check-artifacts`.
- `YOUTUBE_API_KEY`, `YOUTUBE_CLIENT_ID`, and `YOUTUBE_CLIENT_SECRET` are
  all-or-none.
- `HOME_ASSISTANT_TOKEN` requires `HOME_ASSISTANT_URL`.
- `NEXTPVR_PIN` requires `NEXTPVR_HOST`.
- `PLEX_TOKEN` requires `PLEX_SERVER_HOST`.
- `EMBY_PASSWORD` requires `EMBY_SERVER_URL` and `EMBY_USERNAME`, and is used
  only by `configure-coreelec-addons.sh --interactive`.

## Grammar (strict, never shell)

The parser reads the file line by line and dispatches every line through an
explicit allowlist. It never calls `eval`, `source`, or indirect/`${!x}`
expansion, so shell metacharacters in a value are inert data.

- Blank lines and lines whose first non-whitespace character is `#` are
  skipped.
- Every other line must be exactly `KEY=value` (no quoting, no `${...}`
  expansion, no command substitution, no arrays beyond the one repeatable key
  below) or the file is rejected with `file:line: expected KEY=value`.
- An unknown key is rejected with `unknown configuration key: KEY`.
- Every scalar key may appear at most once; a repeat is rejected with
  `duplicate configuration key: KEY`.
- `ADDON_ARTIFACT` is the one repeatable key; each occurrence appends a record
  instead of overwriting.
- Reserved secret keys are rejected outright from the file.
- `TARGET` is not a supported key and can never be set from a config file.

## Supported inputs

### Script input contract

| Entry point | Reads `provision.conf` | Reads `.env` | Input notes |
| --- | --- | --- | --- |
| [`../provision-coreelec.sh`](../provision-coreelec.sh) | yes | yes | CLI overrides win over the config file; `--target` is always CLI-only except for `--check-config` / `--check-artifacts`. |
| [`../configure-coreelec-addons.sh`](../configure-coreelec-addons.sh) | yes | yes | Uses the same config grammar and secret boundary as provisioning. |
| [`../configure-kodi-lifecycle.sh`](../configure-kodi-lifecycle.sh) | no | yes | Controller identities are supplied only by `--controller-public-key` and `--controller-identity`. |

### Supported scalar keys

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

### Add-on artifact lock

`ADDON_ARTIFACT` records are `id|version|https-url|sha256`, one per line.
The shipped lock contains 42 records: the selected add-ons, their
repositories, the regional language resource, the managed Arctic Fuse optional
add-ons, two extra Python modules they introduce, and the remaining transitive
dependency closure. `--check-artifacts` downloads and verifies all 42 over
HTTPS.

### Precedence

1. Built-in defaults.
2. The selected configuration file (`--config PATH`, defaulting to the shared
   file above).
3. Explicit CLI options.
4. Secret variables from the repository-root `.env` file.

`--target HOST` is always supplied only on the command line.

## Arctic Fuse 3 managed contract

The shared baseline manages the following Arctic Fuse state:

- `Next Aired` is disabled by removing every case-insensitive
  `HomeSwitcher.1106.Toggle` and `HomeSwitcher.1106.UpNextMode` root setting
  before Kodi starts.
- Verification accepts either no `HomeSwitcher.1106.Toggle` match, an empty
  string-typed placeholder, or a bool-typed `false` placeholder recreated by
  the skin at runtime.
- `HomeSwitcher.1106.UpNextMode` is valid only when absent or represented by
  an empty string-typed placeholder.
- `HomeSwitcher.1101.*` opens `script.plexmod`.
- `HomeSwitcher.1102.*` opens `plugin://plugin.video.youtube/`.
- The managed Home order after Home is Plex, YouTube, PVR, Add-ons.
- Managed skin settings are normalized to one canonical root node per setting
  ID, with other case variants removed before verification.
- `RecentlyAiredEpisodes30Days.xsp` is the rolling previous 30 days with
  future dates excluded.
- `RecentlyReleasedMoviesCurrentYear.xsp` uses the device year captured during
  provisioning and is ordered by year descending.
- `RecentlyReleasedMovies90Days.xsp` is not written as a managed widget
  playlist and is removed during provisioning.
