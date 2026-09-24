# Profile reference

This reference is for maintainers and agents editing the Ugoos AM6B+ /
CoreELEC 21.3 Profile or a Room Overlay. Use the terms from `CONTEXT.md`:
Device, Profile, Room Overlay, Desired State, Resource, State Address, Change,
Effect, Plan, Run, Verification, Convergence, Fail Forward and Guided Action.

The Reconciler is a controller-only, on-demand tool. It observes Resources,
plans Changes, applies them, and verifies Convergence. It is built to the
trusted home-appliance bar in [ADR 0007](../adr/0007-trusted-home-appliance-bar.md):
prefer simple declarations and real-Device acceptance over machinery for rare
failures.

## Layout

The shared Profile lives under:

```text
config/shared/ugoos-am6b-plus/coreelec-21.3/
|-- profile.yaml
|-- addons.yaml
|-- playlists.yaml
|-- shortcuts.yaml
|-- documents.yaml
|-- settings.yaml
|-- documents/
`-- patches/
```

The Room Overlay lives under `config/rooms/<room>/room.yaml`; the current room
is `config/rooms/theater/room.yaml`.

The directory name records the hardware model and Kodi/CoreELEC version chosen by ADR 0019.
It is a human-facing name. The Profile still declares and Guards the platform
explicitly.

The platform is Ugoos AM6B+, CoreELEC 21.3 Omega
`Amlogic-ng.arm`. Profile 7 FEL Dolby Vision needs the matching 21.3 `-ng`
image and `dovi.ko`.

## Command surface

The entry point is declared in `pyproject.toml`:

```console
uv run coreelec-reconciler --help
```

The command is one positional argument plus shared options:

```console
uv run coreelec-reconciler bootstrap --room theater
uv run coreelec-reconciler plan --room theater
uv run coreelec-reconciler apply --room theater
uv run coreelec-reconciler survey --room theater
uv run coreelec-reconciler record-patches --room theater
```

`--config-root` defaults to `config`. `--env-file` defaults to `.env`.
`plan` mutates nothing. `apply` performs a Run and then plans again for
Verification. `survey` mutates nothing and refuses to run while Kodi is active.
`record-patches` touches no Device.

Tests and maintainer scripts treat the package entry point as the boundary,
per [ADR 0011](../adr/0011-linux-only-ci-and-boundary-tests.md). Do not write
documentation that tells a maintainer to import private modules to inspect a
Profile.

## Schema rules

Configuration is strict. Unknown keys, missing required keys, duplicate State
Addresses, duplicate add-on ids, unknown dialects, unknown transforms and bad
modes fail while Desired State is read, before the Device is contacted. This is
deliberate: a typo should fail loudly rather than produce a Plan for the wrong
address.

Paths that name Device documents are absolute. Sources and Artifact Patches are
relative to the Profile directory and must stay inside it, so the Profile can
be copied as a unit.

## `profile.yaml`

`profile.yaml` names the Profile, the platform Guard, Profile Constants,
Device addresses, SSH transport, and who may log in.

### Platform Guard

Every Run checks the hostname, the operating system identity, release string
and sound card before planning Changes:

```yaml
platform:
  id: coreelec
  version: "21.3"
  device: Amlogic-ng
  release_contains: Amlogic-ng.arm-21.3-Omega
  sound_card: AMLAUGESOUND
```

The sound-card Guard exists because the Profile's audio settings use ALSA
strings containing `CARD=AMLAUGESOUND`. Kodi can fall back quietly if that card
is wrong, so the Guard fails early instead.

### Profile Constants

Use `constants` for committed values taken by more than one State Address:

```yaml
constants:
  timezone: America/Los_Angeles
```

A setting takes the value with `from_profile`:

```yaml
- setting: locale.timezone
  from_profile: timezone
```

A Profile Constant is committed, reviewable and printable. It is not a Named
Value.

### Device addresses

The Profile declares Device addresses whose meaning the Reconciler knows:

```yaml
addresses:
  timezone_cache: /storage/.cache/timezone
  sshd_conf: /storage/.cache/services/sshd.conf
  addons: /storage/.kodi/addons
  addon_database: /storage/.kodi/userdata/Database/Addons33.db
  addon_manifest: /usr/share/kodi/system/addon-manifest.xml
```

The address changes with a platform version; the meaning stays in code. The
add-on database filename carries Kodi's schema version, so it belongs here
rather than in the Reconciler.

### Transport and authorized keys

The current transport is:

```yaml
transport:
  user: root
  port: 22
  identity: ~/.ssh/coreelec_admin_ed25519
```

The administrator key is derived from that identity's `.pub` file and is always
kept. Other entries are declared in `authorized_keys`:

```yaml
authorized_keys:
  document: /storage/.ssh/authorized_keys
  entries:
    - comment: homeassistant-ugoos-kodi-lifecycle
      from_env: COREELEC_LIFECYCLE_PUBLIC_KEY
      forced_command: /storage/.config/kodi-lifecycle
```

Each declared entry carries a forced command. The Home Assistant key may run
only the Kodi Lifecycle gateway document declared in `documents.yaml`. First
Contact is owned by the Reconciler; see
[ADR 0016](../adr/0016-the-reconciler-owns-first-contact.md).

### Password window and `sshd` Effect

The first-boot wizard leaves password SSH available. Desired State closes that
window through the CoreELEC service document in `settings.yaml`:

```yaml
- document: /storage/.cache/services/sshd.conf
  dialect: shell_vars
  mode: "0644"
  settings:
    - setting: SSH_ARGS
      value: "-o 'PasswordAuthentication no'"
    - setting: SSHD_DISABLE_PW_AUTH
      value: "true"
```

Applying either address restarts `sshd.service`. The restart drops the SSH
connection that requested it, so the Reconciler reconnects and verifies the
Device answers with key-only access.

## Smart Playlists

Declare Smart Playlists in `playlists.yaml`:

```yaml
smart_playlists:
  directory: /storage/.kodi/userdata/playlists/video
  kodi_directory: special://profile/playlists/video
  playlists:
    - file: NewMovies.xsp
      name: New Movies
      type: movies
      match: all
      limit: 50
      order:
        field: dateadded
        direction: descending
      rules:
        - field: playcount
          operator: is
          value: "0"
```

`directory` is the Device path. `kodi_directory` is the same location as Kodi
addresses it from a skin. A rule whose operator carries the full test, such as
`inprogress` with `true`, declares `value: ""`.

### Calendar-moving rules

Kodi's `year` field has no relative operator, so rules based on the current
year use an offset and a named base:

```yaml
- field: year
  operator: greaterthan
  value: -2
  relative_to: current_year
```

`current_year` is resolved on every read. A literal year would become wrong on
1 January.

## Shortcut Nodes

Declare Arctic Fuse Shortcut Nodes in `shortcuts.yaml`:

```yaml
shortcut_nodes:
  - document: /storage/.kodi/userdata/addon_data/script.skinvariables/nodes/skin.arctic.fuse.3/skinvariables-shortcut-homewidgets.json
    shortcuts:
      - guid: coreelec-home-new-shows
        playlist: NewShows.xsp
        target: videos
      - guid: coreelec-home-new-movies
        playlist: NewMovies.xsp
        target: videos
```

A shortcut states exactly one of `playlist` and `path`. `playlist` names a
Smart Playlist declared by the Profile and supplies the path and label.
`path` carries a Kodi built-in or a target supplied by another add-on, and
then the shortcut declares its own `label`.

Every `guid` is declared. The skin generates random IDs for shortcuts without
one, which would plan a Change on every Run.

## Documents shipped as files

Declare byte-for-byte documents in `documents.yaml`:

```yaml
documents:
  - document: /storage/.config/kodi-lifecycle
    source: documents/kodi-lifecycle
    mode: "0700"
```

`source` is relative to the Profile directory and must stay inside it. `mode`
is required because the current document is executable. The Reconciler owns
the whole document and replaces it whole when it changes.

## Settings Documents

Declare Settings Documents in `settings.yaml` or in a Room Overlay. A Settings
Document owns individual State Addresses inside a file and preserves the rest.

```yaml
settings_documents:
  - document: /storage/.kodi/userdata/guisettings.xml
    dialect: guisettings
    settings:
      - setting: videolibrary.flattentvshows
        value: "1"
```

A document states exactly one of `document` and `document_glob`. A literal
`document` may contain `*` as a filename character; it is not a pattern.

### Dialects

The dialect is declared and never guessed:

| Dialect | Shape | Example |
| --- | --- | --- |
| `guisettings` | Kodi settings XML | `guisettings.xml` |
| `addon_v2` | versioned add-on settings XML | `pvr.nextpvr` |
| `skin` | skin settings XML with `type` | Arctic Fuse settings |
| `addon_v1` | flat add-on settings XML | `weather.ha` and CEC |
| `json` | dotted paths into JSON | skin view types |
| `shell_vars` | `KEY=value` lines | timezone and `sshd.conf` |

Kodi rewrites `guisettings`, add-on, skin and peripheral Settings Documents
from memory when it exits. That is why a Settings Document Change always takes
the Kodi restart Effect; see
[ADR 0013](../adr/0013-a-settings-document-always-takes-the-kodi-stop.md).

Skin settings need `type="string"` or `type="bool"`. Kodi's skin loader drops
untyped values, so Verification would otherwise see a file that the skin
ignored.

### Declaring a setting

A setting states exactly one of `value`, `from_env`, `from_profile` and
`unset`:

```yaml
- setting: services.webserverpassword
  from_env: KODI_WEB_PASSWORD
```

`from_env` names a Named Value in `.env`. The value is read before Device
contact, is never printed, and is rejected if missing or empty. Use it for the
Home Assistant URL and token, NextPVR host and PIN, TMDb Helper keys, Kodi web
password, and the Home Assistant lifecycle public key. See
[ADR 0014](../adr/0014-desired-state-names-a-value-it-may-not-hold.md).

A Cleared Address states `unset: true`:

```yaml
- setting: optionstiles.03.path
  unset: true
```

It means the Device must resolve no value. Do not use `value: ""`; Kodi reads
an empty node as no value, so a literal empty string would never converge.
When a slice first declares a Cleared Address, set a junk value on the real
Device, run `apply`, and show a later `plan` stays clean. That is the only
acceptance check that catches a typo in an address whose desired Observation
is no value.

### Naming a document the Profile cannot know

Kodi names the CEC peripheral document from the adapter identity, so the
Profile declares a pattern:

```yaml
- document_glob: /storage/.kodi/userdata/peripheral_data/cec_*.xml
  dialect: addon_v1
  settings:
    - setting: standby_pc_on_tv_standby
      value: ignore
      transform: cec_tv_off_action
```

A Run resolves the pattern on the Device and requires exactly one match. CEC
acceptance needs a full Kodi stop/start before the final re-plan because the
peripheral document is rebuilt from Kodi memory at exit.

### Room-scoped Kodi settings and transforms

Room-specific Display and audio state belongs in `config/rooms/<room>/room.yaml`:

```yaml
settings_documents:
  - document: /storage/.kodi/userdata/guisettings.xml
    dialect: guisettings
    settings:
      - setting: coreelec.amlogic.disabledolbyvision
        value: "true"
        transform: invert
      - setting: coreelec.amlogic.dolbyvisionled
        value: tv-led
        transform: dolby_vision_mode
      - setting: audiooutput.truehdpassthrough
        value: "true"
```

The Profile and Room Overlay merge per document. They must agree on the
dialect. A room may add addresses the Profile does not declare; declaring the
same address on both sides is an error.

Current transforms are:

| Transform | Declared | Device value |
| --- | --- | --- |
| `invert` | `true` | `false` |
| `invert` | `false` | `true` |
| `dolby_vision_mode` | `tv-led` | `0` |
| `dolby_vision_mode` | `player-led` | `1` |
| `cec_tv_off_action` | `ignore` | `36028` |

`videoscreen.resolution` is not declared. Kodi recomputes that ordinal from
the live Display mode at startup, so it is not stable Desired State. The
room's stable video declaration is the whitelist and Dolby Vision settings.

## Add-ons

`addons.yaml` is the Artifact Lock. Each record declares the installed version,
source URL, SHA-256 digest, role, and notes:

```yaml
addons:
  - id: script.plexmod
    version: "1.3.19"
    url: https://raw.githubusercontent.com/pannal/dontpanickodi/eba134ac09bfe4916b3511d1e377bf6bb03a947e/omega/zips/script.plexmod/script.plexmod-1.3.19.zip
    sha256: "885b48b724a525a1412df09db8c69f4ec0eebb6da06d6e0509df097b3ac19816"
    role: chosen
    notes: >-
      The latest published stable PM4K release, taken from an immutable commit
      in the publisher's own Don't Panic repository rather than from the
      moving master branch.
```

Appearing in the lock means the add-on should be installed at that version and
enabled. The Reconciler fetches the Artifact, verifies the digest, checks the
expanded `addon.xml`, ships the tree, and writes enablement to Kodi's add-on
database while Kodi is stopped. See
[ADR 0017](../adr/0017-pin-add-on-artifacts-and-patch-the-broken-ones.md) and
[ADR 0018](../adr/0018-enable-add-ons-in-kodis-database-while-kodi-is-stopped.md).

`role` is one of `chosen`, `dependency` and `repository`. `notes` explains why
this version is pinned when there is something to explain; otherwise it is
`~`.

### Artifact Patches

Some Artifacts carry targeted patches. The diffs live under
`patches/<addon-id>/`, and the add-on record lists them:

```yaml
patches:
  - 0001-guard-a-home-window-that-is-gone.patch
patched_files:
  lib/monitor.py: "ab3d01700339e2c3f6690c954ebae76c13b6246d87087b973bb18ed7e7b15dac"
```

Each patch records the add-on id and version it was written for. A Run applies
patches on the controller after verifying the pinned bytes and before shipping
the finished tree to the Device. Patched Python files are compiled before the
Device is touched.

`patched_files` records what each patch produces. A patched add-on is observed
by its Kodi version and by those file hashes; otherwise correcting a patch
without changing the add-on version would never plan a Change. Generate those
hashes with:

```console
uv run coreelec-reconciler record-patches --room theater
```

`record-patches` contacts no Device.

### What a Run observes and applies

A Run observes `/storage/.kodi/addons/<id>/addon.xml`, the enabled row in
`Addons33.db`, and patched file hashes when a record has Artifact Patches. An
undeclared add-on is reported but does not fail the Run; no current slice has
chosen a removal behaviour.

Everything that can fail on the controller fails before Kodi is stopped:
fetching, digest verification, archive safety checks, patch application and
syntax checks. Apply then stops Kodi once, ships all needed add-ons, updates
the database, starts Kodi, and verifies Convergence.

## Effects

A Run takes each Effect once, no matter how many Changes need it.

- **Kodi restart Effect.** Settings Documents, Shortcut Nodes and add-on
  Changes stop and start `kodi.service` as needed. Kodi rewrites many
  Settings Documents from memory on exit, so the stop is part of the Resource
  Type rather than an optional declaration
  ([ADR 0013](../adr/0013-a-settings-document-always-takes-the-kodi-stop.md)).
- **View rebuild Effect.** The skin view-types JSON declares `compiles_to`:

  ```yaml
  compiles_to: /storage/.kodi/addons/skin.arctic.fuse.3/1080i/script-skinviewtypes-includes.xml
  ```

  When that source changes, the Run writes the skin's build trigger stub and
  waits for the include to be regenerated
  ([ADR 0015](../adr/0015-trigger-the-view-rebuild-the-way-the-skin-does.md)).
- **Timezone Effect.** `/storage/.cache/timezone` is read by `tz-data.service`.
  When it changes, the Run restarts that oneshot and verifies
  `/var/run/localtime` names the declared zone.
- **`sshd` Effect.** Changes to `/storage/.cache/services/sshd.conf` restart
  `sshd.service`, then reconnect and verify key-only access.

## Surveying Unmanaged State

`survey` reports how a Device differs from the Profile and mutates nothing:

```console
uv run coreelec-reconciler survey --room theater
```

Kodi must be stopped and kept stopped. The report is sorted so two surveys can
be diffed. Use it to read back hand configuration before declaring it, or to
compare two Devices after a Run.

## Failure semantics

There is no rollback. A Run that fails partway reports what it did and exits
non-zero. Run `apply` again after fixing the cause. Disaster recovery is
re-imaging the card and reconciling again. This is Fail Forward, recorded in
[ADR 0009](../adr/0009-fail-forward-and-exclusive-execution-ownership.md).

## Standing acceptance guidance

When a new slice first exercises a file or execution capability, inject drift
on the real Device and show `apply` repairs it.

On a provisioned Device, a newly declared State Address should not plan as
`create`. A `create` usually means a typo, wrong dialect, wrong filename or a
path Kodi does not read.

For a new Cleared Address, inject a junk value and show `apply` clears it and
a later `plan` remains clean.

For CEC, stop Kodi, inject the wrong values, start Kodi so the values reach
memory, run `apply`, then do a full Kodi stop/start before the final `plan`.
