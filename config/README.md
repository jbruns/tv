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
defaults, audio output device intent, add-on update policy, site-specific
endpoint placeholders, and the locked add-on artifact set. Keep
room-specific hostname/reservation values, HDMI topology, Dolby Vision mode,
whitelist entries, and audio passthrough/channel-layout choices outside this
file.

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
- `HOME_ASSISTANT_URL`
- `HOME_ASSISTANT_TOKEN`
- `NEXTPVR_HOST`
- `NEXTPVR_PIN`
- `TMDB_API_KEY` — reserved and rejected, but not a usable `.env` input

Secret requirements:

- `KODI_WEB_PASSWORD` is required when `APPLY_KODI=1` and by live add-on
  validation.
- `OMDB_API_KEY` and `MDBLIST_API_KEY` are required together for real
  `APPLY_KODI=1` deployments; both are optional for `--check-config` and
  `--check-artifacts`.
- `HOME_ASSISTANT_TOKEN` requires `HOME_ASSISTANT_URL`.
- `NEXTPVR_PIN` requires `NEXTPVR_HOST`.

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

## Room configuration surface

`--component room --room NAME` reads a separate file:

```text
config/rooms/<room>/room.conf
```

It is a distinct file with its own key allowlist, parsed by the same strict
grammar above. The two allowlists are disjoint by name in both directions: a
`provision.conf` key written into a room file is rejected as an unknown room
configuration key, and a room key written into `provision.conf` is rejected
as an unknown configuration key. Room files hold no secrets; the same reserved
secret keys listed above are rejected outright from a room file too.

Every one of the following eleven keys is required; there is no default for
any of them, because a silent default for a display or audio setting is
exactly the unverifiable state the `room` component exists to eliminate.

| Key | Accepted values |
| --- | --- |
| `ROOM_DISPLAY_RESOLUTION` | a resolution label, e.g. `3840x2160p` |
| `ROOM_DISPLAY_WHITELIST` | comma-separated Kodi display mode strings |
| `ROOM_DOLBY_VISION` | `0` or `1` (stated positively; see below) |
| `ROOM_DOLBY_VISION_MODE` | `tv-led` or `player-led` |
| `ROOM_AUDIO_PASSTHROUGH` | `0` or `1` |
| `ROOM_AUDIO_AC3` | `0` or `1` |
| `ROOM_AUDIO_EAC3` | `0` or `1` |
| `ROOM_AUDIO_DTS` | `0` or `1` |
| `ROOM_AUDIO_TRUEHD` | `0` or `1` |
| `ROOM_AUDIO_DTSHD` | `0` or `1` |
| `ROOM_AUDIO_CHANNELS` | a layout label: `2.0`, `2.1`, `3.0`, `3.1`, `4.0`, `4.1`, `5.0`, `5.1`, `7.0`, or `7.1` |

`ROOM_DOLBY_VISION` is written inverted onto Kodi's own
`coreelec.amlogic.disabledolbyvision` setting: `ROOM_DOLBY_VISION=1` writes
`disabledolbyvision=false`. There is no Atmos key; Atmos rides on
`ROOM_AUDIO_TRUEHD` and `ROOM_AUDIO_EAC3`. `ROOM_AUDIO_CHANNELS` governs only
decoded (non-bitstreamed) audio and does not affect any passthrough codec
above; see [managed audio output](../docs/devices/ugoos-am6b-plus/audio-output.md)
for how its label resolves to Kodi's channel setting. The full meaning of
every key, the display mode string format, and the pre-transaction display
probe are documented in the
[room desired-state reference](../docs/devices/ugoos-am6b-plus/room-desired-state.md).

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
| `AUDIO_DEVICE` | `hdmi-multichannel` | `analog`, `sysdefault`, `hdmi-multichannel`, `spdif`, or `hdmi` |
| `AUDIO_PASSTHROUGH_DEVICE` | `hdmi` | `analog`, `sysdefault`, `hdmi-multichannel`, `spdif`, or `hdmi` |
| `HOME_ASSISTANT_WEATHER_ENTITY` | unset | identifier charset |
| `HOME_ASSISTANT_SUN_ENTITY` | unset | identifier charset |
| `NEXTPVR_PORT` | unset, required with a host | `1`-`65535` |
| `NEXTPVR_PROTOCOL` | unset, required with a host | `http` or `https` |
| `NEXTPVR_INSTANCE_NAME` | unset | free-text display charset |
| `ADDON_UNMANAGED_ALLOWED` | unset | comma-separated add-on IDs |
| `ADDON_ARTIFACT` | (41 records shipped) | repeatable, see below |

`NEXTPVR_PORT` and `NEXTPVR_PROTOCOL` are both required whenever
`NEXTPVR_HOST` is set, and provisioning fails naming the missing key rather
than assuming NextPVR's stock `8866`/`http`. A guessed backend address is
plausible enough to be written and wrong enough to be unreachable, and the
post-deploy connectivity check skips itself when these keys are unset — so the
guess was never tested. The host and PIN are secrets and belong in `.env`; the
address the client dials is a deployment fact and belongs in the profile.

`ADDON_UNMANAGED_ALLOWED` acknowledges add-ons that are expected on a device
but deliberately absent from the artifact lock, such as the metadata scrapers
Kodi installs on first boot. They are still inventoried in the report, but do
not count as drift.

`AUDIO_DEVICE` and `AUDIO_PASSTHROUGH_DEVICE` state intent, not the concrete
ALSA device string; a pre-transaction probe resolves the intent against
whatever the running Kodi reports. See
[managed audio output](../docs/devices/ugoos-am6b-plus/audio-output.md) for
the resolution mechanism and the report statuses it produces.

### Add-on artifact lock

`ADDON_ARTIFACT` records are `id|version|https-url|sha256`, one per line.
The shipped lock contains 41 records: the selected add-ons, their
repositories, the regional language resource, the managed Arctic Fuse optional
add-ons, the pinned From Ashes UI sound theme, two extra Python modules they
introduce, and the remaining transitive dependency closure. `--check-artifacts`
downloads and verifies all 41 over HTTPS.

### Precedence

1. Built-in defaults.
2. The selected configuration file (`--config PATH`, defaulting to the shared
   file above).
3. Explicit CLI options.
4. Secret variables from the repository-root `.env` file.

`--target HOST` is always supplied only on the command line.

## Provisioning component contract

Components are CLI selectors, not `provision.conf` keys. With no explicit
`--component`, `provision-coreelec.sh` requests `baseline`, preserving the full
shared baseline. A legacy `--addon ID` invocation also keeps that full baseline
and narrows only the artifact set. When components are explicit, each
`--addon ID` additionally requests `addons`.

| Component | Owned state |
| --- | --- |
| `core` | Regional, locale, timezone, keyboard, Kodi web-access, update-policy, the shared audio output/passthrough device intent, and the shared non-room Kodi library and file-list preferences; the timezone cache and `/etc/localtime` |
| `cec` | Exactly one detected Kodi CEC peripheral file: `activate_source=0`, `wake_devices=231`, `standby_devices=231`, `standby_tv_on_pc_standby=0`, and `standby_pc_on_tv_standby=36028` (reported as `cec.tv_off_action`) |
| `addons` | The selected, checksum-locked artifacts and their installed add-on directories |
| `services` | Settings owned by `plugin.video.themoviedb.helper`, `weather.ha`, `pvr.nextpvr`, and `script.plexmod` |
| `skin` | Active Arctic Fuse selection, Arctic Fuse settings, Skin Variables widget JSON, managed video playlists, and the skin-owned sound skin |
| `room` | Owns display and audio state in `config/rooms/<room>/room.conf`: the desktop resolution, the display mode whitelist, both Dolby Vision settings, the six audio passthrough flags, and the decoded-audio channel layout in `guisettings.xml`. Opt-in: never expanded from `baseline`; must be requested explicitly with `--component room --room NAME` |
| `baseline` | Alias for every implemented component: `core,cec,addons,services,skin`; it excludes `room`, which is opt-in |

Dependencies are expanded before device contact, cycle-checked, and reported
in stable effective order:

| Requested component | Added dependencies |
| --- | --- |
| `core` | none |
| `cec` | none |
| `addons` | none |
| `services` | `addons` |
| `skin` | `core`, `addons` |
| `room` | `core`, because the whitelist only takes effect once `core`'s `videoplayer.adjustrefreshrate=2` is in place |
| `baseline` | expands to `core,cec,addons,services,skin` |

Use `--print-component-plan` to inspect normalization without contacting a
device. Unknown or unimplemented names, `--no-kodi` combined with
`--component`, dependency cycles, and empty effective plans fail locally.
Non-add-on scopes use a valid empty private artifact manifest and neither
download nor stage add-on archives.

Component scope controls Kodi/add-on mutation paths, rollback capture,
verification, and component report fields. Platform identification,
administrator-key installation, optional SSH hardening, transaction identity,
and rollback capability remain shared transaction invariants. A failed scoped
verification rolls back only the paths in that scoped transaction; the dated
operational backup remains available.

## Arctic Fuse 3 managed contract

The shared baseline manages the following Arctic Fuse state. It does not
provision YouTube.

- `HomeSwitcher.1101.*` is the TV Shows hub, `HomeSwitcher.1102.*` is the
  Movies hub, and `HomeSwitcher.1103.*` opens `script.plexmod`.
- The managed top-level order after Home is TV Shows, Movies, Plex,
  conditional PVR, Add-ons.
- Home retains its six managed widgets in order: In-Progress Movies,
  In-Progress Shows, Recently Aired Shows, Recently Released Movies, New
  Shows, and New Movies.
- TV Shows uses `skinvariables-shortcut-1101widgets.json` with widgets in
  order: In-Progress Shows, Recently Aired Shows, Trakt Popular TV Shows, and
  New Shows.
- Movies uses `skinvariables-shortcut-1102widgets.json` with widgets in
  order: In-Progress Movies, Recently Released Movies, Trakt Weekend Box
  Office, and New Movies.
- Managed skin and Kodi settings are normalized to one canonical root node per
  setting ID, with nested copies and other case variants removed before
  verification.
- `RecentlyAiredEpisodes30Days.xsp` is the rolling previous 30 days with
  future dates excluded.
- `TraktPopularTVShows.xsp` and `TraktWeekendBoxOffice.xsp` are tag-driven
  playlists. The stable Emby 11.1.27 client still requires manual sign-in;
  server/library metadata supplies the `trakt-popular` and
  `trakt-weekend-box-office` tags after library synchronization.
- `RecentlyReleasedMoviesCurrentAndPreviousYear.xsp` uses numeric year
  semantics: `year > current year - 2` and `year < current year + 1`. That
  includes the current and previous calendar years while excluding future
  years.
- `RecentlyReleasedMoviesCurrentYear.xsp` and
  `RecentlyReleasedMovies90Days.xsp` are removed during provisioning.
- The Weather tile and the built-in PVR hub are conditional: Weather appears
  only when Home Assistant weather is fully configured, and PVR appears only
  when NextPVR host and PIN are configured. The Weather tile's `path` and
  `target` fields are removed in both configurations.
- The regional baseline settings are `locale.language`, `locale.country`,
  `locale.keyboardlayouts`, `locale.timezonecountry`, and `locale.timezone`.
- The shared library and file-list preferences belong to `core`, and each one
  is verified on its own report key (`library.<setting id>`) against what Kodi
  itself reports over JSON-RPC: `filelists.showparentdiritems`,
  `filelists.showextensions`, `filelists.showaddsourcebuttons`,
  `videolibrary.showallitems`,
  `videolibrary.tvshowsselectfirstunwatcheditem`,
  `videolibrary.flattentvshows`, `videolibrary.ignorevideoextras`,
  `videolibrary.ignorevideoversions`, and `input.enablemouse`. Drift in any one
  of them fails verification and names the setting that drifted.
- `lookandfeel.soundskin` is the only Kodi default the `skin` component owns,
  and it is pinned to `resource.uisounds.fromashes`.
