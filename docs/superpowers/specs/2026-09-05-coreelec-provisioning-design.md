# CoreELEC Provisioning Configuration and Add-ons

## Purpose

Extend `provision-coreelec.sh` so a Ugoos AM6B-family device running
CoreELEC 21.3 can be brought to a repeatable, room-independent baseline
without remote-control input during provisioning. Keep display, receiver,
audio-codec, resolution-whitelist, HDMI, remote, hostname, and other
room/device choices outside this shared baseline.

The baseline will:

- load non-secret settings from a strict `.conf` file;
- keep credentials and API keys in environment variables;
- set and verify Pacific time and English/US regional defaults;
- deterministically install and verify the requested default add-ons;
- preconfigure only settings that are safe and supported without interactive
  authorization; and
- report every remaining manual step.

## Scope

### Included

- Strict configuration parsing and CLI override precedence.
- Existing SSH-key installation, SSH hardening, Kodi web access, backup, and
  audit behavior.
- CoreELEC and Kodi timezone configuration.
- Kodi English/US regional configuration.
- Pinned, checksum-verified add-on and dependency deployment.
- Default installation of:
  - Emby for Kodi Next Gen
  - PM4K
  - official Kodi YouTube
  - Arctic Fuse 3
  - NextPVR
  - Home Assistant Weather
- Supported unattended configuration and post-run manual-action reporting.
- Local validation tests that do not require a CoreELEC device.

### Excluded

- Room-specific display, audio, HDMI, EDID, Dolby Vision, remote, hostname,
  and network reservation choices.
- Automating OAuth, device-code, Emby user login, or other interactive
  authorization flows.
- Storing credentials in the repository or audit reports.
- Configuring a user-supplied TMDb API key. Current TMDb Helper releases do
  not expose such a setting.
- General-purpose provisioning for platforms other than the validated
  CoreELEC 21.3 Amlogic-ng target.

## Configuration Interface

Add a `--config PATH` option. Its default is:

`config/shared/ugoos-am6b-plus/coreelec-21.3/provision.conf`

The file is declarative, not shell code. The parser accepts:

- blank lines;
- comment lines whose first non-whitespace character is `#`;
- documented `KEY=value` entries; and
- repeatable `ADDON_ARTIFACT=id|version|url|sha256` entries.

It rejects malformed lines, unknown keys, duplicate scalar keys, unsupported
values, invalid artifact records, and keys reserved for secrets. Values are
trimmed only according to the documented grammar; they are never evaluated
as shell syntax.

The shared file contains platform and Kodi defaults, regional settings,
update policy, non-secret service endpoints, and a complete pinned artifact
manifest. `--target` remains required because the target is device-specific.
Existing CLI options remain supported and override corresponding config
values. Precedence is:

1. built-in safe defaults;
2. the selected configuration file;
3. explicit CLI options;
4. secret environment variables for secret-only fields.

The default shared configuration uses:

- CoreELEC release `21.3`;
- timezone country `United States`;
- timezone `America/Los_Angeles`;
- language resource `resource.language.en_us`;
- country/region `USA (12h)`;
- keyboard layout `English QWERTY`; and
- all six requested add-ons enabled in the installation set.

Supported secret environment variables are:

- `OMDB_API_KEY`
- `MDBLIST_API_KEY`
- `YOUTUBE_API_KEY`
- `YOUTUBE_CLIENT_ID`
- `YOUTUBE_CLIENT_SECRET`
- `HOME_ASSISTANT_TOKEN`
- `NEXTPVR_PIN`
- `PLEX_TOKEN`

The non-secret service keys are:

- `HOME_ASSISTANT_URL`, `HOME_ASSISTANT_WEATHER_ENTITY`, and
  `HOME_ASSISTANT_SUN_ENTITY`;
- `NEXTPVR_HOST`, `NEXTPVR_PORT`, `NEXTPVR_PROTOCOL`, and
  `NEXTPVR_INSTANCE_NAME`; and
- `PLEX_SERVER_HOST`, `PLEX_SERVER_PORT`, `PLEX_SERVER_NAME`, and
  `PLEX_PROFILE_IDS`.

A secret without its required non-secret companion values is a validation
error. Missing optional secrets are not errors.

## Deterministic Add-on Deployment

Kodi 21's `InstallAddon(id)` builtin opens confirmation and progress dialogs.
Kodi JSON-RPC can query, enable, and execute add-ons, but cannot install them.
The provisioner therefore will not use `InstallAddon` as its unattended
installation mechanism.

Each `ADDON_ARTIFACT` identifies one add-on or dependency ZIP. The manifest
must include the complete transitive dependency set for the selected
add-ons, including the US-English language resource. Every artifact is
version-pinned and SHA-256-pinned.

The deployment flow is:

1. Download all artifacts to a private local temporary directory over HTTPS.
2. Verify every checksum.
3. Inspect every ZIP before touching the target:
   - exactly one top-level add-on directory;
   - a readable `addon.xml`;
   - declared add-on ID and version match the manifest; and
   - no absolute or parent-traversal paths.
4. Transfer validated artifacts to a private remote staging directory.
5. Stop Kodi.
6. Back up every destination that may be replaced, along with affected Kodi
   settings and CoreELEC timezone state.
7. Expand artifacts into staging and atomically replace their add-on
   directories.
8. Write settings through temporary files followed by atomic rename.
9. Start Kodi even if a later deployment step fails.
10. Enable installed add-ons through JSON-RPC where necessary.
11. Verify ID, version, enabled state, active providers, and configured
    non-secret values.

The existing selective pre-provisioning backup will be extended to include
all paths affected by a run. Failed deployment leaves a dated backup and a
specific error. The implementation will restore replaced paths when a
failure occurs before successful Kodi restart and verification; if automatic
restoration itself fails, it will preserve both staged and backup paths and
report exact recovery instructions.

The default manifest includes the Emby, Don't Panic, and Jurialmunkey
repository add-ons so Kodi can discover future updates. Kodi's add-on update
policy defaults to notification rather than automatic installation. Initial
provisioning remains pinned and does not depend on repository refresh timing
or modal UI.

## Regional Baseline

Kodi settings will include:

- `locale.language=resource.language.en_us`
- `locale.country=USA (12h)`
- `locale.keyboardlayouts=English QWERTY`
- `locale.timezonecountry=United States`
- `locale.timezone=America/Los_Angeles`

The provisioner treats `United States` as the canonical Kodi 21
timezone-country value and fails verification if Kodi reports another value.

CoreELEC patches Kodi to write `/storage/.cache/timezone` when the timezone
changes through Kodi. Offline XML editing does not trigger that callback.
Because provisioning edits settings while Kodi is stopped, it will also
write:

```text
TIMEZONE=America/Los_Angeles
```

to `/storage/.cache/timezone` and restart `tz-data.service`.

Verification covers:

- the timezone cache value;
- `/etc/localtime` holding the requested zone, either as a symlink into the
  zoneinfo tree or as a plain copy byte-equal to that zone's file;
- local `date` output carrying the expected UTC offset, which is advisory
  because BusyBox may not expand `%Z%z` at all;
- Kodi JSON-RPC values for timezone, language, country, and keyboard layout;
  and
- presence and enabled state of `resource.language.en_us`.

## Add-on-specific Behavior

### Emby for Kodi Next Gen

- Add-on ID: `plugin.service.emby-next-gen`.
- Install and enable it.
- Do not preseed server credentials. Current Emby Next Gen stores server/user
  state in its own databases and uses dialog-driven server and user setup.
- Report Emby server selection and user login as manual steps.

### PM4K

- Add-on ID: `script.plexmod`.
- Install and enable it.
- If the configured local Plex server details and `PLEX_TOKEN` are present,
  preseed PM4K local mode using its `local_servers_json`,
  `local_profiles_json`, `local_mode`, and `allow_insecure` settings.
- Otherwise report Plex linking/local-server setup as manual.
- Never write the Plex token to the audit report.

### YouTube

- Add-on ID: `plugin.video.youtube`.
- Install and enable it.
- Default language and region to `en-US` and `US`.
- Suppress the add-on's first-run settings wizard only after provisioning the
  corresponding values.
- If all three personal OAuth values are present, write the supported
  `api_keys.json` structure while Kodi is stopped.
- Personal API credentials are optional because the add-on supports bundled
  developer credentials.
- Always report Google device authorization as manual when sign-in is
  desired. Provisioning cannot complete that interactive flow.

### Arctic Fuse 3 and TMDb Helper

- Skin ID: `skin.arctic.fuse.3`.
- Dependency ID: `plugin.video.themoviedb.helper`.
- Install the skin and its full dependency set, then activate Arctic Fuse 3.
- Write `OMDB_API_KEY` to TMDb Helper's `omdb_apikey` setting when present.
- Write `MDBLIST_API_KEY` to TMDb Helper's `mdblist_apikey` setting when
  present.
- Do not write these values into the skin's settings.
- Do not accept or report a `TMDB_API_KEY` setting. TMDb Helper currently
  embeds its application key and exposes only optional interactive TMDb user
  authorization.
- Leave optional Trakt and TMDb user authorization as manual steps.

### NextPVR

- Add-on ID: `pvr.nextpvr`.
- Install and enable the CoreELEC-compatible binary artifact.
- When a host and `NEXTPVR_PIN` are supplied, write Kodi 21's
  `instance-settings-1.xml`, including the instance name and enabled state.
- Enable Kodi PVR management when NextPVR is configured.
- Otherwise, when no instance exists yet, write a disabled, credential-free
  placeholder and report host/PIN setup as manual. This keeps the add-on itself
  enabled without Kodi attempting the generated `127.0.0.1:8866` default
  instance and disabling the add-on after its permanent connection failure.
  Preserve an existing instance so a later run without the environment-only
  PIN cannot disable configuration completed during an earlier run or in Kodi.

### Home Assistant Weather

- Add-on ID: `weather.ha`.
- Install and enable it.
- When a Home Assistant URL, forecast entity, and
  `HOME_ASSISTANT_TOKEN` are supplied, write the add-on's flat-format
  settings and set `weather.addon=weather.ha`.
- Otherwise leave the existing weather provider unchanged and report Home
  Assistant Weather setup as manual.
- Never write the Home Assistant token to the audit report.

## Error Handling and Idempotency

- Validate local configuration and artifacts before opening an SSH
  connection where possible.
- Do not stop Kodi until every artifact has downloaded and passed validation.
- Treat requested installation or configuration verification failures as
  fatal, not warnings.
- Preserve the current warning-only behavior only for explicitly
  environmental checks that cannot invalidate applied state, such as a local
  firewall blocking the Mac from reaching Kodi JSON-RPC. Where remote
  localhost JSON-RPC can verify the same state, use it instead.
- Re-running with the same configuration does not rewrite matching add-on
  versions unnecessarily.
- Re-running applies changed non-secret settings and newly supplied secrets
  without duplicating XML entries or add-on instances.
- Secret values are excluded from command lines, logs, process listings,
  reports, and world-readable files. Temporary secret files use mode `0600`
  and are removed by traps.
- Unknown or unsupported configuration is rejected rather than silently
  ignored.

## Reporting

The audit report will retain platform and hardware inventory and add:

- configuration file path and a non-secret configuration fingerprint;
- expected and observed regional values;
- requested and observed add-on IDs and versions;
- installed/enabled/configured status for each add-on;
- active skin and weather provider;
- whether each optional secret was supplied, never its value;
- verification failures; and
- a consolidated manual-actions section.

Expected manual actions include Emby login, YouTube device authorization,
optional Plex linking when local mode is not configured, and optional
TMDb Helper account integrations.

## Validation and Tests

Add a local configuration-validation mode that requires no target and makes
no network changes. It validates the parser, semantic relationships, artifact
record shape, URLs, versions, and SHA-256 syntax. Network download and ZIP
inspection can be enabled explicitly so offline syntax checks remain useful.

Focused shell tests will cover:

- defaults, config values, CLI precedence, and repeated artifacts;
- comments, whitespace, and permitted empty optional values;
- malformed lines, unknown keys, duplicate scalar keys, and forbidden secret
  keys;
- companion-value requirements for supplied secrets;
- checksum mismatch, ID/version mismatch, and unsafe ZIP entries;
- idempotent XML setting updates;
- add-on manual/configured status classification; and
- secret redaction from logs and reports.

Validation after implementation will run the focused tests and `bash -n`.
Device-dependent behavior will additionally require a CoreELEC 21.3 test run;
the resulting audit report is the acceptance record for remote settings and
add-on verification.

## Primary References

- Kodi built-in add-on installation:
  <https://github.com/xbmc/xbmc/blob/Omega/xbmc/interfaces/builtins/AddonBuiltins.cpp>
- Kodi JSON-RPC add-on methods:
  <https://github.com/xbmc/xbmc/blob/Omega/xbmc/interfaces/json-rpc/schema/methods.json>
- Kodi regional settings:
  <https://github.com/xbmc/xbmc/blob/Omega/system/settings/settings.xml>
- CoreELEC 21 timezone patch:
  <https://github.com/CoreELEC/CoreELEC/blob/coreelec-21/packages/mediacenter/kodi/patches/kodi-100.08-setup-timezone.patch>
- Emby for Kodi Next Gen:
  <https://github.com/MediaBrowser/plugin.video.emby/tree/next-gen-dev-python3>
- PM4K:
  <https://github.com/pannal/plex-for-kodi/tree/develop_kodi21>
- Kodi YouTube:
  <https://github.com/anxdpanic/plugin.video.youtube>
- YouTube personal API keys:
  <https://github.com/anxdpanic/plugin.video.youtube/wiki/Personal-API-Keys>
- Arctic Fuse 3:
  <https://github.com/jurialmunkey/skin.arctic.fuse.3/tree/omega>
- TMDb Helper:
  <https://github.com/jurialmunkey/plugin.video.themoviedb.helper>
- NextPVR:
  <https://github.com/kodi-pvr/pvr.nextpvr/tree/Omega>
- Home Assistant Weather:
  <https://github.com/Eugeniusz-Gienek/kodi_weather_ha>
